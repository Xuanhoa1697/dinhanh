{
    'name': 'Chiết khấu cuối kỳ – Bán hàng',
    'summary': 'Hóa đơn điều chỉnh giảm kèm bảng kê, trừ hóa đơn kỳ sau, bù trừ công nợ khách hàng',
    'version': '1.0.0',
    'category': 'Accounting/Accounting',
    'author': 'Arrowhitech',
    'license': 'LGPL-3',
    'depends': ['rebate_base', 'sale'],
    'data': [
        'views/rebate_agreement_views.xml',
    ],
    'installable': True,
    'auto_install': False,
}
