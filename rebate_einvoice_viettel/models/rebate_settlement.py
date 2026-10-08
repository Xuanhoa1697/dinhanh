import base64
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class RebateSettlement(models.Model):
    _inherit = 'rebate.settlement'

    def _rebate_pick_origin_invoice(self, targets):
        """Viettel only accepts an adjustment of an invoice already issued on
        S-Invoice: prefer the latest *sent* invoice of the period."""
        sent = targets.filtered(lambda m: m.move_type == 'out_invoice' and m.state == 'posted'
                                and m._l10n_vn_edi_is_sent())
        if sent:
            return super()._rebate_pick_origin_invoice(sent)
        return super()._rebate_pick_origin_invoice(targets)

    def _rebate_statement_label(self):
        self.ensure_one()
        return self.env._('Bảng kê kèm theo quyết toán %s', self.name)

    def _rebate_sale_document_vals(self, partner, groups, origin):
        vals = super()._rebate_sale_document_vals(partner, groups, origin)
        if vals.get('move_type') == 'out_refund' and origin:
            vals.update({
                'l10n_vn_edi_adjustment_type': '1',  # money adjustment
                'l10n_vn_edi_agreement_document_name': self._rebate_statement_label()[:255],
                'l10n_vn_edi_agreement_document_date': fields.Datetime.now(),
            })
            if origin.l10n_vn_edi_invoice_symbol:
                vals['l10n_vn_edi_invoice_symbol'] = origin.l10n_vn_edi_invoice_symbol.id
        return vals

    def _rebate_after_sale_document(self, move, entry):
        res = super()._rebate_after_sale_document(move, entry)
        origin = move.reversed_entry_id
        if move.move_type == 'out_refund' and origin and not origin._l10n_vn_edi_is_sent():
            move.message_post(body=self.env._(
                'Hóa đơn gốc %s chưa phát hành trên Viettel S-Invoice: cần phát hành hóa đơn gốc trước khi '
                'gửi hóa đơn điều chỉnh này.', origin.display_name))
        self._rebate_attach_statement(move)
        return res

    def _rebate_attach_statement(self, move):
        """Attach the adjustment statement (bảng kê) of this customer to the document."""
        self.ensure_one()
        try:
            pdf, _fmt = self.env['ir.actions.report'].with_context(
                rebate_partner_id=move.commercial_partner_id.id,
            )._render_qweb_pdf('rebate_base.action_report_rebate_statement', self.ids)
        except Exception as e:  # noqa: BLE001 – wkhtmltopdf missing, … never block the settlement
            _logger.warning('Rebate statement PDF not generated for %s: %s', self.name, e)
            return False
        attachment = self.env['ir.attachment'].create({
            'name': 'BangKe_%s_%s.pdf' % (self.name.replace('/', '_'), move.commercial_partner_id.vat or move.id),
            'type': 'binary',
            'datas': base64.b64encode(pdf),
            'res_model': 'account.move',
            'res_id': move.id,
            'mimetype': 'application/pdf',
        })
        move.message_post(body=self.env._('Bảng kê hóa đơn điều chỉnh'), attachment_ids=attachment.ids)
        return attachment
