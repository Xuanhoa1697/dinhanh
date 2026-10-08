from odoo import fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class RebateSettlement(models.Model):
    _inherit = 'rebate.settlement'

    # ------------------------------------------------------------------
    # T20 – adjustment invoice (HĐ điều chỉnh giảm kèm bảng kê)
    # ------------------------------------------------------------------
    def _rebate_generate_sale_adjust_invoice(self):
        return self._rebate_create_sale_documents(link_origin=True)

    def _rebate_generate_sale_credit_note(self):
        return self._rebate_create_sale_documents(link_origin=False)

    def _rebate_pick_origin_invoice(self, targets):
        """Invoice the adjustment refers to: the latest invoice of the period
        (TH-17 'hóa đơn lần mua cuối'). Overridden by the e-invoice module."""
        invoices = targets.filtered(lambda m: m.move_type == 'out_invoice' and m.state == 'posted')
        return invoices.sorted(lambda m: (m.invoice_date or fields.Date.today(), m.id))[-1:]

    def _rebate_sale_document_vals(self, partner, groups, origin):
        """Values of the adjustment document of one customer.

        :param groups: list of (tax recordset, amount) – one line per tax rate (RQ-14)
        """
        self.ensure_one()
        company = self.company_id
        total = sum(amount for _taxes, amount in groups)
        move_type = 'out_refund' if total > 0 else 'out_invoice'
        sign = 1 if total > 0 else -1
        account = company._rebate_account('rebate_sale_account_id')
        if not account:
            raise UserError(self.env._('Chưa cấu hình tài khoản chiết khấu bán (521).'))
        product = company._rebate_product()
        period = self.period_id
        label = self.env._(
            'Chiết khấu thương mại kỳ %(period)s (%(dfrom)s – %(dto)s) theo thỏa thuận %(agr)s, kèm bảng kê',
            period=period.name, dfrom=period.date_from.strftime('%d/%m/%Y'),
            dto=period.date_to.strftime('%d/%m/%Y'), agr=self.agreement_id.name)
        lines = []
        for taxes, amount in groups:
            if not amount:
                continue
            lines.append(Command.create({
                'product_id': product.id,
                'name': label,
                'quantity': 1,
                'price_unit': sign * amount,
                'tax_ids': [Command.set(taxes.ids)],
                'account_id': account.id,
                'rebate_settlement_id': self.id,
            }))
        vals = {
            'move_type': move_type,
            'partner_id': partner.id,
            'currency_id': self.currency_id.id,
            'invoice_date': self.doc_date,
            'date': self.doc_date,
            'journal_id': company._rebate_journal('sale').id,
            'ref': '%s – %s' % (self.name, self.agreement_id.name),
            'rebate_settlement_id': self.id,
            'invoice_line_ids': lines,
            'narration': label,
        }
        if move_type == 'out_refund' and origin:
            vals['reversed_entry_id'] = origin.id
        return vals

    def _rebate_create_sale_documents(self, link_origin=True):
        self.ensure_one()
        by_partner = {}
        for (partner, _key), details in self._rebate_group_details().items():
            entry = by_partner.setdefault(partner, {'groups': [], 'targets': self.env['account.move']})
            amount = self.currency_id.round(sum(details.mapped('allocated_amount')))
            entry['groups'].append((details[:1].tax_ids, amount))
            entry['targets'] |= details.target_move_id
        moves = self.env['account.move']
        for partner, entry in by_partner.items():
            if not self.currency_id.round(sum(a for _t, a in entry['groups'])):
                continue
            origin = self._rebate_pick_origin_invoice(entry['targets']) if link_origin else False
            buyer = origin.partner_id if origin else partner
            vals = self._rebate_sale_document_vals(buyer, entry['groups'], origin)
            move = self.env['account.move'].create(vals)
            move.action_post()
            self._rebate_after_sale_document(move, entry)
            moves |= move
        if self.agreement_id.payment_method == 'offset':
            moves._rebate_offset_receivables()
        return moves

    def _rebate_after_sale_document(self, move, entry):
        """Hook (e-invoice attachments …)."""
        return True


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _rebate_offset_receivables(self):
        """T22 – reconcile the rebate credit note with the customer's oldest open invoices."""
        for move in self.filtered(lambda m: m.move_type == 'out_refund' and m.state == 'posted'):
            credit_lines = move.line_ids.filtered(
                lambda ln: ln.account_id.account_type == 'asset_receivable' and not ln.reconciled)
            for credit_line in credit_lines:
                open_lines = self.env['account.move.line'].search([
                    ('company_id', '=', move.company_id.id),
                    ('account_id', '=', credit_line.account_id.id),
                    ('partner_id.commercial_partner_id', '=', move.commercial_partner_id.id),
                    ('parent_state', '=', 'posted'),
                    ('reconciled', '=', False),
                    ('balance', '>', 0),
                    ('move_id.rebate_settlement_id', '=', False),
                ], order='date_maturity, date, id')
                if open_lines:
                    (credit_line | open_lines).reconcile()
