"""Decimal unit accounting with conservative reservation before external calls."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from .data import require

UNITS = ('input_tokens', 'output_tokens', 'cache_tokens', 'audio_minutes', 'frames',
         'retry_requests', 'cpu_seconds', 'manual_minutes')


def money(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('invalid monetary value') from exc
    require(result.is_finite() and result >= 0, 'amount must be finite and nonnegative')
    return result


class Ledger:
    def __init__(self, tariff, limit):
        require(bool(tariff.get('version')) and bool(tariff.get('currency')), 'versioned tariff required')
        require(set(tariff['rates']) == set(UNITS), 'all unit rates required')
        require(set(tariff['categories']) == set(UNITS), 'all cost categories required')
        require(all(c in ('api', 'server', 'manual') for c in tariff['categories'].values()),
                'invalid cost category')
        for rate in tariff['rates'].values():
            money(rate)
        self.tariff = tariff
        self.limit = money(limit)
        self.entries = []
        self.committed = Decimal(0)

    def price(self, usage):
        require(set(usage) == set(UNITS), 'all usage units required (explicit zero allowed)')
        return sum((money(usage[u]) * money(self.tariff['rates'][u]) for u in UNITS), Decimal(0))

    def reserve(self, upper_bound):
        bound = money(upper_bound)
        require(bound > 0, 'positive per-call upper bound required')
        if self.committed + bound > self.limit:
            return False
        self.committed += bound
        return True

    def record(self, key, bound, usage=None, error=None):
        bound = money(bound)
        if error is not None:
            self.entries.append({'key': key, 'status': 'uncertain', 'reason': error,
                                 'uncertain_upper_bound': str(bound)})
            return
        cost = self.price(usage)
        self.committed += cost - bound
        # A disproved reservation cannot bound known expenditure. Reconcile the
        # actual cost first and return the violation so the runner stops safely.
        entry = {'key': key, 'status': 'known', 'usage': deepcopy(usage),
                 'cost': str(cost), 'uncertain_upper_bound': '0',
                 'reserved_bound': str(bound), 'bound_exceeded': cost > bound,
                 'budget_exceeded': self.committed > self.limit}
        self.entries.append(entry)
        return entry

    def report(self, denominators):
        known = sum((money(e.get('cost', 0)) for e in self.entries), Decimal(0))
        uncertain = sum((money(e['uncertain_upper_bound']) for e in self.entries), Decimal(0))
        totals = {u: str(sum((money(e['usage'][u]) for e in self.entries
                             if e['status'] == 'known'), Decimal(0))) for u in UNITS}
        by_category = {c: str(sum((money(totals[u]) * money(self.tariff['rates'][u])
                                  for u in UNITS if self.tariff['categories'][u] == c), Decimal(0)))
                       for c in ('api', 'server', 'manual')}
        return {'tariff': self.tariff, 'known_cost': str(known),
                'bound_exceeded': any(e.get('bound_exceeded', False) for e in self.entries),
                'budget_exceeded': self.committed > self.limit,
                'uncertain_cost_upper_bound': str(uncertain), 'reserved_or_spent': str(self.committed),
                'limit': str(self.limit), 'usage': totals, 'by_category': by_category,
                'unit_costs': {unit: {'denominator': n, 'known_cost_per_unit':
                                     str(known / money(n)) if money(n) > 0 else None}
                               for unit, n in denominators.items()}}
