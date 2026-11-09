"""Human ratings, paired comparisons, ASR semantic errors and explicit denominators."""
import math
from collections import Counter

from .blind import DIMENSIONS
from .data import require


def ratio(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'value': numerator / denominator if denominator else None}


def wer_counts(reference, hypothesis):
    reference, hypothesis = reference.split(), hypothesis.split()
    previous = list(range(len(hypothesis) + 1))
    for i, a in enumerate(reference, 1):
        current = [i]
        for j, b in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1], len(reference)


def asr_metrics(rows):
    included, excluded = [], []
    for row in rows:
        if row.get('exclusion_reason'):
            excluded.append({'id': row['id'], 'reason': row['exclusion_reason']})
        else:
            for field in ('square_errors', 'piece_errors', 'negation_errors'):
                require(type(row[field]) is int and row[field] >= 0, 'invalid ASR count')
            require(type(row['known_semantic_distortion_after_review']) is bool, 'ASR review required')
            included.append(row)
    distances = [wer_counts(r['reference'], r['hypothesis']) for r in included]
    return {'input_count': len(rows), 'excluded': excluded,
            'wer': ratio(sum(d[0] for d in distances), sum(d[1] for d in distances)),
            **{field: ratio(sum(r[field] for r in included), len(included))
               for field in ('square_errors', 'piece_errors', 'negation_errors')},
            'remaining_semantic_distortions': ratio(
                sum(r['known_semantic_distortion_after_review'] for r in included), len(included))}


def score(result, key, annotations, asr=()):
    expected = {(r['case_id'], r['variant']) for r in result['responses']}
    require(len(key) == len(expected) and
            {(v['case_id'], v['variant']) for v in key.values()} == expected, 'blind key mismatch')
    seen, rated, excluded = set(), {}, []
    for rating in annotations['ratings']:
        ident = rating['answer_id']
        require(ident in key and ident not in seen, 'unknown or duplicate rating')
        seen.add(ident)
        if rating.get('exclusion_reason'):
            excluded.append({'answer_id': ident, 'reason': rating['exclusion_reason']})
            continue
        require(all(type(rating[d]) is int and 1 <= rating[d] <= 5 for d in DIMENSIONS),
                'all human scores must be integers 1..5')
        require(type(rating['critical_error']) is bool, 'critical error label required')
        rated[ident] = rating
    missing = sorted(set(key) - seen)
    quality = {}
    for variant in ('A', 'B', 'C'):
        selected = [r for ident, r in rated.items() if key[ident]['variant'] == variant]
        quality[variant] = {d: {**ratio(sum(r[d] for r in selected), len(selected)),
                                'histogram': dict(sorted(Counter(r[d] for r in selected).items()))}
                            for d in DIMENSIONS}
        quality[variant]['critical_errors'] = ratio(sum(r['critical_error'] for r in selected), len(selected))
    wins, losses, ties, comparisons = 0, 0, 0, set()
    for comparison in annotations.get('comparisons', []):
        pair = comparison['answer_ids']
        require(len(pair) == 2 and len(set(pair)) == 2 and all(i in rated for i in pair),
                'comparison requires two rated answers')
        by_variant = {key[i]['variant']: i for i in pair}
        require(set(by_variant) == {'A', 'C'}, 'comparison must pair A/C')
        a, c = by_variant['A'], by_variant['C']
        require(key[a]['case_id'] == key[c]['case_id'], 'comparison must pair same case')
        require(key[a]['case_id'] not in comparisons, 'duplicate comparison')
        comparisons.add(key[a]['case_id'])
        require(comparison['winner'] in (a, c, 'tie'), 'invalid winner')
        wins += comparison['winner'] == c
        losses += comparison['winner'] == a
        ties += comparison['winner'] == 'tie'
    latency = sorted(r['latency_seconds'] for r in result['responses'])
    non_ties = wins + losses
    h2 = 'inconclusive'
    # Synthetic fixtures and incomplete runs never establish a product gate.
    if not result['synthetic'] and result['status'] == 'complete' and not missing and not excluded and non_ties >= 30:
        a_acc = quality['A']['accuracy']['value']
        c_acc = quality['C']['accuracy']['value']
        h2 = 'pass' if wins / non_ties >= .6 and c_acc >= a_acc else 'fail'
    return {'dataset_version': result['dataset_version'],
            'protocol_version': result['protocol_version'], 'prompt_revision': result['prompt_revision'],
            'config': result['config'], 'input_sha256': result['input_sha256'],
            'run_status': result['status'],
            'synthetic': result['synthetic'], 'input_holdout_count': result['input_holdout_count'],
            'input_exclusions': result['excluded'], 'rating_exclusions': excluded,
            'unrated_answer_ids': missing, 'quality': quality,
            'profile_preference': {**ratio(wins, non_ties), 'losses': losses, 'ties': ties},
            'latency_seconds': {'values': latency, 'p95': latency[math.ceil(.95 * len(latency)) - 1] if latency else None},
            'asr': asr_metrics(asr), 'costs': result['costs'], 'H2': h2,
            'error_examples': [r['error_example'] for r in rated.values() if r.get('error_example')],
            'next_hypothesis': 'Review errors, retrieval and principle applicability before expanding corpus.'}
