{
    'name': 'Chiết khấu cuối kỳ – Kiểm soát',
    'summary': 'Điều kiện hưởng (tuổi nợ, trả hàng, tăng trưởng, cơ cấu sản phẩm) và tạm trích chiết khấu',
    'version': '1.0.0',
    'category': 'Accounting/Accounting',
    'author': 'Arrowhitech',
    'license': 'LGPL-3',
    'depends': ['rebate_base'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/rebate_control_views.xml',
    ],
    'installable': True,
}
