from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class RebateCarryforward(models.Model):
    """T21 – rebate to be deducted on the partner's next invoices / bills."""
    _name = 'rebate.carryforward'
    _description = 'Chiết khấu trừ vào hóa đơn kỳ sau'
    _order = 'id'

    settlement_id = fields.Many2one('rebate.settlement', string='Quyết toán', required=True, ondelete='cascade',
                                    index=True)
    agreement_id = fields.Many2one(related='settlement_id.agreement_id', store=True)
    direction = fields.Selection(related='settlement_id.direction', store=True)
    company_id = fields.Many2one(related='settlement_id.company_id', store=True)
    currency_id = fields.Many2one(related='settlement_id.currency_id', store=True)
    partner_id = fields.Many2one('res.partner', string='Đối tác', required=True, index=True)
    tax_ids = fields.Many2many('account.tax', 'rebate_carryforward_tax_rel', 'carry_id', 'tax_id', string='Thuế')
    tax_rate = fields.Float('Thuế suất (%)', digits=(5, 2))
    amount = fields.Monetary('Số chiết khấu', currency_field='currency_id')
    line_ids = fields.One2many('account.move.line', 'rebate_carry_id', string='Dòng đã trừ')
    amount_used = fields.Monetary('Đã trừ', compute='_compute_amount_used', store=True, currency_field='currency_id')
    amount_residual = fields.Monetary('Còn lại', compute='_compute_amount_used', store=True,
                                      currency_field='currency_id')

    @api.depends('amount', 'line_ids.price_subtotal', 'line_ids.parent_state')
    def _compute_amount_used(self):
        for rec in self:
            used = sum(-ln.price_subtotal for ln in rec.line_ids if ln.parent_state == 'posted')
            rec.amount_used = used
            rec.amount_residual = rec.amount - used

    def _tax_key(self):
        return tuple(sorted(self.tax_ids.ids))


class AccountMove(models.Model):
    _inherit = 'account.move'

    rebate_carry_available = fields.Monetary(compute='_compute_rebate_carry_available',
                                             currency_field='currency_id')

    def _rebate_open_carryforwards(self):
        self.ensure_one()
        if self.move_type not in ('out_invoice', 'in_invoice') or not self.partner_id:
            return self.env['rebate.carryforward']
        return self.env['rebate.carryforward'].sudo().search([
            ('direction', '=', 'sale' if self.move_type == 'out_invoice' else 'purchase'),
            ('company_id', '=', self.company_id.id),
            ('currency_id', '=', self.currency_id.id),
            ('partner_id', '=', self.commercial_partner_id.id),
            ('amount_residual', '>', 0),
        ])

    @api.depends('partner_id', 'move_type', 'currency_id', 'state')
    def _compute_rebate_carry_available(self):
        for move in self:
            if move.state != 'draft' or not move.id:
                move.rebate_carry_available = 0.0
                continue
            move.rebate_carry_available = sum(move._rebate_open_carryforwards().mapped('amount_residual'))

    def _rebate_line_account(self, direction):
        company = self.company_id
        if direction == 'sale':
            return company._rebate_account('rebate_sale_account_id')
        return company._rebate_account('rebate_purchase_clearing_account_id')

    def _rebate_tax_bases(self):
        """Untaxed base of the normal product lines, by tax set."""
        self.ensure_one()
        bases = defaultdict(float)
        for line in self.invoice_line_ids.filtered(lambda ln: ln.display_type == 'product'):
            key = tuple(sorted(line.tax_ids.ids))
            bases[key] += line.price_subtotal
        return bases

    def action_rebate_apply_carryforward(self):
        """Add negative rebate lines on a draft invoice / bill, never above the
        base of the lines with the same tax (TH-17)."""
        for move in self:
            if move.state != 'draft':
                raise UserError(self.env._('Chỉ áp chiết khấu trên hóa đơn nháp.'))
            direction = 'sale' if move.move_type == 'out_invoice' else 'purchase'
            account = move._rebate_line_account(direction)
            product = move.company_id._rebate_product()
            bases = move._rebate_tax_bases()
            cmds = []
            for carry in move._rebate_open_carryforwards():
                pending = sum(-ln.price_subtotal for ln in carry.line_ids if ln.move_id == move)
                available = carry.amount_residual - pending
                key = carry._tax_key()
                take = min(available, bases.get(key, 0.0))
                take = move.currency_id.round(take)
                if take <= 0:
                    continue
                bases[key] -= take
                cmds.append(Command.create({
                    'product_id': product.id,
                    'name': self.env._('Chiết khấu thương mại %(period)s theo thỏa thuận %(agr)s',
                                       period=carry.settlement_id.period_id.name, agr=carry.agreement_id.name),
                    'quantity': 1,
                    'price_unit': -take,
                    'tax_ids': [Command.set(carry.tax_ids.ids)],
                    'account_id': account.id,
                    'rebate_carry_id': carry.id,
                    'rebate_settlement_id': carry.settlement_id.id,
                }))
            if not cmds:
                raise UserError(self.env._('Không còn chiết khấu nào áp được cho hóa đơn này '
                                           '(đã hết, hoặc không có dòng hàng cùng thuế suất).'))
            move.write({'invoice_line_ids': cmds})
        return True

    def _rebate_check_carry_limits(self):
        for move in self:
            carry_lines = move.invoice_line_ids.filtered('rebate_carry_id')
            if not carry_lines:
                continue
            bases = defaultdict(float)
            for line in move.invoice_line_ids.filtered(
                    lambda ln: ln.display_type == 'product' and not ln.rebate_carry_id):
                bases[tuple(sorted(line.tax_ids.ids))] += line.price_subtotal
            used = defaultdict(float)
            for line in carry_lines:
                used[tuple(sorted(line.tax_ids.ids))] += -line.price_subtotal
            for key, amount in used.items():
                if move.currency_id.compare_amounts(amount, bases.get(key, 0.0)) > 0:
                    raise UserError(self.env._(
                        'Chiết khấu trừ trên hóa đơn %(move)s (%(amount)s) vượt giá trị hàng hóa cùng thuế suất '
                        '(%(base)s). Hãy giảm số trừ hoặc lập hóa đơn điều chỉnh kèm bảng kê.',
                        move=move.display_name, amount=move.currency_id.format(amount),
                        base=move.currency_id.format(bases.get(key, 0.0))))
            for carry in carry_lines.rebate_carry_id:
                carry.invalidate_recordset(['amount_used', 'amount_residual'])
                total = sum(-ln.price_subtotal for ln in carry.line_ids
                            if ln.parent_state == 'posted' or ln.move_id == move)
                if move.currency_id.compare_amounts(total, carry.amount) > 0:
                    raise UserError(self.env._('Số trừ vượt số chiết khấu còn lại của %s.',
                                               carry.settlement_id.name))

    def _post(self, soft=True):
        self._rebate_check_carry_limits()
        return super()._post(soft)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    rebate_carry_id = fields.Many2one('rebate.carryforward', string='CK trừ kỳ sau', copy=False,
                                      index='btree_not_null')
