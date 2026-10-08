from freezegun import freeze_time

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.rebate_base.tests.common import RebateCommon


@tagged('post_install', '-at_install', 'rebate')
class TestRebateReport(RebateCommon):

    def test_01_margin_after_rebate(self):
        self.p_drink.standard_price = 60
        agr = self._create_agreement(settlement_doc='none')
        self._invoice('2026-01-10', [(self.p_drink, 25000, 100)])
        line = agr.line_ids
        self.assertEqual(line.cost_amount, 1_500_000)
        st = self._settle(self._period(agr, 'Q1/2026'))
        st.action_submit()
        st.action_approve()
        st.action_generate_documents()
        report = self.env['rebate.margin.report'].search([('agreement_id', '=', agr.id)])
        self.assertEqual(report.amount, 2_500_000)
        self.assertEqual(report.rebate_amount, 50_000)
        self.assertEqual(report.margin, 2_500_000 - 1_500_000 - 50_000)

    def test_02_simulation(self):
        agr = self._create_agreement()
        self._invoice('2026-01-10', [(self.p_drink, 15000, 100)])
        wiz = self.env['rebate.simulation'].create({
            'period_id': self._period(agr, 'Q1/2026').id,
            'rule_id': agr.rule_ids.id,
            'extra_amount': 500_000,
        })
        self.assertEqual(wiz.current_amount, 15_000)
        self.assertEqual(wiz.new_amount, 40_000)
        self.assertEqual(wiz.delta_amount, 25_000)

    @freeze_time('2026-03-20')
    def test_03_dashboard(self):
        agr = self._create_agreement()
        self._invoice('2026-01-10', [(self.p_drink, 19000, 100)])    # 1.9M, 0.1M from the 2M tier (5%)
        dash = self.env['rebate.dashboard'].create({'near_ratio': 10})
        self.assertGreaterEqual(dash.count_near, 1)
        self.assertIn(agr.display_name, dash.near_html)
        self.assertEqual(dash.action_open_due()['res_model'], 'rebate.period')

    def test_04_dynamic_partner_group_by_tag(self):
        """T34 – every customer with the tag belongs to the agreement, each gets its own allocation."""
        tag = self.env['res.partner.category'].create({'name': 'Chuỗi siêu thị'})
        (self.customer | self.customer2).category_id = [Command.set(tag.ids)]
        agr = self._create_agreement(partners=self.env['res.partner'], partner_category_ids=[Command.set(tag.ids)])
        self._invoice('2026-01-10', [(self.p_drink, 15000, 100)])
        self._invoice('2026-01-12', [(self.p_drink, 10000, 100)], partner=self.customer2)
        st = self._settle(self._period(agr, 'Q1/2026'))
        self.assertEqual(st.amount, 50_000, 'tier reached on the group total (2.5M)')
        by_partner = {}
        for det in st.detail_ids:
            by_partner[det.partner_id] = by_partner.get(det.partner_id, 0) + det.allocated_amount
        self.assertEqual(by_partner[self.customer], 30_000)
        self.assertEqual(by_partner[self.customer2], 20_000)
