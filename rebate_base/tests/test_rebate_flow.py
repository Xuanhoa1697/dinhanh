from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tests import tagged

from .common import TIERS_3, RebateCommon


@tagged('post_install', '-at_install', 'rebate')
class TestRebateFlow(RebateCommon):

    # ---------------- M1: agreement -----------------
    def test_01_periods_and_approval(self):
        agr = self._create_agreement(period_type='quarter')
        self.assertEqual(agr.state, 'active')
        self.assertEqual(agr.period_ids.mapped('name'), ['Q1/2026', 'Q2/2026', 'Q3/2026', 'Q4/2026'])
        self.assertTrue(all(agr.rule_ids.mapped('approved')))
        yq = self._create_agreement(period_type='year_quarter', approve=False)
        yq.action_submit()
        yq.action_approve()
        year = yq.period_ids.filtered(lambda p: not p.parent_id)
        self.assertEqual(len(year), 1)
        self.assertEqual(len(year.child_ids), 4)

    def test_02_overlapping_tiers_rejected(self):
        with self.assertRaises(ValidationError):
            self._create_agreement(rules=[{'name': 'x', 'tiers': [(0, 100, 1), (50, 0, 2)]}], approve=False)

    def test_03_locked_after_approval(self):
        agr = self._create_agreement()
        with self.assertRaises(UserError):
            agr.date_to = '2027-12-31'
        with self.assertRaises(UserError):
            agr.rule_ids.tier_ids[0].value = 5

    def test_04_template_defaults(self):
        tmpl = self.env['rebate.template'].create({
            'name': 'NCC quý', 'direction': 'purchase', 'period_type': 'month', 'payment_method': 'cash'})
        agr = self.env['rebate.agreement'].create({
            'title': 'Từ mẫu', 'template_id': tmpl.id, 'date_from': '2026-01-01', 'date_to': '2026-06-30',
            'partner_ids': [Command.set(self.vendor.ids)]})
        self.assertEqual((agr.direction, agr.period_type, agr.payment_method), ('purchase', 'month', 'cash'))

    # ---------------- M2: accumulation -----------------
    def test_10_lines_created_and_removed(self):
        agr = self._create_agreement()
        inv = self._invoice('2026-02-10', [(self.p_drink, 10, 100)])
        self.assertEqual(len(agr.line_ids), 1)
        self.assertEqual(agr.line_ids.amount, 1000)
        self.assertEqual(agr.line_ids.period_id.name, 'Q1/2026')
        inv.button_draft()
        self.assertFalse(agr.line_ids)
        inv.action_post()
        inv.action_post() if inv.state == 'draft' else None
        self.assertEqual(len(agr.line_ids), 1, 'post again → exactly one line (idempotent)')

    def test_11_other_partner_and_scope(self):
        agr = self._create_agreement(rules=[{
            'name': 'Chỉ nước', 'product_scope': 'category', 'product_categ_ids': [Command.set(self.categ_drink.ids)],
            'tiers': TIERS_3}])
        self._invoice('2026-02-10', [(self.p_drink, 1, 100), (self.p_snack, 1, 50)])
        self._invoice('2026-02-10', [(self.p_drink, 1, 100)], partner=self.customer2)
        self.assertEqual(agr.line_ids.product_id, self.p_drink)
        self.assertEqual(len(agr.line_ids), 1)

    def test_12_refund_goes_to_origin_period(self):
        agr = self._create_agreement()
        inv = self._invoice('2026-03-20', [(self.p_drink, 10, 100)])
        self._invoice('2026-04-05', [(self.p_drink, 2, 100)], move_type='out_refund', reversed_entry=inv)
        q1 = self._period(agr, 'Q1/2026')
        self.assertEqual(sum(q1.line_ids.mapped('amount')), 800)
        refund_line = agr.line_ids.filtered('is_refund')
        self.assertEqual(refund_line.target_move_id, inv)

    def test_13_rebuild_catches_old_invoices(self):
        inv = self._invoice('2026-01-15', [(self.p_drink, 5, 100)])
        agr = self._create_agreement()  # approved after the invoice
        self.assertEqual(agr.line_ids.move_id, inv)
        agr.line_ids.unlink()
        agr.action_rebuild_lines()
        self.assertEqual(len(agr.line_ids), 1)

    def test_14_uom_and_qty_basis(self):
        agr = self._create_agreement(rules=[{
            'name': 'Theo SL', 'basis': 'qty', 'value_type': 'per_unit', 'tiers': [(10, 0, 3)]}])
        self._invoice('2026-01-15', [(self.p_drink, 12, 100)])
        res = self._settle(self._period(agr, 'Q1/2026'))
        self.assertEqual(res.amount, 36)

    def test_15_exclusive_stacking(self):
        high = self._create_agreement(priority=1, stacking='exclusive')
        low = self._create_agreement(priority=5)
        self._invoice('2026-01-15', [(self.p_drink, 1, 100)])
        self.assertEqual(len(high.line_ids), 1)
        self.assertFalse(low.line_ids)

    def test_16_cumulative_stacking(self):
        a1 = self._create_agreement(priority=1)
        a2 = self._create_agreement(priority=5)
        self._invoice('2026-01-15', [(self.p_drink, 1, 100)])
        self.assertEqual(len(a1.line_ids), 1)
        self.assertEqual(len(a2.line_ids), 1)

    # ---------------- M3/M4: compute & settlement -----------------
    def test_20_retro_and_allocation_by_tax(self):
        agr = self._create_agreement()
        i1 = self._invoice('2026-01-10', [(self.p_drink, 10000, 100)])      # 1,000,000 @10%
        i2 = self._invoice('2026-02-10', [(self.p_snack, 16000, 50)])       # 800,000 @8%
        i3 = self._invoice('2026-03-10', [(self.p_drink, 7000, 100)])       # 700,000 @10%
        st = self._settle(self._period(agr, 'Q1/2026'))
        self.assertEqual(st.base_amount, 2_500_000)
        self.assertEqual(st.amount, 50_000)
        self.assertEqual(st.amount_to_settle, 50_000)
        by_move = {d.target_move_id: d for d in st.detail_ids}
        self.assertAlmostEqual(by_move[i1].allocated_amount, 20_000)
        self.assertAlmostEqual(by_move[i2].allocated_amount, 16_000)
        self.assertAlmostEqual(by_move[i3].allocated_amount, 14_000)
        self.assertAlmostEqual(by_move[i2].allocated_tax, 1_280)
        self.assertAlmostEqual(st.tax_amount, 2_000 + 1_280 + 1_400)
        rows = st._statement_rows()
        self.assertEqual(len(rows), 3)

    def test_21_progressive(self):
        agr = self._create_agreement(rules=[{'name': 'LT', 'tier_mode': 'progressive', 'tiers': TIERS_3}])
        self._invoice('2026-01-10', [(self.p_drink, 25000, 100)])
        st = self._settle(self._period(agr, 'Q1/2026'))
        self.assertEqual(st.amount, 20_000)

    def test_22_settlement_idempotent_and_unique(self):
        agr = self._create_agreement()
        self._invoice('2026-01-10', [(self.p_drink, 25000, 100)])
        q1 = self._period(agr, 'Q1/2026')
        q1.action_compute_settlement()
        q1.action_compute_settlement()
        regular = q1.settlement_ids.filtered(lambda s: not s.is_adjustment and s.state != 'cancel')
        self.assertEqual(len(regular), 1)
        self.assertEqual(regular.amount, 50_000)

    def test_23_full_flow_voucher_and_post_close_return(self):
        agr = self._create_agreement(settlement_doc='voucher', nature='support')
        inv = self._invoice('2026-01-10', [(self.p_drink, 25000, 100)])
        q1 = self._period(agr, 'Q1/2026')
        st = self._settle(q1)
        st.action_submit()
        st.action_approve()
        st.action_generate_documents()
        self.assertEqual(st.state, 'done')
        self.assertEqual(q1.state, 'settled')
        self.assertEqual(len(st.move_ids), 1)
        self.assertEqual(st.move_ids.state, 'posted')
        # return after close: 2,500,000 -> 1,900,000 => 1% => 19,000 ; diff -31,000 recovered? default ignore
        self._invoice('2026-04-20', [(self.p_drink, 6000, 100)], move_type='out_refund', reversed_entry=inv)
        self.assertTrue(q1.needs_recalc)
        q1.action_recalc()
        adj = q1.settlement_ids.filtered('is_adjustment')
        self.assertEqual(adj.amount, 19_000)
        self.assertEqual(adj.prior_paid, 50_000)
        self.assertEqual(adj.amount_to_settle, 0, 'negative true-up ignored by default')

    def test_24_negative_recover(self):
        agr = self._create_agreement(negative_true_up='recover', settlement_doc='none')
        inv = self._invoice('2026-01-10', [(self.p_drink, 25000, 100)])
        q1 = self._period(agr, 'Q1/2026')
        st = self._settle(q1)
        st.action_submit()
        st.action_approve()
        st.action_generate_documents()
        self._invoice('2026-04-20', [(self.p_drink, 6000, 100)], move_type='out_refund', reversed_entry=inv)
        q1.action_recalc()
        adj = q1.settlement_ids.filtered('is_adjustment')
        self.assertEqual(adj.amount_to_settle, -31_000)

    def test_25_year_with_quarters_true_up(self):
        """S14 – quarterly provisional payments, yearly true-up."""
        agr = self._create_agreement(
            period_type='year_quarter', settlement_doc='none',
            rules=[{'name': 'Năm', 'tiers': [(1_000_000, 2_000_000, 1.0), (2_000_000, 0, 2.0)]}])
        for date, amount in [('2026-02-01', 400_000), ('2026-05-01', 600_000),
                             ('2026-08-01', 700_000), ('2026-11-01', 800_000)]:
            self._invoice(date, [(self.p_drink, amount / 100, 100)])
        year = agr.period_ids.filtered(lambda p: not p.parent_id)
        # quarters: paid with the same yearly tiers on the quarter base -> 0 each (below 1,000,000)
        for q in year.child_ids:
            st = self._settle(q)
            st.action_submit()
            st.action_approve()
            st.action_generate_documents()
        st = self._settle(year)
        self.assertEqual(st.amount, 50_000)
        self.assertEqual(st.prior_paid, 0)
        self.assertEqual(st.amount_to_settle, 50_000)

    def test_26_version_segment(self):
        """S13 – change rate mid-period, computed by segment."""
        agr = self._create_agreement(period_type='year', rules=[{
            'name': 'DS', 'tiers': [(1_000_000, 2_000_000, 1.0), (2_000_000, 0, 2.0)]}])
        self._invoice('2026-03-01', [(self.p_drink, 10000, 100)])     # 1,000,000 before change
        wiz = self.env['rebate.version.wizard'].create({'agreement_id': agr.id, 'date_start': '2026-07-01'})
        wiz.action_confirm()
        self.assertEqual(agr.state, 'revision')
        agr.pending_rule_ids.tier_ids.filtered(lambda t: t.value == 2.0).value = 2.5
        agr.action_submit()
        agr.action_approve()
        self.assertEqual(agr.version, 2)
        self._invoice('2026-08-01', [(self.p_drink, 15000, 100)])     # 1,500,000 after change
        st = self._settle(self._period(agr, '2026'))
        self.assertEqual(st.amount, 57_500)
        self.assertTrue(st.result_ids.segmented)

    def test_27_version_last(self):
        agr = self._create_agreement(period_type='year', mid_period_change='last', rules=[{
            'name': 'DS', 'tiers': [(1_000_000, 2_000_000, 1.0), (2_000_000, 0, 2.0)]}])
        self._invoice('2026-03-01', [(self.p_drink, 10000, 100)])
        self.env['rebate.version.wizard'].create({'agreement_id': agr.id, 'date_start': '2026-07-01'}).action_confirm()
        agr.pending_rule_ids.tier_ids.filtered(lambda t: t.value == 2.0).value = 2.5
        agr.action_submit()
        agr.action_approve()
        self._invoice('2026-08-01', [(self.p_drink, 15000, 100)])
        st = self._settle(self._period(agr, '2026'))
        self.assertEqual(st.amount, 62_500)

    def test_28_approval_limit_and_segregation(self):
        maker = self.env['res.users'].create({
            'name': 'Maker', 'login': 'rebate_maker',
            'group_ids': [Command.set([self.env.ref('rebate_base.group_rebate_manager').id,
                                       self.env.ref('account.group_account_invoice').id])]})
        checker = self.env['res.users'].create({
            'name': 'Checker', 'login': 'rebate_checker',
            'group_ids': [Command.set([self.env.ref('rebate_base.group_rebate_manager').id])]})
        agr = self._create_agreement(settlement_doc='none')
        self.company.write({'rebate_segregation': True, 'rebate_approval_limit': 10_000})
        self._invoice('2026-01-10', [(self.p_drink, 25000, 100)])
        q1 = self._period(agr, 'Q1/2026')
        q1.with_user(maker).action_compute_settlement()
        st = q1.settlement_ids
        st.with_user(maker).action_submit()
        with self.assertRaises(UserError):
            st.with_user(maker).action_approve()     # segregation
        with self.assertRaises(UserError):
            st.with_user(checker).action_approve()   # 50,000 > limit 10,000
        st.action_approve()                           # superuser / admin
        self.assertEqual(st.state, 'approved')

    def test_29_reports_render(self):
        agr = self._create_agreement()
        self._invoice('2026-01-10', [(self.p_drink, 25000, 100)])
        st = self._settle(self._period(agr, 'Q1/2026'))
        html = self.env['ir.actions.report']._render_qweb_html('rebate_base.report_rebate_statement', st.ids)[0]
        self.assertIn(b'50', html)
        self.env['ir.actions.report']._render_qweb_html('rebate_base.report_rebate_confirmation', st.ids)
        action = st.action_export_xlsx()
        self.assertEqual(action['type'], 'ir.actions.act_url')

    def test_30_progress(self):
        agr = self._create_agreement()
        self._invoice('2026-01-10', [(self.p_drink, 15000, 100)])
        q1 = self._period(agr, 'Q1/2026')
        self.assertEqual(q1.progress_measure, 1_500_000)
        self.assertEqual(q1.progress_gap, 500_000)
        self.assertEqual(q1.progress_amount, 15_000)
