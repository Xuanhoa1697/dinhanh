from odoo import fields, models


class RebateLine(models.Model):
    _inherit = 'rebate.line'

    cost_amount = fields.Monetary('Giá vốn', currency_field='currency_id',
                                  help='Giá vốn của dòng bán (dòng COGS của hóa đơn, nếu không có thì giá vốn sản phẩm).')


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _rebate_prepare_line_vals(self, line, agreement, rule, period, line_date):
        vals = super()._rebate_prepare_line_vals(line, agreement, rule, period, line_date)
        if agreement.direction != 'sale':
            return vals
        cost = None
        if 'cogs_origin_id' in line._fields:
            cogs = self.line_ids.filtered(lambda ln: ln.display_type == 'cogs' and ln.cogs_origin_id == line)
            if cogs:
                # pair of lines (stock credit / COGS debit) → half of the absolute total
                cost = sum(abs(ln.balance) for ln in cogs) / 2.0
        if cost is None and line.product_id:
            cost = line.product_id.with_company(self.company_id).standard_price * abs(vals['quantity'])
        if cost:
            cost = self.company_currency_id._convert(cost, agreement.currency_id, self.company_id,
                                                     self.invoice_date or self.date)
            vals['cost_amount'] = (1 if vals['amount'] >= 0 else -1) * cost
        return vals
