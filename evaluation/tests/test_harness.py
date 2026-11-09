from copy import deepcopy
import json
import subprocess
import sys

import chess
import pytest

from evaluation.adapters import RecordedEngine, RecordedText
from evaluation.blind import blind, DIMENSIONS
from evaluation.costs import Ledger, UNITS
from evaluation.data import Invalid, replay, validate
from evaluation.metrics import asr_metrics, score
from evaluation.runner import run


def execute(inputs, provider=None):
    return run(inputs['manifest'], inputs['config'], provider or RecordedText(inputs['responses']),
               RecordedEngine(inputs['engine']))


@pytest.mark.parametrize('mutation', ['group', 'profile', 'unverified', 'duplicate', 'illegal'])
def test_rejects_invalid_manifest(inputs, mutation):
    data = inputs['manifest']
    if mutation == 'group':
        data['cases'][1]['split_group'] = data['cases'][0]['split_group']
    elif mutation == 'profile':
        data['profiles']['synthetic-author']['evidence_ids'] = ['synthetic-holdout']
    elif mutation == 'unverified':
        data['cases'][0]['verified'] = False
    elif mutation == 'duplicate':
        data['cases'][1]['id'] = data['cases'][0]['id']
    else:
        data['cases'][0]['position']['prefix_uci'] = ['e2e5']
    with pytest.raises(Invalid):
        validate(data)


def test_replay_preserves_turn_and_history(inputs):
    board = chess.Board(replay(inputs['manifest']['cases'][1]['position']))
    assert board.turn == chess.WHITE
    assert board.fullmove_number == 2
    assert board.piece_at(chess.E4) == chess.Piece(chess.PAWN, chess.WHITE)


def test_no_holdout_labels_or_continuation_reach_provider(inputs):
    requests = []
    class Spy(RecordedText):
        def respond(self, request):
            requests.append(deepcopy(request))
            request.context['engine']['lines'].append(['h2h4'])
            return super().respond(request)
    data = inputs['manifest']
    data['cases'][1]['labels'] = {'explanation': 'SECRET_EXPLANATION', 'continuation': 'SECRET_MOVE'}
    result = execute(inputs, Spy(inputs['responses']))
    serialized = json.dumps([r.context for r in requests])
    assert 'SECRET' not in serialized
    assert 'synthetic-author' not in serialized
    assert len(requests) == 3
    assert len({r.model for r in requests}) == 1
    assert all(r.parameters == inputs['config']['parameters'] for r in requests)
    assert all(r.context['engine']['budget'] == inputs['config']['engine_budget'] for r in requests)
    assert all(len(r.context['engine']['lines']) == 1 for r in requests)  # no mutations leaked to subsequent requests
    assert 'episodes' not in requests[0].context
    assert 'profile' not in requests[1].context
    assert requests[2].context['profile']
    assert result['completed_answers'] == 3


def test_deterministic_synthetic_run(inputs):
    assert execute(inputs) == execute(inputs)
    assert execute(inputs)['synthetic'] is True


def test_blind_packet_contains_no_author_or_configuration(inputs):
    result = execute(inputs)
    result['responses'][0]['text'] += ' SYNTHETIC-AUTHOR config A configuration: C'
    packet, key, ratings = blind(result, inputs['manifest'], 19)
    assert (packet, key, ratings) == blind(result, inputs['manifest'], 19)
    serialized = json.dumps(packet).lower()
    for secret in ('example coach', 'synthetic-author', 'config a', 'configuration: c', 'variant', 'case_id'):
        assert secret not in serialized
    assert all(set(row) == {'answer_id', 'position_id', 'text'} for row in packet['answers'])
    assert {r['variant'] for r in key.values()} == {'A', 'B', 'C'}
    assert any(key != blind(result, inputs['manifest'], seed)[1] for seed in range(20, 30))


def test_stops_before_call_that_could_exceed_limit(inputs):
    inputs['config']['spend_limit'] = '1.01'
    result = execute(inputs)
    assert result['status'] == 'budget_stopped'
    assert result['completed_answers'] == 1
    assert len(result['costs']['attempts']) == 1
    assert result['costs']['known_cost'] == '0.018'


def test_timeout_retains_uncertain_cost_and_stops_retry_at_limit(inputs):
    inputs['config'].update(retries=3, spend_limit='1')
    result = execute(inputs, RecordedText([{'timeout': True}]))
    assert result['status'] == 'budget_stopped'
    assert result['costs']['uncertain_cost_upper_bound'] == '1'
    assert result['costs']['known_cost'] == '0'
    assert len(result['costs']['attempts']) == 1


def test_retry_charges_attempts_and_preserves_success(inputs):
    inputs['config'].update(retries=1, spend_limit='4')
    result = execute(inputs, RecordedText([{'timeout':True}, *inputs['responses']]))
    assert result['status'] == 'complete'
    assert result['responses'][0]['attempt'] == 1
    assert len(result['costs']['attempts']) == 4
    assert result['costs']['uncertain_cost_upper_bound'] == '1'


@pytest.mark.parametrize('failure', ['usage', 'nan', 'empty'])
def test_post_call_failure_is_uncertain_and_stops(inputs, failure):
    reply = inputs['responses'][0]
    if failure == 'usage': reply['usage'].pop('frames')
    if failure == 'nan': reply['latency_seconds'] = float('nan')
    if failure == 'empty': reply['text'] = ''
    result = execute(inputs)
    assert result['status'] == 'provider_stopped'
    assert result['costs']['uncertain_cost_upper_bound'] == '1'
    assert result['completed_answers'] == 0


@pytest.mark.parametrize('tokens,cost,budget_exceeded', [(100000, '100.008', True), (1500, '1.508', False)])
def test_valid_usage_exceeding_bound_retains_actual_cost_and_stops(inputs, tokens, cost, budget_exceeded):
    inputs['responses'][0]['usage']['input_tokens'] = tokens
    inputs['config']['retries'] = 3
    result = execute(inputs)
    costs = result['costs']
    assert result['status'] == 'bound_violated'
    assert result['completed_answers'] == 0
    assert costs['known_cost'] == costs['reserved_or_spent'] == cost
    assert costs['uncertain_cost_upper_bound'] == '0'
    assert costs['usage']['input_tokens'] == str(tokens)
    assert costs['bound_exceeded'] is True
    assert costs['budget_exceeded'] is budget_exceeded
    assert len(costs['attempts']) == 1  # No retry or later variant after a disproved bound.
    entry = costs['attempts'][0]
    assert entry['status'] == 'known'
    assert entry['usage'] == inputs['responses'][0]['usage']
    assert entry['cost'] == cost
    assert entry['reserved_bound'] == '1'
    assert entry['bound_exceeded'] is True
    assert entry['budget_exceeded'] is budget_exceeded
    assert entry['uncertain_upper_bound'] == '0'


def test_live_adapter_requires_approved_budget_before_calls(inputs):
    class Live(RecordedText):
        live = True
        def respond(self, request):
            pytest.fail('must not call unapproved live provider')
    with pytest.raises(Invalid, match='approved budget'):
        execute(inputs, Live([]))


@pytest.mark.parametrize('field,value', [('model','latest'),('retries',4), ('spend_limit','NaN'),
                                        ('per_attempt_upper_bound','0')])
def test_invalid_config_fails_before_provider(inputs, field, value):
    inputs['config'][field] = value
    with pytest.raises(ValueError): execute(inputs)


def test_costs_separate_units_categories_and_zero_denominators(inputs):
    result = execute(inputs)
    costs = result['costs']
    assert costs['tariff']['version'] == 'synthetic-tariff-v1'
    assert costs['by_category'] == {'api':'0.045', 'server':'0.003', 'manual':'0.006'}
    assert costs['unit_costs']['game']['known_cost_per_unit'] is None
    assert costs['unit_costs']['answer']['known_cost_per_unit'] == '0.018'
    assert costs['usage']['input_tokens'] == '30'


def rated_result(inputs):
    result = execute(inputs)
    _, key, annotations = blind(result, inputs['manifest'], 19)
    for row in annotations['ratings']:
        row.update({d: 4 for d in DIMENSIONS}, critical_error=False)
    by_variant = {v['variant']: k for k, v in key.items()}
    annotations['comparisons'] = [{'answer_ids':[by_variant['A'],by_variant['C']], 'winner':by_variant['C']}]
    return result, key, annotations


def test_metrics_show_counts_distribution_exclusions_and_inconclusive(inputs):
    result, key, annotations = rated_result(inputs)
    report = score(result, key, annotations, inputs['asr'])
    assert report['H2'] == 'inconclusive'
    assert report['profile_preference'] == {'numerator':1, 'denominator':1,'value':1, 'losses':0,'ties':0}
    assert report['quality']['A']['usefulness']['histogram'] == {4:1}
    assert report['input_holdout_count'] == 2
    assert report['input_exclusions'][0]['reason']
    assert report['latency_seconds']['p95'] == 3
    assert report['asr']['negation_errors']['numerator'] == 1
    assert report['asr']['wer']['denominator'] == 4
    annotations['comparisons'] = []
    annotations['ratings'][0]['exclusion_reason'] = 'unresolved'
    annotations['ratings'].pop()
    report = score(result, key, annotations)
    assert len(report['rating_exclusions']) == len(report['unrated_answer_ids']) == 1
    assert report['quality']['A']['usefulness']['denominator'] in (0,1)


@pytest.mark.parametrize('failure', ['duplicate', 'unknown', 'score', 'comparison'])
def test_reject_invalid_ratings(inputs, failure):
    result, key, annotations = rated_result(inputs)
    if failure == 'duplicate': annotations['ratings'].append(annotations['ratings'][0])
    if failure == 'unknown': annotations['ratings'][0]['answer_id'] = 'unknown'
    if failure == 'score': annotations['ratings'][0]['accuracy'] = 6
    if failure == 'comparison': annotations['comparisons'] *= 2
    with pytest.raises(Invalid): score(result, key, annotations)


def test_asr_exclusions_and_zero_reference():
    report = asr_metrics([{'id':'bad','exclusion_reason':'no audio'}])
    assert report['wer'] == {'numerator':0,'denominator':0,'value':None}
    assert report['excluded'] == [{'id':'bad','reason':'no audio'}]


def test_cli_offline_flow_and_separate_blind_destinations(tmp_path):
    root = 'evaluation/fixtures/'
    def cli(*args, expected=0):
        completed = subprocess.run([sys.executable, '-m', 'evaluation', *map(str,args)], capture_output=True, text=True)
        assert completed.returncode == expected, completed.stderr
        return completed
    cli('validate', root+'manifest.json')
    output = tmp_path/'result.json'
    cli('run', root+'manifest.json',root+'config.json',root+'responses.json',root+'engine.json',output)
    cli('blind',root+'manifest.json',output,tmp_path/'public',tmp_path/'private','--seed',19)
    cli('blind',root+'manifest.json',output,tmp_path/'unsafe',tmp_path/'unsafe','--seed',19,expected=2)
    ratings = tmp_path/'public'/'ratings.json'
    labels = json.loads(ratings.read_text())
    for row in labels['ratings']:
        row.update({d:4 for d in DIMENSIONS}, critical_error=False)
    ratings.write_text(json.dumps(labels))
    cli('score',output,tmp_path/'private'/'key.json',ratings,tmp_path/'report.json','--asr',root+'asr.json')
    assert json.loads((tmp_path/'report.json').read_text())['H2'] == 'inconclusive'
    assert output.stat().st_mode & 0o777 == 0o600


def test_illegal_recorded_engine_line_fails_preflight(inputs):
    next(iter(inputs['engine'].values()))['lines'] = [['e2e5']]
    with pytest.raises(ValueError):
        execute(inputs, RecordedText([]))


def test_engine_metadata_cannot_smuggle_holdout_answer(inputs):
    record = next(iter(inputs['engine'].values()))
    record['explanation'] = 'HIDDEN_ANSWER'
    facts = RecordedEngine(inputs['engine']).analyze(inputs['manifest']['cases'][1]['position'],
                                                   inputs['config']['engine_budget'])
    assert 'HIDDEN_ANSWER' not in json.dumps(facts)


def test_blind_export_rejects_different_manifest(inputs):
    result = execute(inputs)
    inputs['manifest']['cases'][1]['thought'] = 'different question'
    with pytest.raises(Invalid, match='dataset mismatch'):
        blind(result, inputs['manifest'], 19)


def test_zero_limit_makes_no_calls(inputs):
    inputs['config']['spend_limit'] = '0'
    result = execute(inputs, RecordedText([]))
    assert result['status'] == 'budget_stopped'
    assert result['costs']['attempts'] == []


def test_profile_preflight_prevents_partial_provider_run(inputs):
    inputs['manifest']['profiles'] = {}
    with pytest.raises(Invalid, match='missing verified profile'):
        execute(inputs, RecordedText([]))


def test_blind_positions_include_only_pre_explanation_context(inputs):
    result = execute(inputs)
    packet, _, _ = blind(result, inputs['manifest'], 19)
    assert set(packet['positions'][0]) == {'position_id','fen','thought','context_before'}
    assert 'HIDDEN' not in json.dumps(packet)


def test_asr_word_errors_and_semantics_independent(inputs):
    report = asr_metrics(inputs['asr'])
    assert report['wer'] == {'numerator':3,'denominator':4,'value':0.75}
    for field in ('square_errors', 'piece_errors', 'negation_errors'):
        assert report[field] == {'numerator':1,'denominator':1,'value':1.0}
    assert report['remaining_semantic_distortions']['numerator'] == 0
