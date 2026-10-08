from odoo import fields, models


class RebateVersionWizard(models.TransientModel):
    _name = 'rebate.version.wizard'
    _description = 'Tạo phiên bản mới cho thỏa thuận'

    agreement_id = fields.Many2one('rebate.agreement', required=True)
    date_start = fields.Date('Áp dụng từ ngày', required=True, default=fields.Date.context_today)
    reason = fields.Text('Lý do sửa đổi')

    def action_confirm(self):
        self.ensure_one()
        self.agreement_id._start_revision(self.date_start)
        if self.reason:
            self.agreement_id.message_post(body=self.env._('Sửa đổi từ %(d)s: %(r)s',
                                                           d=self.date_start.strftime('%d/%m/%Y'), r=self.reason))
        return {'type': 'ir.actions.act_window_close'}
