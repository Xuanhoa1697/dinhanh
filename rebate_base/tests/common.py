from odoo import fields
from odoo.fields import Command

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

TIERS_3 = [(0, 1_000_000, 0.0), (1_000_000, 2_000_000, 1.0), (2_000_000, 0, 2.0)]


class RebateCommon(AccountTestInvoicingCommon):
    """Shared fixtures for every rebate module test."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('rebate_base.group_rebate_admin')
        cls.company = cls.env.company
        cls.company.rebate_segregation = False
        cls.currency = cls.company.currency_id
        cls.tax_10 = cls.company_data['default_tax_sale'].copy({'name': 'VAT 10 test', 'amount': 10})
        cls.tax_8 = cls.company_data['default_tax_sale'].copy({'name': 'VAT 8 test', 'amount': 8})
        cls.ptax_10 = cls.company_data['default_tax_purchase'].copy({'name': 'PVAT 10 test', 'amount': 10})
        cls.ptax_8 = cls.company_data['default_tax_purchase'].copy({'name': 'PVAT 8 test', 'amount': 8})
        cls.categ_drink = cls.env['product.category'].create({'name': 'Nước giải khát'})
        cls.categ_snack = cls.env['product.category'].create({'name': 'Bánh kẹo'})
        cls.p_drink = cls._create_product(name='Nước ngọt', categ_id=cls.categ_drink.id, lst_price=100,
                                          taxes_id=[Command.set(cls.tax_10.ids)])
        cls.p_snack = cls._create_product(name='Bánh quy', categ_id=cls.categ_snack.id, lst_price=50,
                                          taxes_id=[Command.set(cls.tax_8.ids)])
        cls.customer = cls.env['res.partner'].create({'name': 'Nhà phân phối A', 'vat': '0101234567'})
        cls.customer2 = cls.env['res.partner'].create({'name': 'Nhà phân phối B', 'vat': '0109876543'})
        cls.vendor = cls.env['res.partner'].create({'name': 'Nhà cung cấp X', 'vat': '0300000001'})
        cls.d = staticmethod(fields.Date.to_date)

    # ------------------------------------------------------------------
    @classmethod
    def _create_agreement(cls, direction='sale', partners=None, rules=None, period_type='quarter',
                          date_from='2026-01-01', date_to='2026-12-31', approve=True, **kw):
        """rules: list of dict(name, tiers=[(from, to, value)], + rule fields)."""
        rules = rules or [{'name': 'Tất cả', 'tiers': TIERS_3}]
        rule_cmds = []
        for seq, rule in enumerate(rules):
            rule = dict(rule)
            tiers = rule.pop('tiers')
            rule_cmds.append(Command.create(dict(
                rule, sequence=seq,
                tier_ids=[Command.create({'from_value': f, 'to_value': t, 'value': v}) for f, t, v in tiers])))
        vals = {
            'title': 'Test %s' % direction,
            'direction': direction,
            'partner_ids': [Command.set((partners or cls.customer).ids)],
            'date_from': date_from,
            'date_to': date_to,
            'period_type': period_type,
            'rule_ids': rule_cmds,
        }
        vals.update(kw)
        agreement = cls.env['rebate.agreement'].create(vals)
        if approve:
            agreement.action_submit()
            agreement.action_approve()
        return agreement

    @classmethod
    def _invoice(cls, date, lines, partner=None, move_type='out_invoice', post=True, reversed_entry=None,
                 currency=None):
        """lines: list of (product, qty, price_unit[, taxes[, discount]])."""
        line_cmds = []
        for spec in lines:
            product, qty, price = spec[:3]
            vals = {'product_id': product.id, 'quantity': qty, 'price_unit': price}
            if len(spec) > 3 and spec[3] is not None:
                vals['tax_ids'] = [Command.set(spec[3].ids)]
            elif move_type in ('in_invoice', 'in_refund'):
                tax = cls.ptax_10 if product == cls.p_drink else cls.ptax_8
                vals['tax_ids'] = [Command.set(tax.ids)]
            if len(spec) > 4:
                vals['discount'] = spec[4]
            line_cmds.append(Command.create(vals))
        move_vals = {
            'move_type': move_type,
            'partner_id': (partner or (cls.vendor if move_type.startswith('in_') else cls.customer)).id,
            'invoice_date': date,
            'date': date,
            'invoice_line_ids': line_cmds,
        }
        if reversed_entry:
            move_vals['reversed_entry_id'] = reversed_entry.id
        if currency:
            move_vals['currency_id'] = currency.id
        move = cls.env['account.move'].create(move_vals)
        if post:
            move.action_post()
        return move

    @classmethod
    def _period(cls, agreement, name):
        return agreement.period_ids.filtered(lambda p: p.name == name)

    @classmethod
    def _settle(cls, period):
        period.action_compute_settlement()
        return period.settlement_ids.filtered(lambda s: s.state == 'computed')[:1]
