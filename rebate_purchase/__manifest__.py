{
    'name': 'Chiết khấu cuối kỳ – Mua hàng',
    'summary': 'Đối chiếu hóa đơn điều chỉnh của NCC, khiếu nại chênh lệch, phân bổ CK vào tồn kho và giá vốn',
    'version': '1.0.0',
    'category': 'Accounting/Accounting',
    'author': 'Arrowhitech',
    'license': 'LGPL-3',
    'depends': ['rebate_base', 'purchase_stock', 'stock_account'],
    'data': [
        'security/ir.model.access.csv',
        'views/rebate_purchase_views.xml',
    ],
    'installable': True,
}
