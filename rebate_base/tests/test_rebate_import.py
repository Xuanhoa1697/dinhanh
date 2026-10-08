import base64
import io

import openpyxl

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import RebateCommon


@tagged('post_install', '-at_install', 'rebate')
class TestRebateImport(RebateCommon):
    """T39 – import running agreements and rebuild their accumulation."""

    def _file(self, rows):
        wiz = self.env['rebate.import'].create({})
        wb = openpyxl.load_workbook(io.BytesIO(wiz._template_bytes()))
        ws = wb.active
        ws.delete_rows(3, ws.max_row)
        for row in rows:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        return base64.b64encode(buf.getvalue())

    def test_01_import_and_rebuild(self):
        self._invoice('2026-02-10', [(self.p_drink, 25000, 100)])   # invoice posted before the import
        base = ['IMP-1', 'Thưởng NPP A', 'sale', self.customer.vat, 'HĐ 01', '01/01/2026', '31/12/2026',
                'quarter', 'adjust_invoice', 'offset', 'Tất cả', 'all', '', 'amount', 'retro', 'percent']
        data = self._file([base + [1_000_000, 2_000_000, 1], base + [2_000_000, 0, 2]])
        wiz = self.env['rebate.import'].create({'file_data': data, 'approve': True})
        wiz.action_import()
        agr = self.env['rebate.agreement'].search([('contract_ref', '=', 'HĐ 01')])
        self.assertEqual(agr.state, 'active')
        self.assertEqual(len(agr.rule_ids.tier_ids), 2)
        self.assertEqual(len(agr.line_ids), 1, 'existing invoice picked up')
        st = self._settle(self._period(agr, 'Q1/2026'))
        self.assertEqual(st.amount, 50_000)

    def test_02_bad_value_rejected(self):
        row = ['IMP-2', 'X', 'sale', self.customer.vat, '', '01/01/2026', '31/12/2026', 'weekly',
               'adjust_invoice', 'offset', 'R', 'all', '', 'amount', 'retro', 'percent', 0, 0, 1]
        wiz = self.env['rebate.import'].create({'file_data': self._file([row])})
        with self.assertRaises(UserError):
            wiz.action_import()
