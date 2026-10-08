from odoo import fields, models

from .selections import ACCRUAL_MODE

# field name -> default account code prefix (Vietnamese chart, TT 99/2025)
REBATE_ACCOUNT_DEFAULTS = {
    'rebate_sale_account_id': '521',
    'rebate_purchase_clearing_account_id': '1388',
    'rebate_accrual_sale_account_id': '3388',
    'rebate_accrual_purchase_account_id': '1388',
    'rebate_accrual_purchase_counter_account_id': '632',
    'rebate_support_sale_account_id': '641',
    'rebate_support_purchase_account_id': '711',
}


class ResCompany(models.Model):
    _inherit = 'res.company'

    rebate_sale_account_id = fields.Many2one('account.account', string='TK chiết khấu bán (521)')
    rebate_purchase_clearing_account_id = fields.Many2one(
        'account.account', string='TK trung gian chiết khấu mua',
        help='Ghi Có trên hóa đơn điều chỉnh của NCC, sau đó được phân bổ vào tồn kho / giá vốn.')
    rebate_accrual_sale_account_id = fields.Many2one('account.account', string='TK tạm trích CK bán (3388)')
    rebate_accrual_purchase_account_id = fields.Many2one('account.account', string='TK tạm trích CK mua (1388)')
    rebate_accrual_purchase_counter_account_id = fields.Many2one(
        'account.account', string='TK đối ứng tạm trích CK mua (632)')
    rebate_support_sale_account_id = fields.Many2one('account.account', string='TK hỗ trợ trả cho khách (641)')
    rebate_support_purchase_account_id = fields.Many2one('account.account', string='TK hỗ trợ nhận từ NCC (711)')
    rebate_sale_journal_id = fields.Many2one('account.journal', string='Sổ nhật ký CK bán',
                                             domain="[('type', '=', 'sale')]")
    rebate_purchase_journal_id = fields.Many2one('account.journal', string='Sổ nhật ký CK mua',
                                                 domain="[('type', '=', 'purchase')]")
    rebate_misc_journal_id = fields.Many2one('account.journal', string='Sổ nhật ký bút toán CK',
                                             domain="[('type', '=', 'general')]")
    rebate_product_id = fields.Many2one('product.product', string='Sản phẩm dùng trên chứng từ CK')
    rebate_accrual_mode = fields.Selection(ACCRUAL_MODE, string='Tạm trích', default='management')
    rebate_approval_limit = fields.Monetary(
        string='Hạn mức duyệt của Người duyệt', currency_field='currency_id',
        help='Quyết toán có số tiền lớn hơn hạn mức này cần nhóm Quản trị duyệt. 0 = không giới hạn.')
    rebate_segregation = fields.Boolean(
        string='Người lập không được tự duyệt', default=True)

    def _rebate_account(self, fname):
        """Configured account, or the first account matching the default code prefix."""
        self.ensure_one()
        account = self[fname]
        if account:
            return account
        prefix = REBATE_ACCOUNT_DEFAULTS.get(fname)
        if not prefix:
            return account
        return self.env['account.account'].search([
            *self.env['account.account']._check_company_domain(self),
            ('code', '=like', prefix + '%'),
            ('active', '=', True),
        ], order='code', limit=1)

    def _rebate_journal(self, kind):
        self.ensure_one()
        fname = {'sale': 'rebate_sale_journal_id', 'purchase': 'rebate_purchase_journal_id',
                 'general': 'rebate_misc_journal_id'}[kind]
        return self[fname] or self.env['account.journal'].search([
            *self.env['account.journal']._check_company_domain(self),
            ('type', '=', kind),
        ], limit=1)

    def _rebate_product(self):
        self.ensure_one()
        return self.rebate_product_id or self.env.ref('rebate_base.product_rebate', raise_if_not_found=False)
