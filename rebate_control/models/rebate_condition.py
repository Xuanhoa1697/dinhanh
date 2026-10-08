from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

CONDITION_TYPES = [
    ('overdue', 'Không có nợ quá hạn'),
    ('return_rate', 'Tỷ lệ trả hàng tối đa'),
    ('growth', 'Tăng trưởng so với cùng kỳ'),
    ('mix', 'Cơ cấu sản phẩm tối thiểu'),
]
DEFAULT_EFFECT = {'overdue': 'block', 'return_rate': 'block', 'growth': 'bonus', 'mix': 'block'}


class RebateCondition(models.Model):
    """T29/T30 – conditions evaluated at settlement.

    Each type is a plugin: ``_eval_<type>(settlement, lines, evaluation)`` returns
    ``(passed, message)``. Add a selection value + a method to add a type.
    """
    _name = 'rebate.condition'
    _description = 'Điều kiện hưởng chiết khấu cuối kỳ'
    _order = 'sequence, id'

    agreement_id = fields.Many2one('rebate.agreement', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='agreement_id.currency_id')
    sequence = fields.Integer(default=10)
    condition_type = fields.Selection(CONDITION_TYPES, string='Điều kiện', required=True, default='overdue')
    effect = fields.Selection([
        ('block', 'Không đạt: không được hưởng'),
        ('reduce', 'Không đạt: giảm % chiết khấu'),
        ('bonus', 'Đạt: thưởng thêm % doanh số'),
    ], string='Tác động', required=True, compute='_compute_effect', store=True, readonly=False,
        precompute=True)
    effect_value = fields.Float('Giá trị tác động (%)', digits=(5, 2))
    max_overdue_days = fields.Integer('Số ngày quá hạn cho phép', default=0)
    max_overdue_amount = fields.Monetary('Số nợ quá hạn cho phép', currency_field='currency_id')
    max_return_rate = fields.Float('Tỷ lệ trả hàng tối đa (%)', digits=(5, 2), default=10)
    growth_rate = fields.Float('Tăng trưởng tối thiểu (%)', digits=(5, 2), default=10)
    new_partner_pass = fields.Boolean('Đối tác chưa có cùng kỳ: coi như đạt')
    mix_product_categ_ids = fields.Many2many('product.category', 'rebate_condition_categ_rel', 'condition_id',
                                             'categ_id', string='Nhóm sản phẩm cần đạt')
    mix_product_ids = fields.Many2many('product.product', 'rebate_condition_product_rel', 'condition_id',
                                       'product_id', string='Sản phẩm cần đạt')
    min_share = fields.Float('Tỷ trọng tối thiểu (%)', digits=(5, 2), default=30)
    description = fields.Char(compute='_compute_description')

    @api.depends('condition_type')
    def _compute_effect(self):
        for cond in self:
            cond.effect = DEFAULT_EFFECT.get(cond.condition_type, 'block')

    @api.depends('condition_type', 'max_overdue_days', 'max_return_rate', 'growth_rate', 'min_share',
                 'effect', 'effect_value')
    def _compute_description(self):
        for cond in self:
            text = {
                'overdue': 'Nợ quá hạn > %s ngày' % cond.max_overdue_days,
                'return_rate': 'Trả hàng ≤ %g%%' % cond.max_return_rate,
                'growth': 'Tăng trưởng ≥ %g%%' % cond.growth_rate,
                'mix': 'Tỷ trọng nhóm chỉ định ≥ %g%%' % cond.min_share,
            }.get(cond.condition_type, '')
            if cond.effect != 'block':
                text += ' → %s %g%%' % ('thưởng' if cond.effect == 'bonus' else 'giảm', cond.effect_value)
            cond.description = text

    # ------------------------------------------------------------------
    def _evaluate(self, settlement, lines, evaluation):
        self.ensure_one()
        method = getattr(self, '_eval_%s' % self.condition_type)
        return method(settlement, lines, evaluation)

    def _partners(self, settlement, lines):
        agreement = settlement.agreement_id
        return (lines.partner_id.commercial_partner_id | agreement.partner_ids.commercial_partner_id)

    def _eval_overdue(self, settlement, lines, evaluation):
        today = fields.Date.context_today(self)
        limit_date = today - relativedelta(days=self.max_overdue_days)
        account_type = 'asset_receivable' if settlement.direction == 'sale' else 'liability_payable'
        overdue = self.env['account.move.line'].sudo().search([
            ('company_id', '=', settlement.company_id.id),
            ('account_id.account_type', '=', account_type),
            ('partner_id.commercial_partner_id', 'in', self._partners(settlement, lines).ids),
            ('parent_state', '=', 'posted'),
            ('reconciled', '=', False),
            ('date_maturity', '<', limit_date),
        ])
        amount = abs(sum(overdue.mapped('amount_residual')))
        currency = settlement.company_id.currency_id
        ok = currency.compare_amounts(amount, self.max_overdue_amount or 0.0) <= 0
        return ok, self.env._('Nợ quá hạn trên %(d)s ngày: %(a)s (cho phép %(m)s)',
                              d=self.max_overdue_days, a=currency.format(amount),
                              m=currency.format(self.max_overdue_amount or 0.0))

    def _eval_return_rate(self, settlement, lines, evaluation):
        sold = sum(ln.amount for ln in lines if not ln.is_refund)
        returned = -sum(ln.amount for ln in lines if ln.is_refund)
        rate = returned / sold * 100 if sold else 0.0
        return rate <= self.max_return_rate, self.env._('Tỷ lệ trả hàng %(r).2f%% (tối đa %(m)g%%)',
                                                        r=rate, m=self.max_return_rate)

    def _eval_growth(self, settlement, lines, evaluation):
        current = sum(lines.mapped('amount'))
        previous = self._previous_year_base(settlement, lines)
        if not previous:
            return self.new_partner_pass, self.env._('Chưa có doanh số cùng kỳ năm trước')
        growth = (current - previous) / previous * 100
        return growth >= self.growth_rate, self.env._(
            'Tăng trưởng %(g).2f%% (cùng kỳ %(p)s, kỳ này %(c)s; yêu cầu ≥ %(r)g%%)',
            g=growth, p=settlement.currency_id.format(previous), c=settlement.currency_id.format(current),
            r=self.growth_rate)

    def _previous_year_base(self, settlement, lines):
        agreement = settlement.agreement_id
        dfrom = settlement.period_id.date_from - relativedelta(years=1)
        dto = settlement.period_id.date_to - relativedelta(years=1)
        types = ('out_invoice', 'out_refund') if settlement.direction == 'sale' else ('in_invoice', 'in_refund')
        amls = self.env['account.move.line'].sudo().search([
            ('company_id', '=', settlement.company_id.id),
            ('move_id.move_type', 'in', types),
            ('parent_state', '=', 'posted'),
            ('display_type', '=', 'product'),
            ('move_id.invoice_date', '>=', dfrom),
            ('move_id.invoice_date', '<=', dto),
            ('move_id.rebate_settlement_id', '=', False),
            ('partner_id.commercial_partner_id', 'in', self._partners(settlement, lines).ids),
        ])
        rules = agreement.with_context(active_test=False).all_rule_ids.filtered('approved')
        total = 0.0
        for aml in amls:
            if not any(rule._matches_product(aml.product_id) for rule in rules):
                continue
            sign = -1 if aml.move_id.move_type in ('out_refund', 'in_refund') else 1
            amount = aml.currency_id._convert(aml.price_subtotal, settlement.currency_id, settlement.company_id,
                                              aml.move_id.invoice_date)
            total += sign * amount
        return total

    def _eval_mix(self, settlement, lines, evaluation):
        total = sum(lines.mapped('amount'))

        def in_mix(product):
            if product in self.mix_product_ids:
                return True
            path = product.categ_id.parent_path or ''
            return any(path.startswith(c.parent_path) for c in self.mix_product_categ_ids if c.parent_path)
        share_amount = sum(ln.amount for ln in lines if ln.product_id and in_mix(ln.product_id))
        share = share_amount / total * 100 if total else 0.0
        return share >= self.min_share, self.env._('Tỷ trọng nhóm chỉ định %(s).2f%% (yêu cầu ≥ %(m)g%%)',
                                                   s=share, m=self.min_share)


class RebateAgreement(models.Model):
    _inherit = 'rebate.agreement'

    condition_ids = fields.One2many('rebate.condition', 'agreement_id', string='Điều kiện hưởng')
