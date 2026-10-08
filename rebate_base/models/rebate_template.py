from odoo import fields, models

from . import selections as sel


class RebateTemplate(models.Model):
    """T08 – Mẫu thỏa thuận: giá trị mặc định cho cấu hình tầng 2."""
    _name = 'rebate.template'
    _description = 'Mẫu thỏa thuận chiết khấu cuối kỳ'
    _order = 'sequence, name'

    name = fields.Char('Tên mẫu', required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Công ty')
    direction = fields.Selection(sel.DIRECTION, string='Chiều', required=True, default='sale')
    nature = fields.Selection(sel.NATURE, string='Bản chất', required=True, default='trade')
    period_type = fields.Selection(sel.PERIOD_TYPE, string='Kỳ tính', required=True, default='quarter')
    settlement_doc = fields.Selection(sel.SETTLEMENT_DOC, string='Chứng từ quyết toán', required=True,
                                      default='adjust_invoice')
    payment_method = fields.Selection(sel.PAYMENT_METHOD, string='Hình thức chi trả', required=True,
                                      default='offset')
    allocation_key = fields.Selection(sel.ALLOCATION_KEY, string='Phân bổ về hóa đơn', required=True,
                                      default='amount')
    cogs_split = fields.Selection(sel.COGS_SPLIT, string='Phân bổ giá vốn (mua)', required=True,
                                  default='method')
    return_period_rule = fields.Selection(sel.RETURN_PERIOD_RULE, string='Trả hàng tính vào kỳ',
                                          required=True, default='origin')
    post_close_recalc = fields.Selection(sel.POST_CLOSE_RECALC, string='Phát sinh sau khi chốt',
                                         required=True, default='recalc')
    negative_true_up = fields.Selection(sel.NEGATIVE_TRUE_UP, string='Quyết toán năm âm',
                                        required=True, default='ignore')
    mid_period_change = fields.Selection(sel.MID_PERIOD_CHANGE, string='Sửa đổi giữa kỳ',
                                         required=True, default='segment')
    stacking = fields.Selection(sel.STACKING, string='Chồng chương trình', required=True,
                                default='cumulative')
    basis = fields.Selection(sel.BASIS, string='Cơ sở tính', required=True, default='amount')
    tier_mode = fields.Selection(sel.TIER_MODE, string='Kiểu bậc', required=True, default='retro')
    value_type = fields.Selection(sel.VALUE_TYPE, string='Giá trị chiết khấu', required=True,
                                  default='percent')
    note = fields.Text('Ghi chú')
