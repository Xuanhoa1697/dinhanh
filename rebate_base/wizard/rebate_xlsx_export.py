import base64
import io

import xlsxwriter

from odoo import fields, models


class RebateXlsxExport(models.TransientModel):
    """T19 – bảng kê hóa đơn điều chỉnh dạng Excel."""
    _name = 'rebate.xlsx.export'
    _description = 'Xuất bảng kê chiết khấu cuối kỳ (Excel)'

    settlement_id = fields.Many2one('rebate.settlement', required=True)
    file_data = fields.Binary('File', readonly=True)
    file_name = fields.Char()

    def _build(self):
        settlement = self.settlement_id
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True})
        bold = wb.add_format({'bold': True})
        title = wb.add_format({'bold': True, 'font_size': 14})
        head = wb.add_format({'bold': True, 'bg_color': '#E3F0EC', 'border': 1, 'text_wrap': True,
                              'align': 'center', 'valign': 'vcenter'})
        money = wb.add_format({'num_format': '#,##0', 'border': 1})
        cell = wb.add_format({'border': 1})
        datef = wb.add_format({'num_format': 'dd/mm/yyyy', 'border': 1})
        total_money = wb.add_format({'num_format': '#,##0', 'border': 1, 'bold': True})

        ws = wb.add_worksheet('Bang ke')
        ws.write(0, 0, 'BẢNG KÊ HÓA ĐƠN ĐIỀU CHỈNH CHIẾT KHẤU THƯƠNG MẠI', title)
        ws.write(1, 0, 'Kèm theo quyết toán %s – thỏa thuận %s – kỳ %s (%s – %s)' % (
            settlement.name, settlement.agreement_id.name, settlement.period_id.name,
            settlement.date_from.strftime('%d/%m/%Y'), settlement.date_to.strftime('%d/%m/%Y')))
        headers = ['STT', 'Đối tác', 'MST', 'Số hóa đơn', 'Ngày hóa đơn', 'Thuế suất (%)',
                   'Giá trị hàng hóa chưa thuế', 'Chiết khấu điều chỉnh giảm', 'Thuế GTGT điều chỉnh']
        for col, text in enumerate(headers):
            ws.write(3, col, text, head)
        widths = [6, 34, 16, 18, 14, 12, 22, 22, 20]
        for col, width in enumerate(widths):
            ws.set_column(col, col, width)
        row = 4
        tot = [0.0, 0.0, 0.0]
        for idx, r in enumerate(settlement._statement_rows(), start=1):
            ws.write(row, 0, idx, cell)
            ws.write(row, 1, r['partner'].display_name or '', cell)
            ws.write(row, 2, r['partner'].vat or '', cell)
            ws.write(row, 3, r['number'] or '', cell)
            if r['date']:
                ws.write_datetime(row, 4, fields.Datetime.to_datetime(r['date']), datef)
            else:
                ws.write(row, 4, '', cell)
            ws.write(row, 5, r['tax_rate'], cell)
            ws.write(row, 6, r['base'], money)
            ws.write(row, 7, r['amount'], money)
            ws.write(row, 8, r['tax'], money)
            tot[0] += r['base']
            tot[1] += r['amount']
            tot[2] += r['tax']
            row += 1
        ws.write(row, 1, 'Tổng cộng', bold)
        for i, val in enumerate(tot):
            ws.write(row, 6 + i, val, total_money)

        ws2 = wb.add_worksheet('Ket qua')
        ws2.write(0, 0, 'Kết quả theo quy tắc', title)
        for col, text in enumerate(['Quy tắc', 'Đã đạt', 'Bậc đạt', 'Còn thiếu lên bậc', 'CK theo bậc']):
            ws2.write(2, col, text, head)
        ws2.set_column(0, 0, 36)
        ws2.set_column(1, 4, 20)
        for i, res in enumerate(settlement.result_ids, start=3):
            ws2.write(i, 0, res.rule_id.name or '', cell)
            ws2.write(i, 1, res.measure, money)
            ws2.write(i, 2, res.tier_label or '', cell)
            ws2.write(i, 3, res.next_gap, money)
            ws2.write(i, 4, res.amount, money)
        r = len(settlement.result_ids) + 4
        for label, val in [('CK của kỳ', settlement.amount), ('Đã quyết toán trước', settlement.prior_paid),
                           ('Số cần quyết toán', settlement.amount_to_settle),
                           ('Thuế GTGT điều chỉnh', settlement.tax_amount)]:
            ws2.write(r, 0, label, bold)
            ws2.write(r, 4, val, total_money)
            r += 1
        wb.close()
        return buf.getvalue()

    def action_export(self):
        self.ensure_one()
        data = self._build()
        name = 'BangKe_%s.xlsx' % self.settlement_id.name.replace('/', '_')
        self.write({'file_data': base64.b64encode(data), 'file_name': name})
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/rebate.xlsx.export/%s/file_data/%s?download=true' % (self.id, name),
            'target': 'self',
        }
