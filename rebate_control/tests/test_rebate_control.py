from freezegun import freeze_time

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.rebate_base.tests.common import TIERS_3, RebateCommon


@tagged('post_install', '-at_install', 'rebate')
class TestRebateControl(RebateCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.acc_521 = cls.company_data['default_account_revenue'].copy({'code': '521001', 'name': 'CKTM'})
        cls.acc_3388 = cls.company_data['default_account_payable'].copy({
            'code': '338801', 'name': 'Phải trả khác', 'account_type': 'liability_current', 'reconcile': False})
        cls.company.write({'rebate_sale_account_id': cls.acc_521.id,
                           'rebate_accrual_sale_account_id': cls.acc_3388.id})

    def _agreement_with(self, conditions, **kw):
        return self._create_agreement(condition_ids=[Command.create(c) for c in conditions],
                                      settlement_doc='none', **kw)

    # ---------------- conditions (T29/T30) -----------------
    def test_01_overdue_blocks(self):
        agr = self._agreement_with([{'condition_type': 'overdue', 'max_overdue_days': 30}])
        inv = self._invoice('2026-01-10', [(self.p_drink, 25000, 100)], post=False)
        inv.write({'invoice_payment_term_id': False, 'invoice_date_due': '2026-01-10'})
        inv.action_post()                                            # unpaid, due 10/01 → > 30 days late
        self.assertEqual(str(inv.line_ids.filtered('date_maturity')[:1].date_maturity), '2026-01-10')
        with freeze_time('2026-04-15'):
            st = self._settle(self._period(agr, 'Q1/2026'))
        self.assertTrue(st.blocked)
        self.assertEqual(st.amount, 0)
        self.assertIn('Nợ quá hạn', st.condition_html)

    def test_02_overdue_ok_when_paid(self):
        agr = self._agreement_with([{'condition_type': 'overdue', 'max_overdue_days': 30}])
        inv = self._invoice('2026-01-10', [(self.p_drink, 25000, 100)])
        self.env['account.payment.register'].with_context(active_model='account.move', active_ids=inv.ids)             .create({'payment_date': '2026-02-01'})._create_payments()
        with freeze_time('2026-04-15'):
            st = self._settle(self._period(agr, 'Q1/2026'))
        self.assertFalse(st.blocked)
        self.assertEqual(st.amount, 50_000)

    def test_03_return_rate(self):
        agr = self._agreement_with([{'condition_type': 'return_rate', 'max_return_rate': 20}])
        inv = self._invoice('2026-01-10', [(self.p_drink, 30000, 100)])
        self._invoice('2026-02-10', [(self.p_drink, 7500, 100)], move_type='out_refund', reversed_entry=inv)
        st = self._settle(self._period(agr, 'Q1/2026'))
        self.assertTrue(st.blocked, '25% returns > 20%')

    def test_04_growth_bonus(self):
        self._invoice('2025-02-10', [(self.p_drink, 10000, 100)])   # same quarter last year: 1,000,000
        agr = self._agreement_with([{'condition_type': 'growth', 'growth_rate': 15, 'effect': 'bonus',
                                     'effect_value': 0.5}])
        self._invoice('2026-02-10', [(self.p_drink, 15000, 100)])   # 1,500,000 → +50%
        st = self._settle(self._period(agr, 'Q1/2026'))
        self.assertEqual(st.gross_amount, 15_000)
        self.assertEqual(st.amount, 15_000 + 7_500)
        self.assertEqual(sum(st.detail_ids.mapped('allocated_amount')), 22_500)

    def test_05_mix_reduce(self):
        agr = self._agreement_with([{
            'condition_type': 'mix', 'min_share': 60, 'effect': 'reduce', 'effect_value': 50,
            'mix_product_categ_ids': [Command.set(self.categ_drink.ids)]}])
        self._invoice('2026-01-10', [(self.p_drink, 12500, 100), (self.p_snack, 25000, 50)])  # 50% drinks
        st = self._settle(self._period(agr, 'Q1/2026'))
        self.assertFalse(st.blocked)
        self.assertEqual(st.gross_amount, 50_000)
        self.assertEqual(st.amount, 25_000)

    # ---------------- accrual (T31) -----------------
    def test_10_accrual_gl_and_release(self):
        self.company.rebate_accrual_mode = 'gl'
        agr = self._create_agreement(settlement_doc='voucher', nature='support')
        self._invoice('2026-01-10', [(self.p_drink, 15000, 100)])
        Accrual = self.env['rebate.accrual']
        a1 = Accrual._run(date=self.d('2026-01-31'), agreements=agr)
        self.assertEqual(a1.amount, 15_000)
        self.assertEqual(a1.move_id.state, 'posted')
        self.assertEqual(a1.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_521).debit, 15_000)
        self._invoice('2026-02-10', [(self.p_drink, 10000, 100)])
        a2 = Accrual._run(date=self.d('2026-02-28'), agreements=agr)
        self.assertEqual(a2.amount, 35_000, '50,000 estimate − 15,000 already accrued')
        Accrual._run(date=self.d('2026-02-28'), agreements=agr)
        q1 = self._period(agr, 'Q1/2026')
        self.assertEqual(Accrual._balance(q1), 50_000, 'idempotent re-run')
        st = self._settle(q1)
        st.action_submit()
        st.action_approve()
        st.action_generate_documents()
        self.assertEqual(Accrual._balance(q1), 0, 'released on settlement')
        balance_3388 = sum(self.env['account.move.line'].search([
            ('account_id', '=', self.acc_3388.id), ('parent_state', '=', 'posted')]).mapped('balance'))
        self.assertAlmostEqual(balance_3388, 0)

    def test_11_accrual_year_with_quarters(self):
        self.company.rebate_accrual_mode = 'management'
        agr = self._create_agreement(period_type='year_quarter', settlement_doc='none', rules=[{
            'name': 'Năm', 'tiers': [(0, 0, 1.0)]}])
        self._invoice('2026-02-10', [(self.p_drink, 10000, 100)])
        Accrual = self.env['rebate.accrual']
        Accrual._run(date=self.d('2026-03-31'), agreements=agr)
        year = agr.period_ids.filtered(lambda p: not p.parent_id)
        self.assertEqual(Accrual._balance(year), 10_000)
        q1 = year.child_ids.filtered(lambda p: p.name == 'Q1/2026')
        st = self._settle(q1)
        st.action_submit()
        st.action_approve()
        st.action_generate_documents()
        self.assertEqual(Accrual._balance(year), 0)
        self.assertFalse(Accrual.search([('period_id', '=', year.id)]).move_id, 'management mode: no entry')
