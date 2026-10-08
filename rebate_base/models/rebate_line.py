from odoo import fields, models


class RebateLine(models.Model):
    """Accumulation line: one invoice line counted in one agreement.

    Source of truth for progress, accrual, settlement and reports. Never edited:
    returns / adjustments create negative lines, reset-to-draft deletes them.
    """
    _name = 'rebate.line'
    _description = 'Dòng lũy kế chiết khấu cuối kỳ'
    _order = 'date desc, id desc'

    agreement_id = fields.Many2one('rebate.agreement', string='Thỏa thuận', required=True, ondelete='cascade',
                                   index=True)
    period_id = fields.Many2one('rebate.period', string='Kỳ', required=True, ondelete='cascade', index=True)
    rule_id = fields.Many2one('rebate.rule', string='Quy tắc', required=True, ondelete='cascade', index=True)
    rule_key = fields.Char(related='rule_id.key', store=True, index=True)
    direction = fields.Selection(related='agreement_id.direction', store=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    currency_id = fields.Many2one(related='agreement_id.currency_id', store=True)
    move_id = fields.Many2one('account.move', string='Hóa đơn', required=True, ondelete='cascade', index=True)
    move_line_id = fields.Many2one('account.move.line', string='Dòng hóa đơn', required=True,
                                   ondelete='cascade', index=True)
    target_move_id = fields.Many2one('account.move', string='Hóa đơn được điều chỉnh', index=True,
                                     help='Hóa đơn gốc (với hàng trả lại) – dùng để lập bảng kê.')
    partner_id = fields.Many2one('res.partner', string='Đối tác', index=True)
    product_id = fields.Many2one('product.product', string='Sản phẩm', index=True)
    product_categ_id = fields.Many2one(related='product_id.categ_id', store=True, string='Nhóm sản phẩm')
    date = fields.Date('Ngày', required=True, index=True)
    is_refund = fields.Boolean('Trả hàng / giảm')
    quantity = fields.Float('Số lượng (ĐVT gốc)', digits='Product Unit')
    weight = fields.Float('Trọng lượng', digits='Stock Weight')
    amount = fields.Monetary('Giá trị sau CK dòng', currency_field='currency_id')
    amount_gross = fields.Monetary('Giá trị trước CK dòng', currency_field='currency_id')
    tax_ids = fields.Many2many('account.tax', 'rebate_line_tax_rel', 'line_id', 'tax_id', string='Thuế')
    tax_rate = fields.Float('Thuế suất (%)', digits=(5, 2))

    _uniq_line_agreement = models.UniqueIndex('(move_line_id, agreement_id)')

    def _measure(self, rule):
        """Value compared with tiers, per rule basis (T11)."""
        basis = rule.basis
        if basis == 'qty':
            return sum(rule._convert_qty(line.quantity, line.product_id) for line in self)
        if basis == 'weight':
            return sum(self.mapped('weight'))
        if basis == 'amount_gross':
            return sum(self.mapped('amount_gross'))
        return sum(self.mapped('amount'))

    def _amount_base(self, rule):
        return sum(self.mapped('amount_gross' if rule.basis == 'amount_gross' else 'amount'))

    def _qty_base(self, rule):
        return sum(rule._convert_qty(line.quantity, line.product_id) for line in self)
