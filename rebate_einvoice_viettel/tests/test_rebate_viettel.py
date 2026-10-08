from odoo import fields
from odoo.tests import tagged

from odoo.addons.rebate_base.tests.common import RebateCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'rebate')
class TestRebateViettel(RebateCommon):

    @classmethod
    @RebateCommon.setup_country('vn')
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env['l10n_vn_edi_viettel.sinvoice.template'].create({
            'name': '1/001', 'template_invoice_type': '1'})
        cls.symbol = cls.env['l10n_vn_edi_viettel.sinvoice.symbol'].create({
            'name': 'K26TUT', 'invoice_template_id': cls.template.id})
        cls.env['ir.default'].set('res.partner', 'l10n_vn_edi_symbol', cls.symbol.id, company_id=cls.company.id)
        address = {
            'street': '3 Phan Dinh Phung', 'state_id': cls.env.ref('base.state_vn_VN-HN').id,
            'country_id': cls.env.ref('base.vn').id, 'phone': '0912345678',
        }
        cls.company.write(dict(address, vat='0100109106', l10n_vn_edi_username='u', l10n_vn_edi_password='p'))
        cls.customer.write(dict(address, vat='0101234567'))

    def test_01_adjustment_refers_to_sent_invoice(self):
        agr = self._create_agreement(settlement_doc='adjust_invoice', payment_method='cash')
        self._invoice('2026-01-10', [(self.p_drink, 10000, 100)])
        i2 = self._invoice('2026-02-10', [(self.p_drink, 8000, 100)])
        self._invoice('2026-03-10', [(self.p_drink, 7000, 100)])  # not issued on S-Invoice yet
        i2.write({
            'l10n_vn_edi_invoice_number': 'K26TUT0000123',
            'l10n_vn_edi_issue_date': fields.Datetime.now(),
            'l10n_vn_edi_invoice_state': 'sent',
        })
        st = self._settle(self._period(agr, 'Q1/2026'))
        st.action_submit()
        st.action_approve()
        st.action_generate_documents()
        refund = st.move_ids
        self.assertEqual(refund.reversed_entry_id, i2)
        self.assertEqual(refund.l10n_vn_edi_adjustment_type, '1')
        self.assertIn(st.name, refund.l10n_vn_edi_agreement_document_name)
        info = refund._l10n_vn_edi_generate_invoice_json()['generalInvoiceInfo']
        self.assertEqual(info['adjustmentType'], '5')
        self.assertEqual(info['originalInvoiceId'], 'K26TUT0000123')
        self.assertTrue(self.env['ir.attachment'].search_count([
            ('res_model', '=', 'account.move'), ('res_id', '=', refund.id)]))
        self.assertEqual(st._statement_rows()[0]['number'], st._statement_rows()[0]['move']._rebate_invoice_number())
