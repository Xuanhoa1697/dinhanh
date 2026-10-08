from collections import defaultdict

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

from ..tools import engine


class RebateSettlement(models.Model):
    _name = 'rebate.settlement'
    _description = 'Quyết toán chiết khấu cuối kỳ'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char('Số quyết toán', required=True, copy=False, readonly=True, default='/')
    agreement_id = fields.Many2one('rebate.agreement', string='Thỏa thuận', required=True, ondelete='restrict',
                                   index=True, tracking=True)
    period_id = fields.Many2one('rebate.period', string='Kỳ', required=True, ondelete='restrict', index=True,
                                domain="[('agreement_id', '=', agreement_id)]")
    direction = fields.Selection(related='agreement_id.direction', store=True)
    settlement_doc = fields.Selection(related='agreement_id.settlement_doc')
    payment_method = fields.Selection(related='agreement_id.payment_method')
    company_id = fields.Many2one(related='agreement_id.company_id', store=True)
    currency_id = fields.Many2one(related='agreement_id.currency_id', store=True)
    date_from = fields.Date(related='period_id.date_from', store=True)
    date_to = fields.Date(related='period_id.date_to', store=True)
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('computed', 'Đã tính'),
        ('to_approve', 'Chờ duyệt'),
        ('approved', 'Đã duyệt'),
        ('done', 'Đã lập chứng từ'),
        ('cancel', 'Hủy'),
    ], string='Trạng thái', default='draft', required=True, copy=False, tracking=True)
    is_adjustment = fields.Boolean('Quyết toán chênh lệch', readonly=True)
    origin_settlement_id = fields.Many2one('rebate.settlement', string='Quyết toán gốc', readonly=True)

    base_amount = fields.Monetary('Doanh số / giá trị lũy kế', readonly=True, currency_field='currency_id')
    gross_amount = fields.Monetary('CK theo bậc', readonly=True, currency_field='currency_id')
    condition_adjustment = fields.Monetary('Điều chỉnh do điều kiện', readonly=True, currency_field='currency_id')
    amount = fields.Monetary('CK của kỳ', readonly=True, currency_field='currency_id', tracking=True)
    prior_paid = fields.Monetary('Đã quyết toán trước', readonly=True, currency_field='currency_id')
    amount_to_settle = fields.Monetary('Số cần quyết toán', readonly=True, currency_field='currency_id',
                                       tracking=True)
    tax_amount = fields.Monetary('Thuế GTGT điều chỉnh', compute='_compute_tax_amount', store=True,
                                 currency_field='currency_id')
    condition_html = fields.Html('Kết quả điều kiện', readonly=True, sanitize=False)
    blocked = fields.Boolean('Bị treo do điều kiện', readonly=True)

    result_ids = fields.One2many('rebate.settlement.result', 'settlement_id', string='Kết quả theo quy tắc')
    detail_ids = fields.One2many('rebate.settlement.detail', 'settlement_id', string='Phân bổ')
    move_ids = fields.Many2many('account.move', 'rebate_settlement_move_rel', 'settlement_id', 'move_id',
                                string='Chứng từ', copy=False, readonly=True)
    move_count = fields.Integer(compute='_compute_move_count')
    carryforward_ids = fields.One2many('rebate.carryforward', 'settlement_id', string='Trừ kỳ sau')

    computed_date = fields.Datetime('Ngày tính', readonly=True, copy=False)
    computed_by_id = fields.Many2one('res.users', string='Người tính', readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', string='Người duyệt', readonly=True, copy=False)
    approved_date = fields.Datetime('Ngày duyệt', readonly=True, copy=False)
    partner_confirmed = fields.Boolean('Đối tác đã xác nhận', tracking=True)
    partner_confirmed_date = fields.Date('Ngày xác nhận')
    partner_confirmed_amount = fields.Monetary('Số đối tác xác nhận', currency_field='currency_id')
    doc_date = fields.Date('Ngày chứng từ', default=fields.Date.context_today)
    note = fields.Text('Ghi chú')

    _uniq_regular = models.UniqueIndex(
        "(agreement_id, period_id) WHERE state != 'cancel' AND is_adjustment IS NOT TRUE",
        "Kỳ này đã có quyết toán.",
    )

    @api.depends('detail_ids.allocated_tax')
    def _compute_tax_amount(self):
        for rec in self:
            rec.tax_amount = sum(rec.detail_ids.mapped('allocated_tax'))

    @api.depends('move_ids')
    def _compute_move_count(self):
        for rec in self:
            rec.move_count = len(rec.move_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('rebate.settlement') or '/'
        return super().create(vals_list)

    def unlink(self):
        if any(rec.state not in ('draft', 'computed', 'cancel') for rec in self):
            raise UserError(self.env._('Chỉ xóa được quyết toán chưa duyệt.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Evaluation (pure computation, no write) – used by progress & accrual
    # ------------------------------------------------------------------
    @api.model
    def _rebate_evaluate(self, agreement, period, lines):
        """Compute every rule of ``agreement`` on ``lines``.

        :return: dict(rules=[…], gross_amount, raw_alloc={line_id: amount})
        """
        all_rules = agreement.with_context(active_test=False).all_rule_ids.filtered('approved')
        lines_by_key = defaultdict(lambda: self.env['rebate.line'])
        for line in lines:
            lines_by_key[line.rule_key] |= line
        result = {'rules': [], 'gross_amount': 0.0, 'raw_alloc': defaultdict(float)}
        for key in sorted(lines_by_key, key=lambda k: min(lines_by_key[k].rule_id.mapped('sequence'))):
            key_lines = lines_by_key[key]
            versions = all_rules.filtered(lambda r, k=key: r.key == k).sorted('version')
            latest = versions[-1:] or key_lines.rule_id.sorted('version')[-1:]
            measure = key_lines._measure(latest)
            amount_base = key_lines._amount_base(latest)
            qty_base = key_lines._qty_base(latest)
            tiers = latest._engine_tiers()
            res = engine.compute_tier_amount(
                measure, amount_base, qty_base, tiers, latest.tier_mode, latest.value_type,
                latest.min_threshold, latest.cap_amount)
            used_rules = key_lines.rule_id
            segment_details = None
            if agreement.mid_period_change == 'segment' and len(used_rules) > 1:
                segments, tiers_by_seg = [], {}
                for rule in used_rules.sorted('version'):
                    seg_lines = key_lines.filtered(lambda ln, r=rule: ln.rule_id == r)
                    segments.append((rule.id, seg_lines._measure(latest), seg_lines._amount_base(latest),
                                     seg_lines._qty_base(latest)))
                    tiers_by_seg[rule.id] = rule._engine_tiers()
                total, segment_details = engine.segment_amount(
                    segments, measure, tiers_by_seg, latest.tier_mode, latest.value_type,
                    latest.min_threshold, latest.cap_amount)
                if not measure or measure < (latest.min_threshold or 0):
                    total = 0.0
                res.amount = total
            # raw allocation of this rule on its lines
            weight_field = 'quantity' if agreement.allocation_key == 'qty' else 'amount'
            if segment_details is not None:
                for rule_id, seg_amount in segment_details.items():
                    seg_lines = key_lines.filtered(lambda ln, r=rule_id: ln.rule_id.id == r)
                    self._raw_split(result['raw_alloc'], seg_lines, seg_amount, weight_field)
            else:
                self._raw_split(result['raw_alloc'], key_lines, res.amount, weight_field)
            tier_label = '–'
            if res.tier_index >= 0:
                tier = sorted(tiers, key=lambda t: t.from_value)[res.tier_index]
                tier_label = '≥ {:,.0f} → {:g}'.format(tier.from_value, tier.value)
            result['rules'].append({
                'key': key,
                'rule': latest,
                'measure': measure,
                'amount_base': amount_base,
                'qty_base': qty_base,
                'amount': res.amount,
                'tier_index': res.tier_index,
                'tier_value': res.tier_value,
                'tier_label': tier_label,
                'next_gap': res.next_tier_gap,
                'capped': res.capped,
                'segmented': segment_details is not None,
                'line_count': len(key_lines),
            })
            result['gross_amount'] += res.amount
        return result

    @api.model
    def _raw_split(self, raw_alloc, lines, amount, weight_field):
        if not lines or not amount:
            return
        weights = [line[weight_field] for line in lines]
        if not any(weights):
            weights = [1.0] * len(lines)
        wsum = sum(weights)
        if not wsum:
            return
        for line, w in zip(lines, weights):
            raw_alloc[line.id] += amount * w / wsum

    # hook for rebate_control (T29/T30)
    def _rebate_apply_conditions(self, lines, evaluation):
        """:return: dict(factor=1.0, bonus=0.0, blocked=False, messages=[(ok, text)])"""
        return {'factor': 1.0, 'bonus': 0.0, 'blocked': False, 'messages': []}

    def _prior_paid(self):
        self.ensure_one()
        periods = self.env['rebate.period'].search([('id', 'child_of', self.period_id.id)])
        done = self.search([
            ('period_id', 'in', periods.ids), ('state', '=', 'done'), ('id', '!=', self.id),
        ])
        return sum(done.mapped('amount_to_settle'))

    # ------------------------------------------------------------------
    # Compute (T17)
    # ------------------------------------------------------------------
    def action_compute(self):
        for rec in self:
            if rec.state not in ('draft', 'computed'):
                raise UserError(self.env._('Chỉ tính lại được quyết toán chưa trình duyệt.'))
            period = rec.period_id
            if period.state == 'open':
                period.action_lock()
            lines = period._get_all_lines()
            evaluation = self._rebate_evaluate(rec.agreement_id, period, lines)
            cond = rec._rebate_apply_conditions(lines, evaluation)
            currency = rec.currency_id
            gross = currency.round(evaluation['gross_amount'])
            amount = 0.0 if cond['blocked'] else currency.round(gross * cond['factor'] + cond['bonus'])
            prior = currency.round(rec._prior_paid())
            to_settle = currency.round(amount - prior)
            if to_settle < 0 and rec.agreement_id.negative_true_up == 'ignore':
                to_settle = 0.0

            # final allocation: scale raw allocations so that they sum to "to_settle"
            raw = evaluation['raw_alloc']
            if cond['bonus'] and not cond['blocked']:
                self._raw_split(raw, lines, cond['bonus'], 'amount')
            alloc_lines = lines.filtered(lambda ln: raw.get(ln.id))
            if not alloc_lines and to_settle:
                alloc_lines = lines
                raw = {ln.id: ln.amount for ln in lines}
            digits = currency.decimal_places
            allocated = engine.allocate(to_settle, [raw[ln.id] for ln in alloc_lines], digits)

            details = []
            for line, amt in zip(alloc_lines, allocated):
                if not amt:
                    continue
                details.append(Command.create({
                    'line_id': line.id,
                    'rule_id': line.rule_id.id,
                    'move_id': line.move_id.id,
                    'move_line_id': line.move_line_id.id,
                    'target_move_id': (line.target_move_id or line.move_id).id,
                    'partner_id': line.partner_id.id,
                    'product_id': line.product_id.id,
                    'tax_ids': [Command.set(line.tax_ids.ids)],
                    'tax_rate': line.tax_rate,
                    'base_amount': line.amount,
                    'quantity': line.quantity,
                    'allocated_amount': amt,
                    'allocated_tax': currency.round(amt * line.tax_rate / 100.0),
                }))
            results = [Command.create({
                'rule_id': r['rule'].id,
                'measure': r['measure'],
                'amount_base': r['amount_base'],
                'qty_base': r['qty_base'],
                'tier_label': r['tier_label'],
                'next_gap': r['next_gap'],
                'amount': r['amount'],
                'capped': r['capped'],
                'segmented': r['segmented'],
                'line_count': r['line_count'],
            }) for r in evaluation['rules']]
            cond_html = Markup('').join(
                Markup('<li>%s %s</li>') % ('✔' if ok else '✘', text) for ok, text in cond['messages'])
            rec.result_ids.unlink()
            rec.detail_ids.unlink()
            rec.write({
                'base_amount': sum(lines.mapped('amount')),
                'gross_amount': gross,
                'condition_adjustment': amount - gross,
                'amount': amount,
                'prior_paid': prior,
                'amount_to_settle': to_settle,
                'blocked': cond['blocked'],
                'condition_html': Markup('<ul>%s</ul>') % cond_html if cond['messages'] else False,
                'result_ids': results,
                'detail_ids': details,
                'state': 'computed',
                'computed_date': fields.Datetime.now(),
                'computed_by_id': self.env.user.id,
            })
            period.needs_recalc = False
        return True

    # ------------------------------------------------------------------
    # Approval (T18)
    # ------------------------------------------------------------------
    def action_submit(self):
        for rec in self:
            if rec.state != 'computed':
                raise UserError(self.env._('Hãy tính quyết toán trước khi trình duyệt.'))
            rec.state = 'to_approve'

    def _required_group(self):
        self.ensure_one()
        limit = self.company_id.rebate_approval_limit
        if limit and abs(self.amount_to_settle) > limit:
            return 'rebate_base.group_rebate_admin'
        return 'rebate_base.group_rebate_manager'

    def action_approve(self):
        for rec in self:
            if rec.state != 'to_approve':
                continue
            rec.agreement_id._check_approver(rec.computed_by_id)
            group = rec._required_group()
            if not self.env.su and not self.env.user.has_group(group):
                raise UserError(self.env._(
                    'Số tiền %s vượt hạn mức duyệt, cần nhóm Quản trị chiết khấu cuối kỳ.',
                    rec.currency_id.format(rec.amount_to_settle)))
            rec.write({'state': 'approved', 'approved_by_id': self.env.user.id,
                       'approved_date': fields.Datetime.now()})

    def action_reject(self):
        self.filtered(lambda r: r.state == 'to_approve').write({'state': 'computed'})

    def action_cancel(self):
        for rec in self:
            if rec.move_ids.filtered(lambda m: m.state == 'posted'):
                raise UserError(self.env._('Hãy hủy các chứng từ đã ghi sổ của %s trước.', rec.name))
            rec.state = 'cancel'
            if rec.period_id.state == 'settled' and not rec.period_id.settlement_ids.filtered(
                    lambda s: s.state == 'done'):
                rec.period_id.state = 'locked'

    def action_draft(self):
        self.filtered(lambda r: r.state in ('cancel', 'computed')).write({'state': 'draft'})

    # ------------------------------------------------------------------
    # Documents (T20+ in rebate_sale / rebate_purchase)
    # ------------------------------------------------------------------
    def action_generate_documents(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(self.env._('Quyết toán %s chưa được duyệt.', rec.name))
            rec.agreement_id._check_approver(False)
            moves = rec._rebate_generate_documents()
            rec.write({'move_ids': [Command.link(m.id) for m in moves], 'state': 'done'})
            rec.period_id.write({'state': 'settled', 'needs_recalc': False})
            rec._rebate_after_done()
        return True

    def _rebate_after_done(self):
        """Hook (accrual reversal, …)."""
        return True

    def _rebate_generate_documents(self):
        """Dispatch on agreement.settlement_doc; returns account.move recordset."""
        self.ensure_one()
        doc = self.agreement_id.settlement_doc
        if not self.amount_to_settle or doc == 'none':
            return self.env['account.move']
        if self.agreement_id.nature == 'support' or doc == 'voucher':
            return self._rebate_generate_voucher()
        if doc == 'next_invoice':
            return self._rebate_generate_carryforward()
        method = getattr(self, '_rebate_generate_%s_%s' % (self.direction, doc), None)
        if not method:
            raise UserError(self.env._(
                'Chưa cài module xử lý chứng từ "%(doc)s" cho chiều %(dir)s (rebate_sale / rebate_purchase).',
                doc=dict(self.agreement_id._fields['settlement_doc'].selection)[doc],
                dir=dict(self.agreement_id._fields['direction'].selection)[self.direction]))
        return method()

    def _rebate_group_details(self):
        """{(commercial partner, tax key): [details]} – one document line per tax set (RQ-14)."""
        self.ensure_one()
        groups = defaultdict(lambda: self.env['rebate.settlement.detail'])
        for det in self.detail_ids:
            partner = (det.target_move_id.commercial_partner_id or det.partner_id.commercial_partner_id)
            groups[(partner, tuple(sorted(det.tax_ids.ids)))] |= det
        return groups

    def _rebate_generate_carryforward(self):
        """T21 – keep the rebate as a balance deducted on the next invoices / bills."""
        self.ensure_one()
        if self.amount_to_settle < 0:
            raise UserError(self.env._('Không thể trừ kỳ sau một khoản thu hồi (số âm). '
                                       'Hãy chọn chứng từ là hóa đơn điều chỉnh.'))
        vals_list = []
        for (partner, _key), details in self._rebate_group_details().items():
            amount = self.currency_id.round(sum(details.mapped('allocated_amount')))
            if not amount:
                continue
            vals_list.append({
                'settlement_id': self.id,
                'partner_id': partner.id,
                'tax_ids': [Command.set(details[:1].tax_ids.ids)],
                'tax_rate': details[:1].tax_rate,
                'amount': amount,
            })
        self.env['rebate.carryforward'].create(vals_list)
        return self.env['account.move']

    def _rebate_generate_voucher(self):
        """Support / bonus not tied to goods: journal entry without VAT (Nợ 641 / Có 131, Nợ 331 / Có 711)."""
        self.ensure_one()
        company = self.company_id
        journal = company._rebate_journal('general')
        moves = self.env['account.move']
        by_partner = defaultdict(float)
        for det in self.detail_ids:
            by_partner[det.partner_id] += det.allocated_amount
        for partner, amount in by_partner.items():
            amount_company = self.currency_id._convert(amount, company.currency_id, company, self.doc_date)
            if self.direction == 'sale':
                expense = company._rebate_account('rebate_support_sale_account_id')
                counterpart = partner.with_company(company).property_account_receivable_id
                debit_acc, credit_acc = expense, counterpart
            else:
                income = company._rebate_account('rebate_support_purchase_account_id')
                counterpart = partner.with_company(company).property_account_payable_id
                debit_acc, credit_acc = counterpart, income
            if not debit_acc or not credit_acc:
                raise UserError(self.env._('Thiếu tài khoản hỗ trợ trong cấu hình chiết khấu cuối kỳ.'))
            sign = 1 if amount_company > 0 else -1
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': self.doc_date,
                'ref': '%s – %s' % (self.name, self.agreement_id.name),
                'rebate_settlement_id': self.id,
                'line_ids': [
                    Command.create({'name': self.name, 'account_id': debit_acc.id, 'partner_id': partner.id,
                                    'debit': abs(amount_company) if sign > 0 else 0.0,
                                    'credit': abs(amount_company) if sign < 0 else 0.0}),
                    Command.create({'name': self.name, 'account_id': credit_acc.id, 'partner_id': partner.id,
                                    'credit': abs(amount_company) if sign > 0 else 0.0,
                                    'debit': abs(amount_company) if sign < 0 else 0.0}),
                ],
            })
            move.action_post()
            moves |= move
        return moves

    # ------------------------------------------------------------------
    def action_view_moves(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_journal_line')
        action['domain'] = [('id', 'in', self.move_ids.ids)]
        action['context'] = {'create': False}
        if len(self.move_ids) == 1:
            action.update({'views': [(False, 'form')], 'res_id': self.move_ids.id})
        return action

    def action_print_statement(self):
        return self.env.ref('rebate_base.action_report_rebate_statement').report_action(self)

    def action_print_confirmation(self):
        return self.env.ref('rebate_base.action_report_rebate_confirmation').report_action(self)

    def action_export_xlsx(self):
        self.ensure_one()
        wizard = self.env['rebate.xlsx.export'].create({'settlement_id': self.id})
        return wizard.action_export()

    def _statement_rows(self):
        """Rows of the adjustment statement (bảng kê): one row per (invoice, tax rate)."""
        self.ensure_one()
        grouped = defaultdict(lambda: {'base': 0.0, 'amount': 0.0, 'tax': 0.0})
        details = self.detail_ids
        only_partner = self.env.context.get('rebate_partner_id')
        if only_partner:
            details = details.filtered(
                lambda d: (d.target_move_id.commercial_partner_id or d.partner_id.commercial_partner_id).id
                == only_partner)
        for det in details:
            key = (det.target_move_id, det.partner_id, det.tax_rate)
            grouped[key]['base'] += det.base_amount
            grouped[key]['amount'] += det.allocated_amount
            grouped[key]['tax'] += det.allocated_tax
        rows = []
        for (move, partner, rate), vals in sorted(
                grouped.items(), key=lambda kv: (kv[0][1].display_name or '', kv[0][0].invoice_date or fields.Date.today(),
                                                 kv[0][0].name or '')):
            rows.append({
                'move': move,
                'partner': partner,
                'number': move._rebate_invoice_number(),
                'date': move.invoice_date,
                'tax_rate': rate,
                'base': vals['base'],
                'amount': vals['amount'],
                'tax': vals['tax'],
            })
        return rows


class RebateSettlementResult(models.Model):
    _name = 'rebate.settlement.result'
    _description = 'Kết quả quyết toán theo quy tắc'
    _order = 'id'

    settlement_id = fields.Many2one('rebate.settlement', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='settlement_id.currency_id')
    rule_id = fields.Many2one('rebate.rule', string='Quy tắc', ondelete='set null')
    measure = fields.Float('Đã đạt', digits=(16, 2))
    amount_base = fields.Monetary('Giá trị', currency_field='currency_id')
    qty_base = fields.Float('Số lượng', digits=(16, 2))
    tier_label = fields.Char('Bậc đạt')
    next_gap = fields.Float('Còn thiếu lên bậc', digits=(16, 2))
    amount = fields.Monetary('CK theo bậc', currency_field='currency_id')
    capped = fields.Boolean('Chạm trần')
    segmented = fields.Boolean('Tính theo đoạn')
    line_count = fields.Integer('Số dòng')


class RebateSettlementDetail(models.Model):
    _name = 'rebate.settlement.detail'
    _description = 'Phân bổ quyết toán về hóa đơn'
    _order = 'partner_id, target_move_id, id'

    settlement_id = fields.Many2one('rebate.settlement', required=True, ondelete='cascade', index=True)
    agreement_id = fields.Many2one(related='settlement_id.agreement_id', store=True)
    direction = fields.Selection(related='settlement_id.direction', store=True)
    state = fields.Selection(related='settlement_id.state', store=True)
    company_id = fields.Many2one(related='settlement_id.company_id', store=True)
    currency_id = fields.Many2one(related='settlement_id.currency_id', store=True)
    period_id = fields.Many2one(related='settlement_id.period_id', store=True)
    line_id = fields.Many2one('rebate.line', string='Dòng lũy kế', ondelete='set null')
    rule_id = fields.Many2one('rebate.rule', string='Quy tắc', ondelete='set null')
    move_id = fields.Many2one('account.move', string='Hóa đơn nguồn', ondelete='set null')
    move_line_id = fields.Many2one('account.move.line', string='Dòng hóa đơn', ondelete='set null')
    target_move_id = fields.Many2one('account.move', string='Hóa đơn được điều chỉnh', ondelete='set null')
    partner_id = fields.Many2one('res.partner', string='Đối tác')
    product_id = fields.Many2one('product.product', string='Sản phẩm')
    tax_ids = fields.Many2many('account.tax', 'rebate_detail_tax_rel', 'detail_id', 'tax_id', string='Thuế')
    tax_rate = fields.Float('Thuế suất (%)', digits=(5, 2))
    base_amount = fields.Monetary('Giá trị hóa đơn', currency_field='currency_id')
    quantity = fields.Float('Số lượng', digits='Product Unit')
    allocated_amount = fields.Monetary('CK phân bổ', currency_field='currency_id')
    allocated_tax = fields.Monetary('Thuế điều chỉnh', currency_field='currency_id')
