"""Selection values shared by templates and agreements (configuration tier 2/3)."""

DIRECTION = [('sale', 'Bán hàng'), ('purchase', 'Mua hàng')]
NATURE = [
    ('trade', 'Chiết khấu thương mại'),
    ('support', 'Hỗ trợ / thưởng không gắn hàng hóa'),
]
PERIOD_TYPE = [
    ('month', 'Tháng'),
    ('quarter', 'Quý'),
    ('half', 'Nửa năm'),
    ('year', 'Năm'),
    ('whole', 'Toàn bộ thời hạn thỏa thuận'),
    ('year_quarter', 'Năm, trả tạm theo quý'),
    ('year_month', 'Năm, trả tạm theo tháng'),
]
SETTLEMENT_DOC = [
    ('adjust_invoice', 'HĐ điều chỉnh giảm kèm bảng kê'),
    ('next_invoice', 'Trừ trên hóa đơn kỳ sau'),
    ('credit_note', 'Credit note (đối tác nước ngoài)'),
    ('voucher', 'Chứng từ thu / chi (không hóa đơn)'),
    ('none', 'Không lập chứng từ'),
]
PAYMENT_METHOD = [
    ('offset', 'Bù trừ công nợ'),
    ('cash', 'Chi / thu tiền'),
    ('next_invoice', 'Trừ vào hóa đơn kỳ sau'),
]
ALLOCATION_KEY = [('amount', 'Theo giá trị'), ('qty', 'Theo số lượng')]
COGS_SPLIT = [
    ('method', 'Theo phương pháp giá của sản phẩm'),
    ('all_cogs', 'Toàn bộ vào giá vốn'),
]
RETURN_PERIOD_RULE = [('origin', 'Kỳ của hóa đơn gốc'), ('refund', 'Kỳ phát sinh trả hàng')]
POST_CLOSE_RECALC = [
    ('recalc', 'Tính lại, lập quyết toán chênh lệch'),
    ('lock', 'Khóa, ghi vào kỳ đang mở'),
]
NEGATIVE_TRUE_UP = [('ignore', 'Không thu hồi'), ('recover', 'Thu hồi phần trả thừa')]
MID_PERIOD_CHANGE = [('segment', 'Tính theo từng đoạn'), ('last', 'Áp phiên bản cuối cho cả kỳ')]
STACKING = [('cumulative', 'Cộng dồn'), ('exclusive', 'Loại trừ chương trình ưu tiên thấp hơn')]
BASIS = [
    ('amount', 'Doanh số sau CK dòng (chưa thuế)'),
    ('amount_gross', 'Doanh số trước CK dòng (chưa thuế)'),
    ('qty', 'Số lượng'),
    ('weight', 'Trọng lượng'),
]
TIER_MODE = [('retro', 'Hồi tố'), ('progressive', 'Lũy tiến')]
VALUE_TYPE = [
    ('percent', '% doanh số'),
    ('amount', 'Số tiền cố định khi đạt'),
    ('per_unit', 'Đơn giá / đơn vị'),
]
ACCRUAL_MODE = [
    ('none', 'Không tạm trích'),
    ('management', 'Sổ quản trị (chỉ tính số)'),
    ('gl', 'Ghi sổ cái'),
]

TEMPLATE_FIELDS = [
    'direction', 'nature', 'period_type', 'settlement_doc', 'payment_method', 'allocation_key',
    'cogs_split', 'return_period_rule', 'post_close_recalc', 'negative_true_up',
    'mid_period_change', 'stacking',
]
