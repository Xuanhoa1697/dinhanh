from collections import defaultdict

from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    rebate_alloc_ids = fields.One2many('rebate.purchase.alloc', 'source_move_id', string='Phân bổ CK mua')

    def write(self, vals):
        res = super().write(vals)
        if 'rebate_settlement_id' in vals and not self.env.context.get('rebate_skip_link'):
            self._rebate_link_vendor_document()
        return res

    def _rebate_link_vendor_document(self):
        """The vendor's own credit note (e.g. imported e-invoice) is linked to a
        purchase settlement: its lines are booked on the clearing account."""
        for move in self.filtered(lambda m: m.state == 'draft' and m.move_type in ('in_refund', 'in_invoice')
                                  and m.rebate_settlement_id.direction == 'purchase'):
            account = move.company_id._rebate_account('rebate_purchase_clearing_account_id')
            lines = move.invoice_line_ids.filtered(lambda ln: ln.display_type == 'product' and not ln.rebate_carry_id)
            lines.write({'rebate_settlement_id': move.rebate_settlement_id.id, 'account_id': account.id})

    def _post(self, soft=True):
        posted = super()._post(soft)
        posted._rebate_purchase_on_post()
        return posted

    def button_draft(self):
        purchase_docs = self.filtered(lambda m: m.move_type in ('in_invoice', 'in_refund') and m.rebate_alloc_ids)
        if purchase_docs:
            self.env['rebate.settlement']._rebate_purchase_unallocate(purchase_docs)
        return super().button_draft()

    def _rebate_purchase_on_post(self):
        """When the vendor document carrying the rebate is posted: compare with
        our own figure (claim) then split the rebate on stock / COGS."""
        for move in self.filtered(lambda m: m.move_type in ('in_invoice', 'in_refund')):
            lines = move.invoice_line_ids.filtered(
                lambda ln: ln.rebate_settlement_id and ln.rebate_settlement_id.direction == 'purchase')
            if not lines:
                continue
            by_settlement = defaultdict(lambda: self.env['account.move.line'])
            for line in lines:
                by_settlement[line.rebate_settlement_id] |= line
            for settlement, st_lines in by_settlement.items():
                received_company = -sum(st_lines.mapped('balance'))
                received = -sum(st_lines.mapped('amount_currency')) if move.currency_id == settlement.currency_id \
                    else move.company_currency_id._convert(received_company, settlement.currency_id,
                                                           move.company_id, move.date)
                if not st_lines.rebate_carry_id:
                    settlement._rebate_check_vendor_amount(move, received)
                settlement._rebate_purchase_allocate(move, received_company)
                if move not in settlement.move_ids:
                    settlement.move_ids = [fields.Command.link(move.id)]
