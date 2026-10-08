from odoo import fields, models


class RebatePurchaseAlloc(models.Model):
    """T26/T27 – one line of the split of a purchase rebate on stock and COGS."""
    _name = 'rebate.purchase.alloc'
    _description = 'Phân bổ chiết khấu mua vào tồn kho / giá vốn'
    _order = 'id'

    settlement_id = fields.Many2one('rebate.settlement', required=True, ondelete='cascade', index=True)
    source_move_id = fields.Many2one('account.move', string='Chứng từ NCC', ondelete='cascade', index=True)
    detail_id = fields.Many2one('rebate.settlement.detail', string='Dòng phân bổ', ondelete='set null')
    bill_line_id = fields.Many2one('account.move.line', string='Dòng hóa đơn mua', ondelete='set null')
    product_id = fields.Many2one('product.product', string='Sản phẩm')
    stock_move_id = fields.Many2one('stock.move', string='Lô nhập', ondelete='set null', index='btree_not_null')
    company_id = fields.Many2one('res.company', required=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    cost_method = fields.Selection([('standard', 'Giá chuẩn'), ('fifo', 'FIFO'), ('average', 'Bình quân')],
                                   string='Phương pháp giá')
    valuation = fields.Selection([('periodic', 'Định kỳ'), ('real_time', 'Thường xuyên')], string='Định giá')
    qty_in = fields.Float('SL nhập', digits='Product Unit')
    qty_remaining = fields.Float('SL còn tồn', digits='Product Unit')
    amount = fields.Monetary('CK phân bổ', currency_field='currency_id')
    value_delta = fields.Monetary('Điều chỉnh giá trị lô nhập', currency_field='currency_id',
                                  help='Số âm cộng vào giá trị lô nhập (FIFO / Bình quân).')
    to_inventory = fields.Monetary('Vào tồn kho', currency_field='currency_id')
    to_cogs = fields.Monetary('Vào giá vốn / chi phí', currency_field='currency_id')
    inventory_account_id = fields.Many2one('account.account', string='TK tồn kho / chênh lệch giá')
    cogs_account_id = fields.Many2one('account.account', string='TK giá vốn / chi phí')
    entry_id = fields.Many2one('account.move', string='Bút toán phân bổ', ondelete='set null')
    state = fields.Selection([('posted', 'Đã ghi sổ'), ('cancel', 'Đã hủy')], default='posted', required=True)
