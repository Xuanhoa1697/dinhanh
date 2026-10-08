{
    'name': 'Chiết khấu cuối kỳ – Báo cáo',
    'summary': 'Biên lợi nhuận sau chiết khấu, bảng điều khiển cảnh báo, mô phỏng chiết khấu',
    'version': '1.0.0',
    'category': 'Accounting/Accounting',
    'author': 'Arrowhitech',
    'license': 'LGPL-3',
    'depends': ['rebate_base'],
    'data': [
        'security/ir.model.access.csv',
        'report/rebate_margin_report_views.xml',
        'wizard/rebate_simulation_views.xml',
        'views/rebate_dashboard_views.xml',
    ],
    'installable': True,
}
