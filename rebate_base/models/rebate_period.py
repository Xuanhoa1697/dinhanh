from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError


class RebatePeriod(models.Model):
    _name = 'rebate.period'
    _description = 'Kỳ chiết khấu cuối kỳ'
    _order = 'agreement_id, date_from, parent_path'
    _parent_store = True

    name = fields.Char('Kỳ', required=True)
    agreement_id = fields.Many2one('rebate.agreement', string='Thỏa thuận', required=True, ondelete='cascade',
                                   index=True)
    direction = fields.Selection(related='agreement_id.direction', store=True)
    company_id = fields.Many2one(related='agreement_id.company_id', store=True)
    currency_id = fields.Many2one(related='agreement_id.currency_id')
    date_from = fields.Date('Từ ngày', required=True)
    date_to = fields.Date('Đến ngày', required=True)
    parent_id = fields.Many2one('rebate.period', string='Kỳ tổng', ondelete='cascade', index=True)
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('rebate.period', 'parent_id', string='Kỳ con')
    state = fields.Selection([
        ('open', 'Đang mở'),
        ('locked', 'Đã khóa'),
        ('settled', 'Đã quyết toán'),
    ], string='Trạng thái', default='open', required=True, copy=False)
    needs_recalc = fields.Boolean('Cần tính lại', copy=False,
                                  help='Có phát sinh mới (trả hàng, điều chỉnh) sau khi kỳ đã khóa / quyết toán.')
    line_ids = fields.One2many('rebate.line', 'period_id', string='Dòng lũy kế')
    settlement_ids = fields.One2many('rebate.settlement', 'period_id', string='Quyết toán')

    # T16 – progress (computed on demand)
    progress_measure = fields.Float('Đã đạt', compute='_compute_progress', digits=(16, 2))
    progress_amount = fields.Monetary('CK dự kiến', compute='_compute_progress', currency_field='currency_id')
    progress_gap = fields.Float('Còn thiếu để lên bậc', compute='_compute_progress', digits=(16, 2))
    progress_html = fields.Html('Tiến độ theo quy tắc', compute='_compute_progress', sanitize=False)
    settled_amount = fields.Monetary('Đã quyết toán', compute='_compute_settled_amount',
                                     currency_field='currency_id')

    def _get_all_lines(self):
        return self.env['rebate.line'].search([('period_id', 'child_of', self.ids)])

    def _compute_progress(self):
        Settlement = self.env['rebate.settlement']
        for period in self:
            evaluation = Settlement._rebate_evaluate(period.agreement_id, period, period._get_all_lines())
            rules = evaluation['rules']
            period.progress_measure = sum(r['measure'] for r in rules)
            period.progress_amount = evaluation['gross_amount']
            period.progress_gap = min((r['next_gap'] for r in rules if r['next_gap'] > 0), default=0.0)
            rows = Markup('').join(
                Markup('<tr><td>%s</td><td class="text-end">%s</td><td>%s</td>'
                       '<td class="text-end">%s</td><td class="text-end">%s</td></tr>') % (
                    r['rule'].name, '{:,.2f}'.format(r['measure']), r['tier_label'],
                    '{:,.2f}'.format(r['next_gap']) if r['next_gap'] else '–',
                    '{:,.0f}'.format(r['amount']))
                for r in rules)
            period.progress_html = Markup(
                '<table class="table table-sm o_rebate_progress"><thead><tr><th>Quy tắc</th>'
                '<th class="text-end">Đã đạt</th><th>Bậc</th><th class="text-end">Còn thiếu</th>'
                '<th class="text-end">CK dự kiến</th></tr></thead><tbody>%s</tbody></table>') % rows if rules else \
                Markup('<p>%s</p>') % escape(self.env._('Chưa có phát sinh.'))

    @api.depends('settlement_ids.state', 'settlement_ids.amount_to_settle')
    def _compute_settled_amount(self):
        for period in self:
            period.settled_amount = sum(period.settlement_ids.filtered(
                lambda s: s.state == 'done').mapped('amount_to_settle'))

    @api.depends('name', 'agreement_id.name')
    def _compute_display_name(self):
        for period in self:
            period.display_name = '%s – %s' % (period.agreement_id.name, period.name)

    # ------------------------------------------------------------------
    def action_lock(self):
        for period in self:
            if period.state != 'open':
                continue
            if period.child_ids.filtered(lambda c: c.state == 'open'):
                raise UserError(self.env._('Hãy khóa các kỳ con của %s trước.', period.display_name))
            period.state = 'locked'

    def action_unlock(self):
        for period in self:
            if period.settlement_ids.filtered(lambda s: s.state == 'done'):
                raise UserError(self.env._('Kỳ %s đã có quyết toán, không mở lại được.', period.display_name))
            if period.state == 'locked':
                period.state = 'open'

    def _current_settlement(self):
        self.ensure_one()
        return self.settlement_ids.filtered(lambda s: s.state != 'cancel' and not s.is_adjustment)[:1]

    def action_compute_settlement(self):
        """Lock (if needed) and compute the settlement of the period – idempotent."""
        settlements = self.env['rebate.settlement']
        for period in self:
            if period.state == 'open':
                period.action_lock()
            settlement = period._current_settlement()
            if settlement and settlement.state not in ('draft', 'computed'):
                if period.needs_recalc:
                    settlement = period._create_adjustment()
                else:
                    settlements |= settlement
                    continue
            if not settlement:
                settlement = self.env['rebate.settlement'].create({
                    'agreement_id': period.agreement_id.id,
                    'period_id': period.id,
                })
            settlement.action_compute()
            settlements |= settlement
        if len(settlements) == 1:
            return settlements.get_formview_action()
        return True

    def _create_adjustment(self):
        """T33 – adjustment settlement after a post-close change."""
        self.ensure_one()
        pending = self.settlement_ids.filtered(lambda s: s.is_adjustment and s.state in ('draft', 'computed'))
        if pending:
            return pending[:1]
        origin = self.settlement_ids.filtered(lambda s: s.state == 'done' and not s.is_adjustment)[:1]
        return self.env['rebate.settlement'].create({
            'agreement_id': self.agreement_id.id,
            'period_id': self.id,
            'is_adjustment': True,
            'origin_settlement_id': origin.id,
        })

    def action_recalc(self):
        for period in self:
            period._create_adjustment().action_compute()

    def action_view_lines(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('rebate_base.action_rebate_line')
        action['domain'] = [('period_id', 'child_of', self.id)]
        return action
