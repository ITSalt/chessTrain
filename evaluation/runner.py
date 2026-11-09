"""A/B/C execution with fixed settings and per-attempt cost reservations."""
from copy import deepcopy
import hashlib
import json

from .adapters import Request
from .costs import Ledger, money
from .data import number, prompt_context, require, validate


def run(dataset, config, provider, engine):
    data = validate(dataset)
    require(bool(config.get('version')), 'config version required')
    require(isinstance(config.get('model'), str) and config['model']
            and 'latest' not in config['model'].lower(), 'exact model ID required')
    require(isinstance(config.get('parameters'), dict), 'explicit parameters required')
    require(isinstance(config.get('engine_budget'), dict) and config['engine_budget'], 'engine budget required')
    require(type(config.get('retries', 0)) is int and 0 <= config.get('retries', 0) <= 3,
            'transport retries must be between zero and three')
    bound = money(config['per_attempt_upper_bound'])
    require(bound > 0, 'positive bound required')
    if provider.live:
        require(bool(config.get('budget_approval_reference')), 'live calls require approved budget reference')
        require(money(config['spend_limit']) > 0, 'live calls require positive limit')
    for amount in data.get('workload_units', {}).values():
        money(amount)
    ledger = Ledger(deepcopy(config['tariff']), config['spend_limit'])
    cases = [c for c in data['cases'] if c['split'] == 'holdout' and not c['exclusion_reason']]
    # Preflight all contexts before any provider call. Reuse exactly the same engine facts.
    contexts = []
    for case in cases:
        facts = engine.analyze(deepcopy(case['position']), deepcopy(config['engine_budget']))
        contexts.extend((case, variant, prompt_context(data, case, variant, facts))
                        for variant in ('A', 'B', 'C'))
    result = {'dataset_version': data['dataset_version'], 'protocol_version': data['protocol_version'],
              'prompt_revision': data['prompt_revision'], 'config': deepcopy(config),
              'input_sha256': hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
              'synthetic': data['synthetic'], 'status': 'complete', 'responses': [],
              'excluded': [{'case_id': c['id'], 'reason': c['exclusion_reason']}
                           for c in data['cases'] if c['split'] == 'holdout' and c['exclusion_reason']],
              'input_holdout_count': sum(c['split'] == 'holdout' for c in data['cases'])}
    for case, variant, context in contexts:
        for attempt in range(config.get('retries', 0) + 1):
            key = f"{case['id']}:{variant}:{attempt}"
            if not ledger.reserve(bound):
                result['status'] = 'budget_stopped'
                break
            request = Request(config['model'], deepcopy(config['parameters']), data['prompt_revision'],
                              deepcopy(context), str(bound), ledger.tariff['currency'])
            try:
                reply = provider.respond(request)
                require(isinstance(reply.text, str) and bool(reply.text.strip()), 'empty response')
                require(number(reply.latency_seconds), 'invalid latency')
                ledger.record(key, bound, reply.usage)
            except Exception as exc:
                # Even malformed usage / post-call validation can hide billable costs.
                ledger.record(key, bound, error=f'{type(exc).__name__}: outcome may be billed')
                if isinstance(exc, TimeoutError) and attempt < config.get('retries', 0):
                    continue
                result['status'] = 'provider_stopped'
                break
            result['responses'].append({'case_id': case['id'], 'variant': variant,
                                        'text': reply.text, 'latency_seconds': reply.latency_seconds,
                                        'attempt': attempt})
            break
        if result['status'] != 'complete':
            break
    result['costs'] = ledger.report({**data.get('workload_units', {}),
                                    'answer': len(result['responses'])})
    result['costs']['attempts'] = ledger.entries
    result['completed_answers'] = len(result['responses'])
    result['planned_answers'] = len(contexts)
    return result
