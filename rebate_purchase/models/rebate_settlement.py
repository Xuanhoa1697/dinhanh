from collections import defaultdict

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

from odoo.addons.rebate_base.tools import engine


class RebateSettlement(models.Model):
    _inherit = 'rebate.settlement'

    purchase_alloc_ids = fields.One2many('rebate.purchase.alloc', 'settlement_id', string='Phân bổ giá vốn')
    claim_ids = fields.One2many('rebate.claim', 'settlement_id', string='Khiếu nại')
    vendor_received_amount = fields.Monetary('NCC đã chấp nhận', compute='_compute_vendor_received', store=True,
                                             currency_field='currency_id')
    vendor_pending = fields.Boolean('Chờ chứng từ NCC', compute='_compute_vendor_received', store=True)
    cogs_preview_html = fields.Html('Phân bổ giá vốn dự kiến', compute='_compute_cogs_preview', sanitize=False)

    @api.depends('move_ids.state', 'move_ids.amount_untaxed', 'carryforward_ids.amount_used', 'state')
    def _compute_vendor_received(self):
        for rec in self:
            if rec.direction != 'purchase':
                rec.vendor_received_amount = 0.0
                rec.vendor_pending = False
                continue
            received = sum(rec.move_ids.filtered(lambda m: m.state == 'posted').mapped(
                lambda m: m.amount_untaxed if m.move_type == 'in_refund' else -m.amount_untaxed))
            received += sum(rec.carryforward_ids.mapped('amount_used'))
            rec.vendor_received_amount = received
            rec.vendor_pending = rec.state == 'done' and rec.currency_id.compare_amounts(
                received, rec.amount_to_settle) != 0 and not rec.claim_ids.filtered(lambda c: c.state == 'open')

    # ------------------------------------------------------------------
    # T26 – preview
    # ------------------------------------------------------------------
    def _rebate_inventory_situation(self, detail):
        """(stock moves, qty_in, qty_remaining) of the receipts behind one bill line."""
        aml = detail.move_line_id
        moves = self.env['stock.move']
        if aml and detail.product_id.is_storable:
            moves = aml._get_stock_moves().filtered(lambda m: m.state == 'done' and m.is_in)
        qty_in = sum(m._get_valued_qty() for m in moves)
        qty_remaining = sum(max(m.remaining_qty, 0.0) for m in moves)
        return moves, qty_in, qty_remaining

    def _compute_cogs_preview(self):
        for rec in self:
            if rec.direction != 'purchase' or not rec.detail_ids:
                rec.cogs_preview_html = False
                continue
            rows = []
            tot = defaultdict(float)
            for det in rec.detail_ids:
                _moves, qty_in, qty_rem = rec._rebate_inventory_situation(det)
                if rec.agreement_id.cogs_split == 'all_cogs':
                    split = {'to_inventory': 0.0, 'to_cogs': det.allocated_amount}
                else:
                    split = engine.split_inventory(det.allocated_amount, qty_in, qty_rem,
                                                   digits=rec.currency_id.decimal_places)
                tot['inv'] += split['to_inventory']
                tot['cogs'] += split['to_cogs']
                rows.append(Markup('<tr><td>%s</td><td class="text-end">%s</td><td class="text-end">%s</td>'
                                   '<td class="text-end">%s</td><td class="text-end">%s</td>'
                                   '<td class="text-end">%s</td></tr>') % (
                    det.product_id.display_name or det.move_line_id.name or '', '{:,.2f}'.format(qty_in),
                    '{:,.2f}'.format(qty_rem), rec.currency_id.format(det.allocated_amount),
                    rec.currency_id.format(split['to_inventory']), rec.currency_id.format(split['to_cogs'])))
            rec.cogs_preview_html = Markup(
                '<table class="table table-sm"><thead><tr><th>Sản phẩm</th><th class="text-end">SL nhập</th>'
                '<th class="text-end">SL còn tồn</th><th class="text-end">CK</th><th class="text-end">Vào tồn kho</th>'
                '<th class="text-end">Vào giá vốn</th></tr></thead><tbody>%s</tbody><tfoot><tr class="fw-bold">'
                '<td colspan="4">Tổng</td><td class="text-end">%s</td><td class="text-end">%s</td></tr></tfoot>'
                '</table>') % (Markup('').join(rows), rec.currency_id.format(tot['inv']),
                               rec.currency_id.format(tot['cogs']))

    # ------------------------------------------------------------------
    # T24 – expected vendor documents
    # ------------------------------------------------------------------
    def _rebate_generate_purchase_adjust_invoice(self):
        return self._rebate_create_purchase_documents()

    def _rebate_generate_purchase_credit_note(self):
        return self._rebate_create_purchase_documents()

    def _rebate_create_purchase_documents(self):
        """Draft vendor credit notes with the amounts we expect. The accountant
        matches them with the vendor's e-invoice (number, amounts) then posts."""
        self.ensure_one()
        company = self.company_id
        account = company._rebate_account('rebate_purchase_clearing_account_id')
        if not account:
            raise UserError(self.env._('Chưa cấu hình tài khoản trung gian chiết khấu mua.'))
        product = company._rebate_product()
        by_partner = defaultdict(list)
        for (partner, _key), details in self._rebate_group_details().items():
            by_partner[partner].append((details[:1].tax_ids, self.currency_id.round(
                sum(details.mapped('allocated_amount')))))
        moves = self.env['account.move']
        label = self.env._('Chiết khấu thương mại kỳ %(period)s theo thỏa thuận %(agr)s',
                           period=self.period_id.name, agr=self.agreement_id.name)
        for partner, groups in by_partner.items():
            total = sum(a for _t, a in groups)
            if not total:
                continue
            sign = 1 if total > 0 else -1
            moves |= self.env['account.move'].create({
                'move_type': 'in_refund' if total > 0 else 'in_invoice',
                'partner_id': partner.id,
                'currency_id': self.currency_id.id,
                'invoice_date': self.doc_date,
                'date': self.doc_date,
                'journal_id': company._rebate_journal('purchase').id,
                'rebate_settlement_id': self.id,
                'narration': label,
                'invoice_line_ids': [Command.create({
                    'product_id': product.id,
                    'name': label,
                    'quantity': 1,
                    'price_unit': sign * amount,
                    'tax_ids': [Command.set(taxes.ids)],
                    'account_id': account.id,
                    'rebate_settlement_id': self.id,
                }) for taxes, amount in groups if amount],
            })
        return moves

    def _rebate_expected_for(self, partner):
        self.ensure_one()
        return sum(d.allocated_amount for d in self.detail_ids
                   if (d.target_move_id.commercial_partner_id or d.partner_id.commercial_partner_id) == partner)

    def _rebate_check_vendor_amount(self, source_move, received):
        """Open a claim when the vendor grants a different amount (TH-24)."""
        self.ensure_one()
        partner = source_move.commercial_partner_id
        expected = self._rebate_expected_for(partner)
        already = sum(self.claim_ids.filtered(lambda c: c.partner_id == partner and c.state != 'cancel')
                      .mapped('received_amount'))
        if self.currency_id.compare_amounts(expected, received + already) == 0:
            return False
        claim = self.env['rebate.claim'].create({
            'settlement_id': self.id,
            'partner_id': partner.id,
            'source_move_id': source_move.id,
            'expected_amount': expected - already,
            'received_amount': received,
        })
        self.message_post(body=self.env._(
            'NCC %(p)s chấp nhận %(r)s, số tự tính %(e)s: đã mở khiếu nại phần chênh lệch.',
            p=partner.display_name, r=self.currency_id.format(received), e=self.currency_id.format(expected)))
        return claim

    # ------------------------------------------------------------------
    # T26/T27 – allocation to inventory / COGS
    # ------------------------------------------------------------------
    def _rebate_accounts_for(self, det, product):
        """(inventory/price-diff account, cogs/expense account, adjust stock value?)"""
        accounts = product.product_tmpl_id.with_company(self.company_id).get_product_accounts()
        bill_account = det.move_line_id.account_id
        if self.agreement_id.cogs_split == 'all_cogs' or not product.is_storable:
            account = accounts['expense'] if product.is_storable else (bill_account or accounts['expense'])
            return account, account, False
        if product.valuation == 'real_time':
            cogs = accounts['expense']
            if product.cost_method == 'standard':
                return product._get_price_diff_account() or cogs, cogs, False
            return accounts['stock_valuation'], cogs, True
        # periodic valuation: the bill debited the purchase account; stock is revalued at closing
        account = bill_account or accounts['expense']
        return account, account, product.cost_method != 'standard'

    def _rebate_purchase_allocate(self, source_move, received_company):
        """Split ``received_company`` (company currency) of one vendor document."""
        self.ensure_one()
        company = self.company_id
        partner = source_move.commercial_partner_id
        details = self.detail_ids.filtered(
            lambda d: (d.target_move_id.commercial_partner_id or d.partner_id.commercial_partner_id) == partner)
        if not details or not received_company:
            return self.env['rebate.purchase.alloc']
        amounts = engine.allocate(received_company, details.mapped('allocated_amount'),
                                  company.currency_id.decimal_places)
        Alloc = self.env['rebate.purchase.alloc']
        allocs = Alloc
        value_moves = self.env['stock.move']
        pending = []  # (alloc vals, product, adjust)
        for det, amount in zip(details, amounts):
            if not amount:
                continue
            product = det.product_id
            inv_acc, cogs_acc, adjust = self._rebate_accounts_for(det, product)
            moves, qty_in, qty_rem = self._rebate_inventory_situation(det)
            if amount < 0 or not moves or not qty_in:
                adjust = False
            base = {
                'settlement_id': self.id, 'source_move_id': source_move.id, 'detail_id': det.id,
                'bill_line_id': det.move_line_id.id, 'product_id': product.id, 'company_id': company.id,
                'cost_method': product.cost_method if product.is_storable else False,
                'valuation': product.valuation if product.is_storable else False,
                'inventory_account_id': inv_acc.id, 'cogs_account_id': cogs_acc.id,
            }
            split = engine.split_inventory(amount, qty_in, qty_rem, digits=company.currency_id.decimal_places) \
                if (self.agreement_id.cogs_split != 'all_cogs' and qty_in and amount > 0) else \
                {'to_inventory': 0.0, 'to_cogs': amount}
            if adjust:
                shares = engine.allocate(amount, [m._get_valued_qty() for m in moves],
                                         company.currency_id.decimal_places)
                for move, share in zip(moves, shares):
                    pending.append((dict(base, stock_move_id=move.id, qty_in=move._get_valued_qty(),
                                         qty_remaining=max(move.remaining_qty, 0.0), amount=share,
                                         value_delta=-share), product, True))
                    value_moves |= move
            else:
                pending.append((dict(base, qty_in=qty_in, qty_remaining=qty_rem, amount=amount,
                                     to_inventory=split['to_inventory'], to_cogs=split['to_cogs']),
                                product, False))

        # measure the real inventory value change produced by Odoo's valuation (FIFO / AVCO)
        products = value_moves.product_id.with_company(company)
        before = {p: p.total_value for p in products}
        for vals, _product, _adjust in pending:
            allocs |= Alloc.create(vals)
        if value_moves:
            value_moves._set_value()
            products.invalidate_recordset(['total_value', 'avg_cost', 'standard_price'])
            delta = {p: before[p] - p.total_value for p in products}
            for product in products:
                prod_allocs = allocs.filtered(lambda a, p=product: a.stock_move_id and a.product_id == p)
                total = sum(prod_allocs.mapped('amount'))
                to_inv = company.currency_id.round(min(max(delta[product], 0.0), total))
                inv_parts = engine.allocate(to_inv, prod_allocs.mapped('amount'), company.currency_id.decimal_places)
                for alloc, inv in zip(prod_allocs, inv_parts):
                    alloc.write({'to_inventory': inv, 'to_cogs': alloc.amount - inv})
        entry = self._rebate_post_allocation_entry(source_move, allocs)
        allocs.write({'entry_id': entry.id})
        return allocs

    def _rebate_post_allocation_entry(self, source_move, allocs):
        self.ensure_one()
        company = self.company_id
        clearing = company._rebate_account('rebate_purchase_clearing_account_id')
        credits = defaultdict(float)
        for alloc in allocs:
            if alloc.to_inventory:
                credits[alloc.inventory_account_id] += alloc.to_inventory
            if alloc.to_cogs:
                credits[alloc.cogs_account_id] += alloc.to_cogs
        credits = {acc: company.currency_id.round(v) for acc, v in credits.items() if company.currency_id.round(v)}
        total = sum(credits.values())
        if not total:
            return self.env['account.move']
        ref = self.env._('Phân bổ CK mua %(s)s – %(m)s', s=self.name, m=source_move.display_name)
        lines = [Command.create({
            'name': ref, 'account_id': clearing.id, 'partner_id': source_move.commercial_partner_id.id,
            'debit': total if total > 0 else 0.0, 'credit': -total if total < 0 else 0.0,
        })]
        for account, amount in credits.items():
            lines.append(Command.create({
                'name': ref, 'account_id': account.id, 'partner_id': source_move.commercial_partner_id.id,
                'credit': amount if amount > 0 else 0.0, 'debit': -amount if amount < 0 else 0.0,
            }))
        entry = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': company._rebate_journal('general').id,
            'date': source_move.date,
            'ref': ref,
            'rebate_settlement_id': self.id,
            'line_ids': lines,
        })
        entry.action_post()
        return entry

    def _rebate_purchase_unallocate(self, source_moves):
        allocs = self.env['rebate.purchase.alloc'].search([
            ('source_move_id', 'in', source_moves.ids), ('state', '=', 'posted')])
        if not allocs:
            return
        for entry in allocs.entry_id.filtered(lambda m: m.state == 'posted'):
            entry._reverse_moves([{'date': entry.date, 'ref': self.env._('Hủy %s', entry.ref)}], cancel=True)
        moves = allocs.stock_move_id
        allocs.write({'state': 'cancel'})
        if moves:
            moves._set_value()
        self.env['rebate.claim'].search([('source_move_id', 'in', source_moves.ids),
                                         ('state', '=', 'open')]).write({'state': 'cancel'})
