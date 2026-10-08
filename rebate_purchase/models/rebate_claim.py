from odoo import api, fields, models


class RebateClaim(models.Model):
    """T24 – difference between the rebate computed by us and the one the vendor granted (TH-24)."""
    _name = 'rebate.claim'
    _description = 'Khiếu nại chênh lệch chiết khấu mua'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char('Số', compute='_compute_name', store=True)
    settlement_id = fields.Many2one('rebate.settlement', string='Quyết toán', required=True, ondelete='cascade',
                                    index=True)
    agreement_id = fields.Many2one(related='settlement_id.agreement_id', store=True)
    company_id = fields.Many2one(related='settlement_id.company_id', store=True)
    currency_id = fields.Many2one(related='settlement_id.currency_id', store=True)
    partner_id = fields.Many2one('res.partner', string='Nhà cung cấp', required=True)
    source_move_id = fields.Many2one('account.move', string='Chứng từ NCC', ondelete='set null')
    expected_amount = fields.Monetary('Số tự tính', currency_field='currency_id')
    received_amount = fields.Monetary('Số NCC chấp nhận', currency_field='currency_id')
    difference = fields.Monetary('Chênh lệch', compute='_compute_difference', store=True,
                                 currency_field='currency_id')
    state = fields.Selection([
        ('open', 'Đang khiếu nại'),
        ('resolved', 'Đã giải quyết'),
        ('written_off', 'Chấp nhận mất'),
        ('cancel', 'Hủy'),
    ], default='open', required=True, tracking=True)
    note = fields.Text('Ghi chú')

    @api.depends('settlement_id.name', 'partner_id.name')
    def _compute_name(self):
        for claim in self:
            claim.name = '%s / %s' % (claim.settlement_id.name or '', claim.partner_id.display_name or '')

    @api.depends('expected_amount', 'received_amount')
    def _compute_difference(self):
        for claim in self:
            claim.difference = claim.expected_amount - claim.received_amount

    def action_resolve(self):
        self.write({'state': 'resolved'})

    def action_write_off(self):
        self.write({'state': 'written_off'})
