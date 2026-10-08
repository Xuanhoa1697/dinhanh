from collections import defaultdict

from odoo import api, fields, models

SALE_TYPES = ('out_invoice', 'out_refund')
PURCHASE_TYPES = ('in_invoice', 'in_refund')


class AccountMove(models.Model):
    _inherit = 'account.move'

    rebate_settlement_id = fields.Many2one('rebate.settlement', string='Quyết toán CK cuối kỳ', copy=False,
                                           index='btree_not_null', readonly=True)
    rebate_line_ids = fields.One2many('rebate.line', 'move_id', string='Dòng lũy kế CK')
    rebate_line_count = fields.Integer(compute='_compute_rebate_line_count')

    def _compute_rebate_line_count(self):
        data = dict(self.env['rebate.line']._read_group(
            [('move_id', 'in', self.ids)], ['move_id'], ['__count']))
        for move in self:
            move.rebate_line_count = data.get(move, 0)

    def _rebate_invoice_number(self):
        """Number printed on statements: e-invoice number when available."""
        self.ensure_one()
        number = self['l10n_vn_edi_invoice_number'] if 'l10n_vn_edi_invoice_number' in self._fields else False
        if number:
            return number
        if self.is_purchase_document(include_receipts=False):
            return self.ref or self.name
        return self.name

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------
    def _post(self, soft=True):
        posted = super()._post(soft)
        posted._rebate_sync_lines()
        return posted

    def button_draft(self):
        self._rebate_remove_lines()
        return super().button_draft()

    # ------------------------------------------------------------------
    # Accumulation (T09/T10)
    # ------------------------------------------------------------------
    def _rebate_remove_lines(self, agreements=None):
        domain = [('move_id', 'in', self.ids)]
        if agreements is not None:
            domain.append(('agreement_id', 'in', agreements.ids))
        lines = self.env['rebate.line'].sudo().search(domain)
        lines.period_id.filtered(lambda p: p.state != 'open').write({'needs_recalc': True})
        lines.unlink()

    def _rebate_candidate_agreements(self, agreements=None):
        moves = self.filtered(lambda m: m.move_type in SALE_TYPES + PURCHASE_TYPES)
        if not moves:
            return self.env['rebate.agreement']
        if agreements is not None:
            return agreements.sudo()
        dates = [d for m in moves for d in (m.invoice_date or m.date, m.reversed_entry_id.invoice_date) if d]
        return self.env['rebate.agreement'].sudo().search([
            ('state', 'in', ('active', 'revision', 'to_approve')),
            ('rule_ids.approved', '=', True),
            ('company_id', 'in', moves.company_id.ids),
            ('date_from', '<=', max(dates)),
            ('date_to', '>=', min(dates)),
        ], order='priority, id')

    def _rebate_sync_lines(self, agreements=None):
        """(Re)create accumulation lines of the posted invoices in ``self``.

        Idempotent: existing lines of these invoices (for the given agreements)
        are deleted first.
        """
        moves = self.filtered(lambda m: m.state == 'posted' and m.move_type in SALE_TYPES + PURCHASE_TYPES
                              and not m.rebate_settlement_id)
        candidates = moves._rebate_candidate_agreements(agreements)
        self._rebate_remove_lines(agreements=candidates if agreements is not None else None)
        if not candidates or not moves:
            return
        vals_list = []
        for move in moves.sudo():
            direction = 'sale' if move.move_type in SALE_TYPES else 'purchase'
            move_agreements = candidates.filtered(
                lambda a, m=move, d=direction: a.direction == d and a.company_id == m.company_id
                and a._matches_partner(m.partner_id))
            if not move_agreements:
                continue
            rebate_product = move.company_id._rebate_product()
            for line in move.invoice_line_ids.filtered(
                    lambda ln: ln.display_type == 'product' and not ln.rebate_settlement_id
                    and (not ln.product_id or ln.product_id != rebate_product)):
                for agreement, rule, period, line_date in move._rebate_match_line(line, move_agreements):
                    vals_list.append(move._rebate_prepare_line_vals(line, agreement, rule, period, line_date))
        if vals_list:
            self.env['rebate.line'].sudo().create(vals_list)

    def _rebate_line_date(self, agreement):
        self.ensure_one()
        own_date = self.invoice_date or self.date
        if self.move_type in ('out_refund', 'in_refund') and agreement.return_period_rule == 'origin' \
                and self.reversed_entry_id:
            return self.reversed_entry_id.invoice_date or self.reversed_entry_id.date or own_date
        return own_date

    def _rebate_match_line(self, line, agreements):
        """T09/T35 – yields (agreement, rule, period, date) for one invoice line.

        Agreements are visited by priority; an *exclusive* agreement that matches
        stops the lower-priority ones (stacking).
        """
        self.ensure_one()
        for agreement in agreements.sorted(lambda a: (a.priority, a.id)):
            line_date = self._rebate_line_date(agreement)
            if not (agreement.date_from <= line_date <= agreement.date_to):
                continue
            rules = agreement.with_context(active_test=False).all_rule_ids.filtered(
                lambda r, d=line_date: r.active and r._applies_on(d)).sorted(lambda r: (r.sequence, r.id))
            rule = next((r for r in rules if r._matches_product(line.product_id)), None)
            if not rule:
                continue
            period = agreement._leaf_period(line_date)
            if not period:
                continue
            if period.state == 'settled':
                if agreement.post_close_recalc == 'lock':
                    own_date = self.invoice_date or self.date
                    period = agreement._leaf_period(own_date)
                    if not period or period.state == 'settled':
                        continue
                    line_date = own_date
                else:
                    period.needs_recalc = True
            elif period.state == 'locked':
                period.needs_recalc = True
            yield agreement, rule, period, line_date
            if agreement.stacking == 'exclusive':
                break

    def _rebate_prepare_line_vals(self, line, agreement, rule, period, line_date):
        self.ensure_one()
        sign = -1 if self.move_type in ('out_refund', 'in_refund') else 1
        product = line.product_id
        qty = line.quantity
        if product and line.product_uom_id and line.product_uom_id != product.uom_id:
            qty = line.product_uom_id._compute_quantity(qty, product.uom_id, round=False, raise_if_failure=False)
        currency = line.currency_id or self.currency_id
        amount = line.price_subtotal
        if line.discount and line.discount < 100:
            gross = amount / (1 - line.discount / 100.0)
        else:
            gross = line.price_unit * line.quantity if line.discount >= 100 else amount
        if currency != agreement.currency_id:
            conv_date = self.invoice_date or self.date
            amount = currency._convert(amount, agreement.currency_id, self.company_id, conv_date)
            gross = currency._convert(gross, agreement.currency_id, self.company_id, conv_date)
        taxes = line.tax_ids
        target = self.reversed_entry_id if sign < 0 and self.reversed_entry_id else self
        return {
            'agreement_id': agreement.id,
            'period_id': period.id,
            'rule_id': rule.id,
            'company_id': self.company_id.id,
            'move_id': self.id,
            'move_line_id': line.id,
            'target_move_id': target.id,
            'partner_id': self.partner_id.id,
            'product_id': product.id,
            'date': line_date,
            'is_refund': sign < 0,
            'quantity': sign * qty,
            'weight': sign * qty * (product.weight or 0.0),
            'amount': sign * amount,
            'amount_gross': sign * gross,
            'tax_ids': [(6, 0, taxes.ids)],
            'tax_rate': sum(t.amount for t in taxes if t.amount_type == 'percent'),
        }

    @api.model
    def _rebate_rebuild(self, agreement, date_from=None):
        """T12 – rebuild the accumulation of one agreement from posted invoices."""
        agreement = agreement.sudo()
        types = SALE_TYPES if agreement.direction == 'sale' else PURCHASE_TYPES
        start = date_from or agreement.date_from
        domain = [
            ('state', '=', 'posted'),
            ('move_type', 'in', types),
            ('company_id', '=', agreement.company_id.id),
            '|',
            '&', ('invoice_date', '>=', start), ('invoice_date', '<=', agreement.date_to),
            '&', ('reversed_entry_id.invoice_date', '>=', start),
            ('reversed_entry_id.invoice_date', '<=', agreement.date_to),
        ]
        if agreement.partner_ids and not agreement.partner_category_ids:
            domain.append(('commercial_partner_id', 'in', agreement.partner_ids.commercial_partner_id.ids))
        moves = self.sudo().search(domain, order='id')
        # keep lines of settled periods untouched (they belong to a done settlement)
        settled = agreement.period_ids.filtered(lambda p: p.state == 'settled')
        for batch_start in range(0, len(moves), 500):
            batch = moves[batch_start:batch_start + 500]
            existing = self.env['rebate.line'].sudo().search([
                ('move_id', 'in', batch.ids), ('agreement_id', '=', agreement.id),
                ('period_id', 'in', settled.ids)])
            batch_to_sync = batch - existing.move_id
            batch_to_sync._rebate_sync_lines(agreements=agreement)
        return len(moves)

    def action_view_rebate_lines(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('rebate_base.action_rebate_line')
        action['domain'] = [('move_id', '=', self.id)]
        return action


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    rebate_settlement_id = fields.Many2one('rebate.settlement', string='Quyết toán CK cuối kỳ', copy=False,
                                           index='btree_not_null')
