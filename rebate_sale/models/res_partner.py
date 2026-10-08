from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    rebate_agreement_count = fields.Integer(compute='_compute_rebate_agreement_count',
                                            groups='rebate_base.group_rebate_user')

    def _rebate_agreement_domain(self):
        self.ensure_one()
        commercial = self.commercial_partner_id
        domain = [('partner_ids', 'in', commercial.ids + commercial.child_ids.ids)]
        if commercial.category_id:
            domain = ['|', *domain, ('partner_category_ids', 'in', commercial.category_id.ids)]
        return domain

    def _compute_rebate_agreement_count(self):
        Agreement = self.env['rebate.agreement']
        for partner in self:
            partner.rebate_agreement_count = Agreement.search_count(partner._rebate_agreement_domain())

    def action_view_rebate_agreements(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('rebate_base.action_rebate_agreement')
        action['domain'] = self._rebate_agreement_domain()
        return action
