from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.rebate_base.tests.common import RebateCommon

TEN_PCT = [(0, 0, 10.0)]


@tagged('post_install', '-at_install', 'rebate')
class TestRebatePurchase(RebateCommon):
    """T24–T28 on a real purchase → receipt → bill → delivery flow (Odoo 19 valuation)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref('stock.group_stock_manager') | cls.env.ref('purchase.group_purchase_manager')
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.clearing = cls.company_data['default_account_assets'].copy({'code': '138801', 'name': 'CK mua trung gian'})
        cls.company.rebate_purchase_clearing_account_id = cls.clearing
        cls.price_diff = cls.company_data['default_account_expense'].copy({'code': '632999', 'name': 'Chênh lệch giá'})

        def categ(name, method, valuation):
            return cls.env['product.category'].create({
                'name': name, 'property_cost_method': method, 'property_valuation': valuation,
                'property_price_difference_account_id': cls.price_diff.id,
            })

        def product(name, cat):
            return cls.env['product.product'].create({
                'name': name, 'is_storable': True, 'categ_id': cat.id, 'standard_price': 100,
                'supplier_taxes_id': [Command.set(cls.ptax_10.ids)], 'taxes_id': [Command.set(cls.tax_10.ids)],
            })
        cls.p_fifo = product('Hàng FIFO', categ('FIFO RT', 'fifo', 'real_time'))
        cls.p_avco = product('Hàng BQ', categ('AVCO RT', 'average', 'real_time'))
        cls.p_std = product('Hàng giá chuẩn', categ('STD RT', 'standard', 'real_time'))
        cls.p_periodic = product('Hàng định kỳ', categ('FIFO P', 'fifo', 'periodic'))

    # ------------------------------------------------------------------
    def _buy(self, product, qty, price, date='2026-01-10'):
        po = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'order_line': [Command.create({'product_id': product.id, 'product_qty': qty, 'price_unit': price,
                                           'tax_ids': [Command.set(self.ptax_10.ids)]})],
        })
        po.button_confirm()
        picking = po.picking_ids
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.move_ids.picked = True
        picking.button_validate()
        po.action_create_invoice()
        bill = po.invoice_ids
        bill.write({'invoice_date': date, 'date': date})
        bill.action_post()
        return bill

    def _sell_out(self, product, qty):
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom': product.uom_id.id,
            'product_uom_qty': qty,
            'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'picking_type_id': self.warehouse.out_type_id.id,
        })
        move._action_confirm()
        move._action_assign()
        move.quantity = qty
        move.picked = True
        move._action_done()
        return move

    def _settle_purchase(self, agreement, period='Q1/2026'):
        st = self._settle(self._period(agreement, period))
        st.action_submit()
        st.action_approve()
        st.action_generate_documents()
        return st

    def _agreement(self, **kw):
        return self._create_agreement(direction='purchase', partners=self.vendor,
                                      rules=[{'name': '10%', 'tiers': TEN_PCT}], **kw)

    # ------------------------------------------------------------------
    def test_01_fifo_real_time_split(self):
        """S12 – 1,000 rebate, 100 received, 70 sold → 300 stock / 700 COGS."""
        agr = self._agreement()
        self._buy(self.p_fifo, 100, 100)
        self._sell_out(self.p_fifo, 70)
        self.assertEqual(self.p_fifo.total_value, 3000)
        st = self._settle_purchase(agr)
        self.assertIn('Vào tồn kho', st.cogs_preview_html)
        refund = st.move_ids
        self.assertEqual(refund.move_type, 'in_refund')
        self.assertEqual(refund.state, 'draft')
        self.assertTrue(st.vendor_pending)
        refund.ref = 'C26TXX-0001'
        refund.action_post()
        allocs = st.purchase_alloc_ids
        self.assertAlmostEqual(sum(allocs.mapped('to_inventory')), 300)
        self.assertAlmostEqual(sum(allocs.mapped('to_cogs')), 700)
        self.p_fifo.invalidate_recordset()
        self.assertAlmostEqual(self.p_fifo.total_value, 2700)
        self.assertAlmostEqual(self.p_fifo.standard_price, 90)
        entry = allocs.entry_id
        self.assertEqual(entry.state, 'posted')
        clearing_balance = sum(self.env['account.move.line'].search([
            ('account_id', '=', self.clearing.id), ('parent_state', '=', 'posted')]).mapped('balance'))
        self.assertAlmostEqual(clearing_balance, 0, msg='clearing account fully cleared')
        self.assertFalse(st.claim_ids)
        self.assertFalse(st.vendor_pending)

    def test_02_avco_real_time_split(self):
        agr = self._agreement()
        self._buy(self.p_avco, 100, 100)
        self._sell_out(self.p_avco, 70)
        st = self._settle_purchase(agr)
        st.move_ids.action_post()
        allocs = st.purchase_alloc_ids
        self.p_avco.invalidate_recordset()
        self.assertAlmostEqual(sum(allocs.mapped('to_inventory')) + sum(allocs.mapped('to_cogs')), 1000)
        self.assertAlmostEqual(self.p_avco.total_value, 3000 - sum(allocs.mapped('to_inventory')))
        self.assertAlmostEqual(sum(allocs.mapped('to_inventory')), 300)

    def test_03_standard_goes_to_price_difference(self):
        agr = self._agreement()
        self._buy(self.p_std, 100, 100)
        self._sell_out(self.p_std, 70)
        st = self._settle_purchase(agr)
        st.move_ids.action_post()
        alloc = st.purchase_alloc_ids
        self.assertAlmostEqual(alloc.to_inventory, 300)
        self.assertEqual(alloc.inventory_account_id, self.price_diff)
        self.p_std.invalidate_recordset()
        self.assertEqual(self.p_std.standard_price, 100, 'standard cost unchanged')

    def test_04_periodic_whole_amount_on_purchase_account(self):
        agr = self._agreement()
        bill = self._buy(self.p_periodic, 100, 100)
        st = self._settle_purchase(agr)
        st.move_ids.action_post()
        alloc = st.purchase_alloc_ids
        bill_account = bill.invoice_line_ids.account_id
        self.assertEqual(alloc.inventory_account_id, bill_account)
        self.assertEqual(alloc.cogs_account_id, bill_account)

    def test_05_vendor_grants_less_opens_claim(self):
        agr = self._agreement()
        self._buy(self.p_fifo, 100, 100)
        st = self._settle_purchase(agr)
        refund = st.move_ids
        refund.invoice_line_ids.price_unit = 900
        refund.action_post()
        claim = st.claim_ids
        self.assertEqual(claim.difference, 100)
        self.assertEqual(claim.state, 'open')
        self.assertAlmostEqual(sum(st.purchase_alloc_ids.mapped('amount')), 900)
        # reset the vendor document: allocation is reversed, stock value restored
        refund.button_draft()
        self.assertEqual(set(st.purchase_alloc_ids.mapped('state')), {'cancel'})
        self.p_fifo.invalidate_recordset()
        self.assertAlmostEqual(self.p_fifo.total_value, 10000)
        self.assertEqual(claim.state, 'cancel')

    def test_06_link_vendor_own_credit_note(self):
        agr = self._agreement()
        self._buy(self.p_fifo, 100, 100)
        st = self._settle_purchase(agr)
        st.move_ids.button_cancel()
        vendor_doc = self._invoice('2026-04-05', [(self.company._rebate_product(), 1, 1000, self.ptax_10)],
                                   partner=self.vendor, move_type='in_refund', post=False)
        vendor_doc.rebate_settlement_id = st
        self.assertEqual(vendor_doc.invoice_line_ids.account_id, self.clearing)
        vendor_doc.action_post()
        self.assertAlmostEqual(sum(st.purchase_alloc_ids.mapped('amount')), 1000)

    def test_07_next_bill_deduction(self):
        agr = self._agreement(settlement_doc='next_invoice', payment_method='next_invoice')
        self._buy(self.p_fifo, 100, 100)
        st = self._settle_purchase(agr)
        self.assertEqual(st.carryforward_ids.amount, 1000)
        next_bill = self._invoice('2026-04-10', [(self.p_avco, 50, 100, self.ptax_10)], partner=self.vendor,
                                  move_type='in_invoice', post=False)
        next_bill.action_rebate_apply_carryforward()
        self.assertEqual(next_bill.amount_untaxed, 4000)
        next_bill.action_post()
        self.assertAlmostEqual(sum(st.purchase_alloc_ids.mapped('amount')), 1000)
        self.assertEqual(st.carryforward_ids.amount_residual, 0)

    def test_08_foreign_currency_agreement(self):
        eur = self.setup_other_currency('EUR', rates=[('2026-01-01', 2.0)])
        agr = self._agreement(currency_id=eur.id)
        self._buy(self.p_fifo, 100, 100)                 # 10,000 company currency = 20,000 EUR
        st = self._settle_purchase(agr)
        self.assertEqual(st.amount, 2000)
        refund = st.move_ids
        self.assertEqual(refund.currency_id, eur)
        refund.action_post()
        self.assertAlmostEqual(sum(st.purchase_alloc_ids.mapped('amount')), 1000)
