from odoo import models


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _rebate_value_delta(self):
        self.ensure_one()
        allocs = self.env['rebate.purchase.alloc'].sudo().search([
            ('stock_move_id', '=', self.id), ('state', '=', 'posted')])
        return sum(allocs.mapped('value_delta')), allocs

    def _get_value_from_extra(self, quantity, at_date=None):
        """Purchase rebates lower the value of the receipt (same hook as landed costs),
        so FIFO layers and the average cost are recomputed by Odoo itself."""
        data = super()._get_value_from_extra(quantity, at_date=at_date)
        if not self.is_in and not self._is_in():
            return data
        delta, allocs = self._rebate_value_delta()
        if not delta:
            return data
        valued_qty = self._get_valued_qty()
        ratio = quantity / valued_qty if valued_qty else 1.0
        data['value'] += delta * ratio
        desc = self.env._('%(v)s chiết khấu cuối kỳ (%(s)s)', v=self.company_currency_id.format(delta * ratio),
                          s=', '.join(allocs.settlement_id.mapped('name')))
        data['description'] = (data.get('description') + '\n' + desc) if data.get('description') else desc
        return data
