from markupsafe import Markup

from odoo import api, fields, models

from odoo.addons.rebate_base.tools import engine


class RebateSimulation(models.TransientModel):
    """T38 – "if we buy / sell X more, how much more rebate?" """
    _name = 'rebate.simulation'
    _description = 'Mô phỏng chiết khấu cuối kỳ'

    period_id = fields.Many2one('rebate.period', string='Kỳ', required=True)
    agreement_id = fields.Many2one(related='period_id.agreement_id')
    currency_id = fields.Many2one(related='period_id.currency_id')
    rule_id = fields.Many2one('rebate.rule', string='Quy tắc', required=True,
                              domain="[('agreement_id', '=', agreement_id), ('is_current', '=', True)]")
    extra_amount = fields.Monetary('Doanh số thêm', currency_field='currency_id')
    extra_qty = fields.Float('Số lượng thêm', digits=(16, 2))
    current_measure = fields.Float('Đã đạt', compute='_compute_result', digits=(16, 2))
    current_amount = fields.Monetary('CK hiện tại', compute='_compute_result', currency_field='currency_id')
    new_measure = fields.Float('Sau khi thêm', compute='_compute_result', digits=(16, 2))
    new_amount = fields.Monetary('CK sau khi thêm', compute='_compute_result', currency_field='currency_id')
    delta_amount = fields.Monetary('CK tăng thêm', compute='_compute_result', currency_field='currency_id')
    result_html = fields.Html(compute='_compute_result', sanitize=False)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        period = self.env['rebate.period'].browse(res.get('period_id') or self.env.context.get('active_id'))
        if period and 'period_id' in fields_list:
            res['period_id'] = period.id
        if period and 'rule_id' in fields_list and not res.get('rule_id'):
            res['rule_id'] = period.agreement_id.rule_ids[:1].id
        return res

    @api.depends('period_id', 'rule_id', 'extra_amount', 'extra_qty')
    def _compute_result(self):
        Settlement = self.env['rebate.settlement']
        for wiz in self:
            rule = wiz.rule_id
            if not wiz.period_id or not rule:
                wiz.update({'current_measure': 0, 'current_amount': 0, 'new_measure': 0, 'new_amount': 0,
                            'delta_amount': 0, 'result_html': False})
                continue
            lines = wiz.period_id._get_all_lines().filtered(lambda ln: ln.rule_key == rule.key)
            measure = lines._measure(rule)
            amount_base = lines._amount_base(rule)
            qty_base = lines._qty_base(rule)
            tiers = rule._engine_tiers()
            current = engine.compute_tier_amount(measure, amount_base, qty_base, tiers, rule.tier_mode,
                                                 rule.value_type, rule.min_threshold, rule.cap_amount)
            add_measure = wiz.extra_qty if rule.basis == 'qty' else wiz.extra_amount
            new = engine.compute_tier_amount(measure + add_measure, amount_base + wiz.extra_amount,
                                             qty_base + wiz.extra_qty, tiers, rule.tier_mode, rule.value_type,
                                             rule.min_threshold, rule.cap_amount)
            wiz.current_measure = measure
            wiz.current_amount = current.amount
            wiz.new_measure = measure + add_measure
            wiz.new_amount = new.amount
            wiz.delta_amount = new.amount - current.amount
            gap_text = '{:,.0f}'.format(new.next_tier_gap) if new.next_tier_gap else '–'
            wiz.result_html = Markup(
                '<p>Hiện tại: đạt <b>%s</b>, CK <b>%s</b>. Sau khi thêm: đạt <b>%s</b>, CK <b>%s</b> '
                '(tăng <b>%s</b>). Còn thiếu để lên bậc kế tiếp: <b>%s</b>.</p>') % (
                '{:,.0f}'.format(measure), wiz.currency_id.format(current.amount),
                '{:,.0f}'.format(measure + add_measure), wiz.currency_id.format(new.amount),
                wiz.currency_id.format(new.amount - current.amount), gap_text)
