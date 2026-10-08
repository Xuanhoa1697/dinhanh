from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.fields import Command


class RebateAccrual(models.Model):
    """T31 – monthly estimate of the rebate not yet settled.

    Balance per root period = Σ amount. Each run books the difference between
    the new estimate and the current balance; a done settlement releases its
    share, so the balance never doubles with the real documents.
    """
    _name = 'rebate.accrual'
    _description = 'Tạm trích chiết khấu cuối kỳ'
    _order = 'date desc, id desc'

    agreement_id = fields.Many2one('rebate.agreement', required=True, ondelete='cascade', index=True)
    period_id = fields.Many2one('rebate.period', string='Kỳ', required=True, ondelete='cascade', index=True,
                                help='Kỳ gốc (kỳ tổng nếu có).')
    direction = fields.Selection(related='agreement_id.direction', store=True)
    company_id = fields.Many2one(related='agreement_id.company_id', store=True)
    currency_id = fields.Many2one(related='agreement_id.currency_id', store=True)
    date = fields.Date('Ngày', required=True)
    estimate = fields.Monetary('CK ước tính chưa quyết toán', currency_field='currency_id')
    amount = fields.Monetary('Số trích (+) / hoàn nhập (−)', currency_field='currency_id')
    kind = fields.Selection([('estimate', 'Ước tính'), ('release', 'Hoàn nhập khi quyết toán')],
                            default='estimate', required=True)
    settlement_id = fields.Many2one('rebate.settlement', string='Quyết toán', ondelete='set null')
    mode = fields.Selection([('management', 'Sổ quản trị'), ('gl', 'Sổ cái')], required=True)
    move_id = fields.Many2one('account.move', string='Bút toán', ondelete='set null')

    @api.model
    def _balance(self, period):
        return sum(self.search([('period_id', '=', period.id)]).mapped('amount'))

    @api.model
    def _root(self, period):
        while period.parent_id:
            period = period.parent_id
        return period

    @api.model
    def _create_entry(self, agreement, amount, date, label):
        company = agreement.company_id
        amount_company = agreement.currency_id._convert(amount, company.currency_id, company, date)
        amount_company = company.currency_id.round(amount_company)
        if not amount_company:
            return self.env['account.move']
        if agreement.direction == 'sale':
            debit = company._rebate_account('rebate_sale_account_id')
            credit = company._rebate_account('rebate_accrual_sale_account_id')
        else:
            debit = company._rebate_account('rebate_accrual_purchase_account_id')
            credit = company._rebate_account('rebate_accrual_purchase_counter_account_id')
        if amount_company < 0:
            debit, credit = credit, debit
            amount_company = -amount_company
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': company._rebate_journal('general').id,
            'date': date,
            'ref': label,
            'line_ids': [
                Command.create({'name': label, 'account_id': debit.id, 'debit': amount_company}),
                Command.create({'name': label, 'account_id': credit.id, 'credit': amount_company}),
            ],
        })
        move.action_post()
        return move

    @api.model
    def _book(self, agreement, period, amount, date, estimate=0.0, kind='estimate', settlement=None):
        mode = agreement.company_id.rebate_accrual_mode
        if mode == 'none' or not agreement.currency_id.round(amount):
            return self.browse()
        label = self.env._('Tạm trích CK %(agr)s – %(p)s', agr=agreement.name, p=period.name) if kind == 'estimate' \
            else self.env._('Hoàn nhập tạm trích CK %(agr)s – %(p)s', agr=agreement.name, p=period.name)
        move = self._create_entry(agreement, amount, date, label) if mode == 'gl' else self.env['account.move']
        return self.create({
            'agreement_id': agreement.id, 'period_id': period.id, 'date': date, 'amount': amount,
            'estimate': estimate, 'kind': kind, 'settlement_id': settlement.id if settlement else False,
            'mode': mode, 'move_id': move.id,
        })

    @api.model
    def _run(self, date=None, agreements=None):
        """Book the accrual of every active agreement as of ``date``."""
        date = date or (fields.Date.context_today(self).replace(day=1) - relativedelta(days=1))
        agreements = agreements if agreements is not None else self.env['rebate.agreement'].search([
            ('state', 'in', ('active', 'revision')), ('date_from', '<=', date)])
        Settlement = self.env['rebate.settlement']
        created = self.browse()
        for agreement in agreements:
            if agreement.company_id.rebate_accrual_mode == 'none':
                continue
            roots = agreement.period_ids.filtered(
                lambda p: not p.parent_id and p.date_from <= date and p.state != 'settled')
            for root in roots:
                lines = root._get_all_lines().filtered(lambda ln, d=date: ln.date <= d)
                gross = Settlement._rebate_evaluate(agreement, root, lines)['gross_amount']
                settled = sum(Settlement.search([
                    ('period_id', 'child_of', root.id), ('state', '=', 'done')]).mapped('amount_to_settle'))
                estimate = agreement.currency_id.round(max(gross - settled, 0.0))
                delta = estimate - self._balance(root)
                created |= self._book(agreement, root, delta, date, estimate=estimate)
        return created

    @api.model
    def _cron_run(self):
        self._run()

    @api.model
    def _release_for_settlement(self, settlement):
        root = self._root(settlement.period_id)
        balance = self._balance(root)
        if not balance:
            return self.browse()
        release = balance if root == settlement.period_id else min(balance, max(settlement.amount_to_settle, 0.0))
        return self._book(settlement.agreement_id, root, -release, settlement.doc_date or fields.Date.today(),
                          kind='release', settlement=settlement)

    def action_run_now(self):
        self._run(date=fields.Date.context_today(self))
        return {'type': 'ir.actions.client', 'tag': 'reload'}
