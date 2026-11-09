"""Separate public review packet and private key. Export into different directories."""
import hashlib
import json
import random
import re

from .data import require, replay

DIMENSIONS = ('accuracy', 'usefulness', 'applicability', 'explanation_character')


def blind(result, dataset, seed):
    require(result['input_sha256'] == hashlib.sha256(json.dumps(dataset, sort_keys=True).encode()).hexdigest(),
            'dataset mismatch')
    rows = list(result['responses'])
    rng = random.Random(seed)
    rng.shuffle(rows)
    aliases = [name for author, names in dataset['authors'].items() for name in [author, *names]]
    require(len({(r['case_id'], r['variant']) for r in rows}) == len(rows), 'duplicate answer')
    case_ids = list(dict.fromkeys(r['case_id'] for r in rows))
    rng.shuffle(case_ids)
    case_keys = {case_id: f'position-{i + 1:04d}' for i, case_id in enumerate(case_ids)}
    def redact(text):
        for alias in sorted(aliases, key=len, reverse=True):
            text = re.sub(re.escape(alias), '[author]', text, flags=re.IGNORECASE)
        return re.sub(r'\b(?:configuration|config|variant|конфигурация)\s*[:=]?\s*[ABC]\b',
                      '[configuration]', text, flags=re.IGNORECASE)
    public, private = [], {}
    for index, row in enumerate(rows):
        answer_id = f'answer-{index + 1:04d}'
        text = redact(row['text'])
        public.append({'answer_id': answer_id, 'position_id': case_keys[row['case_id']], 'text': text})
        private[answer_id] = {'case_id': row['case_id'], 'variant': row['variant']}
    packet = {'synthetic': result['synthetic'], 'answers': public,
              'positions': [{'position_id': case_keys[c['id']], 'fen': replay(c['position']),
                             'thought': redact(c['thought']), 'context_before': redact(c['context_before'])}
                            for c in dataset['cases'] if c['id'] in case_keys]}
    ratings = {'ratings': [{'answer_id': r['answer_id'], 'exclusion_reason': '',
                           **{d: None for d in DIMENSIONS}, 'critical_error': None,
                           'error_example': ''} for r in public],
               'comparisons': []}
    return packet, private, ratings
