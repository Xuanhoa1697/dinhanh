from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.rebate_base.tests.common import RebateCommon


@tagged('post_install', '-at_install', 'rebate')
class TestRebateSale(RebateCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.acc_521 = cls.company_data['default_account_revenue'].copy({'code': '521001', 'name': 'CKTM'})
        cls.company.rebate_sale_account_id = cls.acc_521

    def _done(self, agreement, period_name='Q1/2026'):
        st = self._settle(self._period(agreement, period_name))
        st.action_submit()
        st.action_approve()
        st.action_generate_documents()
        return st

    def test_01_adjust_invoice_per_tax_and_offset(self):
        agr = self._create_agreement(settlement_doc='adjust_invoice', payment_method='offset')
        i1 = self._invoice('2026-01-10', [(self.p_drink, 10000, 100)])
        i2 = self._invoice('2026-02-10', [(self.p_snack, 16000, 50)])
        i3 = self._invoice('2026-03-10', [(self.p_drink, 7000, 100)])
        st = self._done(agr)
        refund = st.move_ids
        self.assertEqual(len(refund), 1)
        self.assertEqual(refund.move_type, 'out_refund')
        self.assertEqual(refund.state, 'posted')
        self.assertEqual(refund.reversed_entry_id, i3, 'adjusts the last invoice of the period')
        self.assertEqual(refund.amount_untaxed, 50_000)
        self.assertEqual(len(refund.invoice_line_ids), 2, 'one line per tax rate')
        self.assertEqual(refund.amount_tax, 2_000 + 1_400 + 1_280)
        self.assertEqual(refund.invoice_line_ids.account_id, self.acc_521)
        # offset: the refund is reconciled with open invoices
        self.assertEqual(refund.payment_state, 'paid')
        self.assertIn('partial', (i1 | i3).mapped('payment_state'))
        # the rebate refund must not count as a return in the accumulation
        self.assertFalse(agr.line_ids.filtered(lambda ln: ln.move_id == refund))

    def test_02_group_partners_get_own_documents(self):
        agr = self._create_agreement(partners=self.customer | self.customer2, settlement_doc='adjust_invoice',
                                     payment_method='cash')
        self._invoice('2026-01-10', [(self.p_drink, 15000, 100)])
        self._invoice('2026-01-12', [(self.p_drink, 10000, 100)], partner=self.customer2)
        st = self._done(agr)
        self.assertEqual(len(st.move_ids), 2)
        self.assertEqual(st.move_ids.partner_id, self.customer | self.customer2)
        amounts = {m.partner_id: m.amount_untaxed for m in st.move_ids}
        self.assertEqual(amounts[self.customer], 30_000)
        self.assertEqual(amounts[self.customer2], 20_000)

    def test_03_next_invoice_carryforward(self):
        agr = self._create_agreement(settlement_doc='next_invoice', payment_method='next_invoice')
        self._invoice('2026-01-10', [(self.p_drink, 25000, 100)])
        st = self._done(agr)
        self.assertFalse(st.move_ids)
        carry = st.carryforward_ids
        self.assertEqual(carry.amount, 50_000)
        # next invoice of 30,000 only absorbs 30,000
        nxt = self._invoice('2026-04-10', [(self.p_drink, 300, 100)], post=False)
        self.assertEqual(nxt.rebate_carry_available, 50_000)
        nxt.action_rebate_apply_carryforward()
        self.assertEqual(nxt.amount_untaxed, 0)
        nxt.action_post()
        self.assertEqual(carry.amount_residual, 20_000)
        # the deduction lines are not counted as sales of Q2
        self.assertEqual(sum(self._period(agr, 'Q2/2026').line_ids.mapped('amount')), 30_000)
        # manual over-deduction is blocked
        nxt2 = self._invoice('2026-04-20', [(self.p_drink, 100, 100)], post=False)
        nxt2.action_rebate_apply_carryforward()
        nxt2.invoice_line_ids.filtered('rebate_carry_id').price_unit = -15_000
        with self.assertRaises(UserError):
            nxt2.action_post()

    def test_04_recover_issues_increase_invoice(self):
        agr = self._create_agreement(settlement_doc='adjust_invoice', payment_method='cash',
                                     negative_true_up='recover')
        inv = self._invoice('2026-01-10', [(self.p_drink, 25000, 100)])
        q1 = self._period(agr, 'Q1/2026')
        self._done(agr)
        self._invoice('2026-04-20', [(self.p_drink, 6000, 100)], move_type='out_refund', reversed_entry=inv)
        q1.action_recalc()
        adj = q1.settlement_ids.filtered('is_adjustment')
        adj.action_submit()
        adj.action_approve()
        adj.action_generate_documents()
        self.assertEqual(adj.move_ids.move_type, 'out_invoice')
        self.assertEqual(adj.move_ids.amount_untaxed, 31_000)
