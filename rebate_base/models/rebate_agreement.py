from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from . import selections as sel

LOCKED_FIELDS = {
    'direction', 'nature', 'partner_ids', 'partner_category_ids', 'date_from', 'date_to',
    'currency_id', 'company_id', 'period_type', 'stacking', 'priority', 'return_period_rule',
}


def _period_ranges(date_from, date_to, months):
    """Calendar-anchored blocks of ``months`` months, clipped to [date_from, date_to]."""
    start = date(date_from.year, ((date_from.month - 1) // months) * months + 1, 1)
    while start <= date_to:
        end = start + relativedelta(months=months) - timedelta(days=1)
        yield max(start, date_from), min(end, date_to), start
        start = end + timedelta(days=1)


def _period_name(start, months, dfrom, dto):
    if months == 1:
        return start.strftime('T%m/%Y')
    if months == 3:
        return 'Q%s/%s' % ((start.month - 1) // 3 + 1, start.year)
    if months == 6:
        return 'H%s/%s' % ((start.month - 1) // 6 + 1, start.year)
    if months == 12:
        return str(start.year)
    return '%s – %s' % (dfrom.strftime('%d/%m/%Y'), dto.strftime('%d/%m/%Y'))


class RebateAgreement(models.Model):
    _name = 'rebate.agreement'
    _description = 'Thỏa thuận chiết khấu cuối kỳ'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, id desc'
    _check_company_auto = True

    name = fields.Char('Số thỏa thuận', required=True, copy=False, readonly=True, default='/', tracking=True)
    title = fields.Char('Tên chương trình', required=True, tracking=True)
    direction = fields.Selection(sel.DIRECTION, string='Chiều', required=True, default='sale', tracking=True)
    nature = fields.Selection(sel.NATURE, string='Bản chất', required=True, default='trade', tracking=True)
    template_id = fields.Many2one('rebate.template', string='Mẫu')
    partner_ids = fields.Many2many('res.partner', 'rebate_agreement_partner_rel', 'agreement_id', 'partner_id',
                                   string='Đối tác', tracking=True)
    partner_category_ids = fields.Many2many(
        'res.partner.category', 'rebate_agreement_partner_category_rel', 'agreement_id', 'category_id',
        string='Nhóm đối tác (thẻ)',
        help='Mọi đối tác mang một trong các thẻ này đều thuộc thỏa thuận (danh mục động).')
    contract_ref = fields.Char('Số hợp đồng / phụ lục', tracking=True)
    date_from = fields.Date('Hiệu lực từ', required=True, tracking=True)
    date_to = fields.Date('Hiệu lực đến', required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Công ty', required=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='Tiền tệ', required=True,
                                  default=lambda self: self.env.company.currency_id)
    user_id = fields.Many2one('res.users', string='Người phụ trách', default=lambda self: self.env.user,
                              tracking=True)
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('to_approve', 'Chờ duyệt'),
        ('active', 'Hiệu lực'),
        ('revision', 'Đang sửa đổi'),
        ('closed', 'Đã đóng'),
        ('cancel', 'Hủy'),
    ], string='Trạng thái', default='draft', required=True, copy=False, tracking=True)
    is_revision = fields.Boolean(copy=False, help='Đang chờ duyệt một phiên bản sửa đổi.')
    version = fields.Integer('Phiên bản', default=1, copy=False, readonly=True, tracking=True)
    submitted_by_id = fields.Many2one('res.users', string='Người trình', copy=False, readonly=True)
    approved_by_id = fields.Many2one('res.users', string='Người duyệt', copy=False, readonly=True)
    approved_date = fields.Datetime('Ngày duyệt', copy=False, readonly=True)

    # configuration tier 3
    period_type = fields.Selection(sel.PERIOD_TYPE, string='Kỳ tính', required=True, default='quarter')
    settlement_doc = fields.Selection(sel.SETTLEMENT_DOC, string='Chứng từ quyết toán', required=True,
                                      default='adjust_invoice', tracking=True)
    payment_method = fields.Selection(sel.PAYMENT_METHOD, string='Hình thức chi trả', required=True,
                                      default='offset', tracking=True)
    allocation_key = fields.Selection(sel.ALLOCATION_KEY, string='Phân bổ về hóa đơn', required=True,
                                      default='amount')
    cogs_split = fields.Selection(sel.COGS_SPLIT, string='Phân bổ giá vốn (mua)', required=True,
                                  default='method')
    return_period_rule = fields.Selection(sel.RETURN_PERIOD_RULE, string='Trả hàng tính vào kỳ',
                                          required=True, default='origin')
    post_close_recalc = fields.Selection(sel.POST_CLOSE_RECALC, string='Phát sinh sau khi chốt',
                                         required=True, default='recalc')
    negative_true_up = fields.Selection(sel.NEGATIVE_TRUE_UP, string='Quyết toán năm âm', required=True,
                                        default='ignore')
    mid_period_change = fields.Selection(sel.MID_PERIOD_CHANGE, string='Sửa đổi giữa kỳ', required=True,
                                         default='segment')
    stacking = fields.Selection(sel.STACKING, string='Chồng chương trình', required=True, default='cumulative')
    priority = fields.Integer('Ưu tiên', default=10, help='Số nhỏ được xét trước khi có nhiều thỏa thuận cùng khớp.')

    rule_ids = fields.One2many('rebate.rule', 'agreement_id', string='Quy tắc hiện hành',
                               domain=[('is_current', '=', True)])
    pending_rule_ids = fields.One2many('rebate.rule', 'agreement_id', string='Quy tắc phiên bản mới',
                                       domain=[('is_current', '=', False), ('approved', '=', False)])
    all_rule_ids = fields.One2many('rebate.rule', 'agreement_id', string='Lịch sử quy tắc',
                                   context={'active_test': False})
    period_ids = fields.One2many('rebate.period', 'agreement_id', string='Kỳ')
    line_ids = fields.One2many('rebate.line', 'agreement_id', string='Dòng lũy kế')
    settlement_ids = fields.One2many('rebate.settlement', 'agreement_id', string='Quyết toán')
    line_count = fields.Integer(compute='_compute_counts')
    settlement_count = fields.Integer(compute='_compute_counts')
    period_count = fields.Integer(compute='_compute_counts')
    note = fields.Html('Ghi chú')

    # ------------------------------------------------------------------
    @api.depends('line_ids', 'settlement_ids', 'period_ids')
    def _compute_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.settlement_count = len(rec.settlement_ids)
            rec.period_count = len(rec.period_ids)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_to < rec.date_from:
                raise ValidationError(self.env._('Ngày kết thúc phải sau ngày bắt đầu.'))

    @api.onchange('template_id')
    def _onchange_template_id(self):
        tmpl = self.template_id
        if not tmpl:
            return
        for fname in sel.TEMPLATE_FIELDS:
            self[fname] = tmpl[fname]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('template_id'):
                tmpl = self.env['rebate.template'].browse(vals['template_id'])
                for fname in sel.TEMPLATE_FIELDS:
                    vals.setdefault(fname, tmpl[fname])
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('rebate.agreement') or '/'
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('rebate_force'):
            locked = LOCKED_FIELDS.intersection(vals)
            if locked and any(rec.state not in ('draft',) for rec in self):
                raise UserError(self.env._(
                    'Thỏa thuận đã duyệt không sửa được các trường: %s. Hãy tạo phiên bản mới.',
                    ', '.join(sorted(self._fields[f].string for f in locked))))
        return super().write(vals)

    def unlink(self):
        if any(rec.state not in ('draft', 'cancel') for rec in self):
            raise UserError(self.env._('Chỉ xóa được thỏa thuận ở trạng thái Nháp hoặc Hủy.'))
        return super().unlink()

    @api.depends('name', 'title')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s – %s' % (rec.name, rec.title) if rec.title else rec.name

    # ------------------------------------------------------------------
    # Partner matching
    # ------------------------------------------------------------------
    def _matches_partner(self, partner):
        self.ensure_one()
        commercial = partner.commercial_partner_id
        if commercial in self.partner_ids.commercial_partner_id:
            return True
        if self.partner_category_ids and (
                (partner.category_id | commercial.category_id) & self.partner_category_ids):
            return True
        return False

    # ------------------------------------------------------------------
    # Workflow (T06)
    # ------------------------------------------------------------------
    def _check_ready(self):
        for rec in self:
            rules = rec.pending_rule_ids if rec.state == 'revision' else rec.rule_ids
            if not rules:
                raise UserError(self.env._('Thỏa thuận %s chưa có quy tắc.', rec.display_name))
            if not rec.partner_ids and not rec.partner_category_ids:
                raise UserError(self.env._('Thỏa thuận %s chưa có đối tác hoặc nhóm đối tác.', rec.display_name))
            for rule in rules:
                if not rule.tier_ids:
                    raise UserError(self.env._('Quy tắc "%s" chưa có bậc.', rule.name))

    def action_submit(self):
        for rec in self:
            if rec.state not in ('draft', 'revision'):
                continue
            rec._check_ready()
            rec.with_context(rebate_force=True).write({
                'is_revision': rec.state == 'revision',
                'state': 'to_approve',
                'submitted_by_id': self.env.user.id,
            })

    def _check_approver(self, requester):
        """Approval rights + segregation of duties (RQ-15, D15)."""
        user = self.env.user
        if self.env.su:
            return
        if not user.has_group('rebate_base.group_rebate_manager'):
            raise AccessError(self.env._('Bạn không có quyền duyệt chiết khấu cuối kỳ.'))
        if self.company_id.rebate_segregation and requester and requester == user:
            raise UserError(self.env._('Người lập / người trình không được tự duyệt.'))

    def action_approve(self):
        for rec in self.filtered(lambda r: r.state == 'to_approve'):
            rec._check_approver(rec.submitted_by_id or rec.create_uid)
            if rec.is_revision:
                rec._approve_revision()
            else:
                rec.rule_ids.with_context(rebate_force=True).write({
                    'approved': True, 'date_start': rec.date_from, 'version': 1,
                })
                if not rec.period_ids:
                    rec._generate_periods()
                rec.with_context(rebate_force=True).write({'state': 'active'})
                rec.action_rebuild_lines()
            rec.with_context(rebate_force=True).write({
                'approved_by_id': self.env.user.id,
                'approved_date': fields.Datetime.now(),
                'is_revision': False,
            })
        return True

    def action_reject(self):
        for rec in self.filtered(lambda r: r.state == 'to_approve'):
            rec.with_context(rebate_force=True).write({'state': 'revision' if rec.is_revision else 'draft'})

    def action_draft(self):
        for rec in self:
            if rec.state != 'cancel':
                raise UserError(self.env._('Chỉ đưa về Nháp được thỏa thuận đã hủy.'))
            if rec.settlement_ids.filtered(lambda s: s.state == 'done'):
                raise UserError(self.env._('Thỏa thuận đã có quyết toán, không đưa về Nháp được.'))
            rec.line_ids.unlink()
            rec.period_ids.filtered(lambda p: not p.settlement_ids).unlink()
            rec.rule_ids.with_context(rebate_force=True).write({'approved': False})
            rec.with_context(rebate_force=True).write({'state': 'draft'})

    def action_cancel(self):
        for rec in self:
            if rec.settlement_ids.filtered(lambda s: s.state == 'done'):
                raise UserError(self.env._('Thỏa thuận đã có quyết toán, hãy Đóng thay vì Hủy.'))
            rec.with_context(rebate_force=True).write({'state': 'cancel'})

    def action_close(self):
        self.with_context(rebate_force=True).write({'state': 'closed'})

    def action_cancel_revision(self):
        for rec in self.filtered(lambda r: r.state == 'revision'):
            rec.pending_rule_ids.with_context(rebate_force=True).unlink()
            rec.with_context(rebate_force=True).write({'state': 'active'})

    # ------------------------------------------------------------------
    # Versioning (T07)
    # ------------------------------------------------------------------
    def action_open_version_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Tạo phiên bản mới'),
            'res_model': 'rebate.version.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_agreement_id': self.id},
        }

    def _start_revision(self, date_start):
        self.ensure_one()
        if self.state != 'active':
            raise UserError(self.env._('Chỉ tạo phiên bản mới cho thỏa thuận đang hiệu lực.'))
        if not (self.date_from <= date_start <= self.date_to):
            raise UserError(self.env._('Ngày áp dụng phải nằm trong thời hạn thỏa thuận.'))
        for rule in self.rule_ids:
            rule.copy({
                'agreement_id': self.id,
                'key': rule.key,
                'version': self.version + 1,
                'date_start': date_start,
                'date_end': False,
                'approved': False,
                'is_current': False,
            })
        self.with_context(rebate_force=True).write({'state': 'revision'})

    def _approve_revision(self):
        self.ensure_one()
        new_rules = self.pending_rule_ids
        date_start = min(new_rules.mapped('date_start'))
        old_rules = self.rule_ids
        for rule in old_rules:
            end = date_start - timedelta(days=1)
            rule.with_context(rebate_force=True).write({
                'date_end': end if (not rule.date_end or rule.date_end > end) else rule.date_end,
                'is_current': False,
            })
        new_rules.with_context(rebate_force=True).write({'approved': True, 'is_current': True})
        self.with_context(rebate_force=True).write({'state': 'active', 'version': self.version + 1})
        self.message_post(body=self.env._('Phiên bản %(v)s có hiệu lực từ %(d)s.',
                                          v=self.version, d=date_start.strftime('%d/%m/%Y')))
        self.action_rebuild_lines(date_from=date_start)

    # ------------------------------------------------------------------
    # Periods (T05)
    # ------------------------------------------------------------------
    def _period_layout(self):
        """Return [(parent_vals, [child_vals…])]."""
        self.ensure_one()
        ptype = self.period_type
        months = {'month': 1, 'quarter': 3, 'half': 6, 'year': 12}.get(ptype)
        result = []
        if ptype == 'whole':
            result.append(({'date_from': self.date_from, 'date_to': self.date_to,
                            'name': _period_name(self.date_from, 0, self.date_from, self.date_to)}, []))
        elif months:
            for dfrom, dto, start in _period_ranges(self.date_from, self.date_to, months):
                result.append(({'date_from': dfrom, 'date_to': dto,
                                'name': _period_name(start, months, dfrom, dto)}, []))
        else:
            child_months = 3 if ptype == 'year_quarter' else 1
            for dfrom, dto, start in _period_ranges(self.date_from, self.date_to, 12):
                children = [{'date_from': cf, 'date_to': ct, 'name': _period_name(cs, child_months, cf, ct)}
                            for cf, ct, cs in _period_ranges(dfrom, dto, child_months)]
                result.append(({'date_from': dfrom, 'date_to': dto,
                                'name': _period_name(start, 12, dfrom, dto)}, children))
        return result

    def _generate_periods(self):
        Period = self.env['rebate.period']
        for rec in self:
            for parent_vals, children in rec._period_layout():
                parent = Period.create(dict(parent_vals, agreement_id=rec.id))
                for child_vals in children:
                    Period.create(dict(child_vals, agreement_id=rec.id, parent_id=parent.id))

    def action_generate_periods(self):
        for rec in self:
            if rec.period_ids:
                raise UserError(self.env._('Thỏa thuận %s đã có kỳ.', rec.display_name))
        self._generate_periods()

    def _leaf_period(self, on_date):
        self.ensure_one()
        return self.period_ids.filtered(
            lambda p: not p.child_ids and p.date_from <= on_date <= p.date_to)[:1]

    # ------------------------------------------------------------------
    # Accumulation rebuild (T12)
    # ------------------------------------------------------------------
    def action_rebuild_lines(self, date_from=None):
        """Re-scan posted invoices and rebuild the accumulation lines of open periods."""
        for rec in self.filtered(lambda r: r.state in ('active', 'revision', 'to_approve')):
            self.env['account.move']._rebate_rebuild(rec, date_from=date_from)
        return True

    # ------------------------------------------------------------------
    # Smart buttons (T13)
    # ------------------------------------------------------------------
    def action_view_lines(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('rebate_base.action_rebate_line')
        action['domain'] = [('agreement_id', '=', self.id)]
        action['context'] = {'search_default_group_period': 1}
        return action

    def action_view_settlements(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('rebate_base.action_rebate_settlement')
        action['domain'] = [('agreement_id', '=', self.id)]
        action['context'] = {'default_agreement_id': self.id}
        return action

    def action_view_periods(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('rebate_base.action_rebate_period')
        action['domain'] = [('agreement_id', '=', self.id)]
        return action
