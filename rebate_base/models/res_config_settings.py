from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rebate_sale_account_id = fields.Many2one(related='company_id.rebate_sale_account_id', readonly=False)
    rebate_purchase_clearing_account_id = fields.Many2one(
        related='company_id.rebate_purchase_clearing_account_id', readonly=False)
    rebate_accrual_sale_account_id = fields.Many2one(
        related='company_id.rebate_accrual_sale_account_id', readonly=False)
    rebate_accrual_purchase_account_id = fields.Many2one(
        related='company_id.rebate_accrual_purchase_account_id', readonly=False)
    rebate_accrual_purchase_counter_account_id = fields.Many2one(
        related='company_id.rebate_accrual_purchase_counter_account_id', readonly=False)
    rebate_support_sale_account_id = fields.Many2one(
        related='company_id.rebate_support_sale_account_id', readonly=False)
    rebate_support_purchase_account_id = fields.Many2one(
        related='company_id.rebate_support_purchase_account_id', readonly=False)
    rebate_sale_journal_id = fields.Many2one(related='company_id.rebate_sale_journal_id', readonly=False)
    rebate_purchase_journal_id = fields.Many2one(related='company_id.rebate_purchase_journal_id', readonly=False)
    rebate_misc_journal_id = fields.Many2one(related='company_id.rebate_misc_journal_id', readonly=False)
    rebate_product_id = fields.Many2one(related='company_id.rebate_product_id', readonly=False)
    rebate_accrual_mode = fields.Selection(related='company_id.rebate_accrual_mode', readonly=False)
    rebate_approval_limit = fields.Monetary(related='company_id.rebate_approval_limit', readonly=False)
    rebate_segregation = fields.Boolean(related='company_id.rebate_segregation', readonly=False)
