"""T02/T14/T15 – the golden scenarios run against the pure engine.

Runs inside Odoo (``--test-tags /rebate_base``) and also standalone:
``python -m unittest discover -s rebate_base/tests -p test_engine.py``.
"""
import os
import sys
import unittest

try:
    from odoo.tests import BaseCase as _Base, tagged
    from odoo.addons.rebate_base.tools import engine
    from odoo.addons.rebate_base.tools.scenarios import SCENARIOS
except ImportError:  # standalone run, no Odoo
    _Base = unittest.TestCase

    def tagged(*_tags):
        return lambda cls: cls
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
    import engine  # noqa: E402
    from scenarios import SCENARIOS  # noqa: E402


def _tiers(raw):
    return [engine.Tier(f, t, v) for f, t, v in raw]


def run_scenario(sc):
    kind = sc['kind']
    if kind == 'tier':
        res = engine.compute_tier_amount(
            sc['measure'], sc['amount'], sc['qty'], _tiers(sc['tiers']),
            sc['tier_mode'], sc['value_type'], sc.get('min_threshold', 0), sc.get('cap', 0))
        return round(res.amount)
    if kind == 'allocate':
        alloc = engine.allocate(sc['total'], sc['weights'], sc['digits'])
        taxes = [round(a * r / 100) for a, r in zip(alloc, sc['tax_rates'])]
        return alloc, taxes
    if kind == 'inventory':
        return engine.split_inventory(sc['total'], sc['qty_in'], sc['qty_remaining'], sc['qty_consumed'], 0)
    if kind == 'segment':
        total, _details = engine.segment_amount(
            sc['segments'], sc['total_measure'],
            {k: _tiers(v) for k, v in sc['tiers_by_segment'].items()},
            sc['tier_mode'], sc['value_type'])
        return round(total)
    if kind == 'trueup':
        paid = sum(round(engine.compute_tier_amount(q, q, 0, _tiers(sc['quarter_tiers'])).amount)
                   for q in sc['quarters'])
        year = sum(sc['quarters'])
        year_amount = round(engine.compute_tier_amount(year, year, 0, _tiers(sc['year_tiers'])).amount)
        return year_amount - paid
    raise ValueError(kind)


@tagged('post_install', '-at_install', 'rebate')
class TestEngineScenarios(_Base):

    def test_golden_scenarios(self):
        for sc in SCENARIOS:
            with self.subTest(sc['code']):
                got = run_scenario(sc)
                if sc['kind'] == 'allocate':
                    self.assertEqual(got[0], sc['expected'])
                    self.assertEqual(got[1], sc['expected_tax'])
                else:
                    self.assertEqual(got, sc['expected'], f"{sc['code']} {sc['name']}")

    def test_allocation_sums_exactly(self):
        weights = [123.45, 678.9, 0.01, 999.99, -50]
        alloc = engine.allocate(1_000_003, weights, 0)
        self.assertEqual(sum(alloc), 1_000_003)

    def test_check_tiers_overlap(self):
        errors = engine.check_tiers(_tiers([(0, 100, 1), (50, 0, 2)]))
        self.assertTrue(errors)
        self.assertFalse(engine.check_tiers(_tiers([(0, 100, 1), (100, 0, 2)])))

    def test_next_tier_gap(self):
        res = engine.compute_tier_amount(1_500_000_000, 1_500_000_000, 0, _tiers([
            (1_000_000_000, 2_000_000_000, 1.0), (2_000_000_000, 0, 2.0)]))
        self.assertEqual(res.next_tier_gap, 500_000_000)
        self.assertEqual(res.tier_index, 0)

    def test_progressive_fixed_amounts_add_up(self):
        res = engine.compute_tier_amount(3_000, 0, 0, _tiers([(1_000, 2_000, 10), (2_000, 0, 20)]),
                                         'progressive', 'amount')
        self.assertEqual(res.amount, 30)


if __name__ == '__main__':
    unittest.main()
