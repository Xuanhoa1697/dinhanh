{
    'name': 'Chiết khấu cuối kỳ (Rebate) – Nền tảng',
    'summary': 'Thỏa thuận, lũy kế, engine tính và quyết toán chiết khấu cuối kỳ cho mua và bán',
    'description': """
Chiết khấu cuối kỳ theo sản lượng / doanh số (volume rebate).
- Thỏa thuận có phiên bản, quy tắc, bậc thang hồi tố hoặc lũy tiến
- Tự ghi nhận lũy kế từ hóa đơn đã ghi sổ, kể cả hàng trả lại
- Engine tính thuần Python, phân bổ ngược về từng hóa đơn và thuế suất
- Khóa kỳ, quyết toán, duyệt theo hạn mức, bảng kê và biên bản xác nhận
""",
    'version': '1.0.0',
    'category': 'Accounting/Accounting',
    'author': 'Arrowhitech',
    'license': 'LGPL-3',
    'depends': ['account', 'mail', 'product', 'uom'],
    'data': [
        'security/rebate_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/product_data.xml',
        'views/rebate_template_views.xml',
        'views/rebate_rule_views.xml',
        'views/rebate_agreement_views.xml',
        'views/rebate_period_views.xml',
        'views/rebate_line_views.xml',
        'views/rebate_settlement_views.xml',
        'views/account_move_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/rebate_version_wizard_views.xml',
        'wizard/rebate_xlsx_export_views.xml',
        'wizard/rebate_import_views.xml',
        'report/rebate_settlement_report.xml',
        'report/rebate_settlement_templates.xml',
        'views/rebate_menus.xml',
    ],
    'installable': True,
    'application': True,
}
