from odoo import fields, models
from odoo.tools import SQL


class RebateMarginReport(models.Model):
    """T37 / RQ-21 – revenue (or purchase value), cost and settled rebate per accumulation line."""
    _name = 'rebate.margin.report'
    _description = 'Phân tích lợi nhuận sau chiết khấu cuối kỳ'
    _auto = False
    _order = 'date desc'
    _depends = {
        'rebate.line': ['agreement_id', 'period_id', 'partner_id', 'product_id', 'product_categ_id', 'direction',
                        'company_id', 'currency_id', 'date', 'quantity', 'amount', 'cost_amount'],
        'rebate.settlement.detail': ['line_id', 'allocated_amount', 'settlement_id'],
        'rebate.settlement': ['state'],
    }

    line_id = fields.Many2one('rebate.line', readonly=True)
    agreement_id = fields.Many2one('rebate.agreement', string='Thỏa thuận', readonly=True)
    period_id = fields.Many2one('rebate.period', string='Kỳ', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Đối tác', readonly=True)
    product_id = fields.Many2one('product.product', string='Sản phẩm', readonly=True)
    product_categ_id = fields.Many2one('product.category', string='Nhóm sản phẩm', readonly=True)
    direction = fields.Selection([('sale', 'Bán hàng'), ('purchase', 'Mua hàng')], string='Chiều', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    date = fields.Date('Ngày', readonly=True)
    quantity = fields.Float('Số lượng', readonly=True)
    amount = fields.Monetary('Doanh số / giá trị mua', readonly=True)
    cost_amount = fields.Monetary('Giá vốn', readonly=True)
    rebate_amount = fields.Monetary('Chiết khấu đã quyết toán', readonly=True)
    net_amount = fields.Monetary('Giá trị sau chiết khấu', readonly=True)
    margin = fields.Monetary('Lãi gộp sau chiết khấu', readonly=True)

    @property
    def _table_query(self):
        return SQL("""
            SELECT l.id AS id,
                   l.id AS line_id,
                   l.agreement_id, l.period_id, l.partner_id, l.product_id, l.product_categ_id,
                   l.direction, l.company_id, l.currency_id, l.date, l.quantity,
                   l.amount AS amount,
                   COALESCE(l.cost_amount, 0) AS cost_amount,
                   COALESCE(d.rebate, 0) AS rebate_amount,
                   l.amount - COALESCE(d.rebate, 0) AS net_amount,
                   CASE WHEN l.direction = 'sale'
                        THEN l.amount - COALESCE(l.cost_amount, 0) - COALESCE(d.rebate, 0)
                        ELSE 0 END AS margin
              FROM rebate_line l
              LEFT JOIN (
                    SELECT sd.line_id, SUM(sd.allocated_amount) AS rebate
                      FROM rebate_settlement_detail sd
                      JOIN rebate_settlement s ON s.id = sd.settlement_id
                     WHERE s.state = 'done'
                  GROUP BY sd.line_id
              ) d ON d.line_id = l.id
        """)
