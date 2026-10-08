from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models


class RebateDashboard(models.TransientModel):
    """T37 – one screen with what needs attention."""
    _name = 'rebate.dashboard'
    _description = 'Bảng điều khiển chiết khấu cuối kỳ'

    name = fields.Char(default='Bảng điều khiển')
    near_ratio = fields.Float('Ngưỡng "sát bậc" (%)', default=10.0,
                              help='Kỳ đang mở còn thiếu ít hơn tỷ lệ này để lên bậc kế tiếp.')
    count_due = fields.Integer(compute='_compute_counts')
    count_recalc = fields.Integer(compute='_compute_counts')
    count_agreement_to_approve = fields.Integer(compute='_compute_counts')
    count_settlement_to_approve = fields.Integer(compute='_compute_counts')
    count_to_document = fields.Integer(compute='_compute_counts')
    count_expiring = fields.Integer(compute='_compute_counts')
    count_vendor_pending = fields.Integer(compute='_compute_counts')
    count_near = fields.Integer(compute='_compute_near')
    near_html = fields.Html(compute='_compute_near', sanitize=False)

    # ------------------------------------------------------------------
    @api.model
    def _domains(self):
        today = fields.Date.context_today(self)
        domains = {
            'due': ('rebate.period', [('state', '!=', 'settled'), ('date_to', '<', today), ('child_ids', '=', False)]),
            'recalc': ('rebate.period', [('needs_recalc', '=', True)]),
            'agreement_to_approve': ('rebate.agreement', [('state', '=', 'to_approve')]),
            'settlement_to_approve': ('rebate.settlement', [('state', '=', 'to_approve')]),
            'to_document': ('rebate.settlement', [('state', '=', 'approved')]),
            'expiring': ('rebate.agreement', [('state', '=', 'active'),
                                              ('date_to', '<=', today + relativedelta(days=30))]),
        }
        if 'vendor_pending' in self.env['rebate.settlement']._fields:
            domains['vendor_pending'] = ('rebate.settlement', [('vendor_pending', '=', True)])
        return domains

    def _compute_counts(self):
        domains = self._domains()
        for rec in self:
            for key in ('due', 'recalc', 'agreement_to_approve', 'settlement_to_approve', 'to_document',
                        'expiring', 'vendor_pending'):
                if key in domains:
                    model, domain = domains[key]
                    rec['count_%s' % key] = self.env[model].search_count(domain)
                else:
                    rec['count_%s' % key] = 0

    def _near_threshold_periods(self, ratio):
        today = fields.Date.context_today(self)
        Settlement = self.env['rebate.settlement']
        periods = self.env['rebate.period'].search([
            ('state', '=', 'open'), ('date_from', '<=', today), ('date_to', '>=', today),
            ('agreement_id.state', 'in', ('active', 'revision'))])
        result = []
        for period in periods:
            evaluation = Settlement._rebate_evaluate(period.agreement_id, period, period._get_all_lines())
            for r in evaluation['rules']:
                gap = r['next_gap']
                if gap <= 0:
                    continue
                target = r['measure'] + gap
                if target and gap / target * 100 <= ratio:
                    result.append((period, r))
        return result

    @api.depends('near_ratio')
    def _compute_near(self):
        for rec in self:
            near = rec._near_threshold_periods(rec.near_ratio)
            rec.count_near = len(near)
            rows = Markup('').join(
                Markup('<tr><td>%s</td><td>%s</td><td>%s</td><td class="text-end">%s</td>'
                       '<td class="text-end">%s</td></tr>') % (
                    period.agreement_id.display_name, period.name, r['rule'].name,
                    '{:,.0f}'.format(r['measure']), '{:,.0f}'.format(r['next_gap']))
                for period, r in near)
            rec.near_html = Markup(
                '<table class="table table-sm"><thead><tr><th>Thỏa thuận</th><th>Kỳ</th><th>Quy tắc</th>'
                '<th class="text-end">Đã đạt</th><th class="text-end">Còn thiếu</th></tr></thead>'
                '<tbody>%s</tbody></table>') % rows if near else False

    def _open(self, key, name):
        model, domain = self._domains()[key]
        return {'type': 'ir.actions.act_window', 'name': name, 'res_model': model,
                'view_mode': 'list,form', 'domain': domain}

    def action_open_due(self):
        return self._open('due', self.env._('Kỳ đến hạn quyết toán'))

    def action_open_recalc(self):
        return self._open('recalc', self.env._('Kỳ cần tính lại'))

    def action_open_agreement_to_approve(self):
        return self._open('agreement_to_approve', self.env._('Thỏa thuận chờ duyệt'))

    def action_open_settlement_to_approve(self):
        return self._open('settlement_to_approve', self.env._('Quyết toán chờ duyệt'))

    def action_open_to_document(self):
        return self._open('to_document', self.env._('Quyết toán chờ lập chứng từ'))

    def action_open_expiring(self):
        return self._open('expiring', self.env._('Thỏa thuận sắp hết hạn'))

    def action_open_vendor_pending(self):
        return self._open('vendor_pending', self.env._('Chờ chứng từ NCC'))
