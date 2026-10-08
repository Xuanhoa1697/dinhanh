"""T02 – Bộ kịch bản mẫu (golden scenarios).

Dùng chung cho:
- unit test thuần Python (tests/test_engine.py) và test Odoo,
- file Excel docs/kich_ban_mau.xlsx để kế toán xác nhận số kết quả.
Số tiền tính bằng VND.
"""

TIERS_3 = [(0, 1_000_000_000, 0.0), (1_000_000_000, 2_000_000_000, 1.0), (2_000_000_000, 0, 2.0)]

SCENARIOS = [
    {
        'code': 'S01', 'th': 'TH-01', 'name': 'Bậc hồi tố – doanh số 2,5 tỷ',
        'kind': 'tier', 'measure': 2_500_000_000, 'amount': 2_500_000_000, 'qty': 0,
        'tiers': TIERS_3, 'tier_mode': 'retro', 'value_type': 'percent',
        'expected': 50_000_000,
        'note': '2,5 tỷ × 2%',
    },
    {
        'code': 'S02', 'th': 'TH-02', 'name': 'Bậc lũy tiến – doanh số 2,5 tỷ',
        'kind': 'tier', 'measure': 2_500_000_000, 'amount': 2_500_000_000, 'qty': 0,
        'tiers': TIERS_3, 'tier_mode': 'progressive', 'value_type': 'percent',
        'expected': 20_000_000,
        'note': '1 tỷ × 0% + 1 tỷ × 1% + 0,5 tỷ × 2%',
    },
    {
        'code': 'S03', 'th': 'TH-03', 'name': 'Theo số lượng – 2.000 đ/thùng khi trên 10.000 thùng',
        'kind': 'tier', 'measure': 12_000, 'amount': 1_800_000_000, 'qty': 12_000,
        'tiers': [(10_000, 0, 2_000)], 'tier_mode': 'retro', 'value_type': 'per_unit',
        'expected': 24_000_000,
        'note': '12.000 thùng × 2.000 đ',
    },
    {
        'code': 'S04', 'th': 'TH-04', 'name': 'Số tiền cố định khi đạt 5 tỷ',
        'kind': 'tier', 'measure': 5_200_000_000, 'amount': 5_200_000_000, 'qty': 0,
        'tiers': [(5_000_000_000, 0, 100_000_000)], 'tier_mode': 'retro', 'value_type': 'amount',
        'expected': 100_000_000,
        'note': 'Đạt ngưỡng 5 tỷ → thưởng 100 triệu',
    },
    {
        'code': 'S05', 'th': 'TH-15', 'name': 'Không đạt bậc đầu tiên – 0,8 tỷ',
        'kind': 'tier', 'measure': 800_000_000, 'amount': 800_000_000, 'qty': 0,
        'tiers': TIERS_3[1:], 'tier_mode': 'retro', 'value_type': 'percent',
        'expected': 0,
        'note': 'Chưa đạt 1 tỷ → 0',
    },
    {
        'code': 'S06', 'th': 'TH-15', 'name': 'Ngưỡng tối thiểu 1,5 tỷ, đạt 1,2 tỷ',
        'kind': 'tier', 'measure': 1_200_000_000, 'amount': 1_200_000_000, 'qty': 0,
        'tiers': TIERS_3, 'tier_mode': 'retro', 'value_type': 'percent', 'min_threshold': 1_500_000_000,
        'expected': 0,
        'note': 'Dưới ngưỡng tối thiểu → 0',
    },
    {
        'code': 'S07', 'th': '–', 'name': 'Trần 40 triệu',
        'kind': 'tier', 'measure': 2_500_000_000, 'amount': 2_500_000_000, 'qty': 0,
        'tiers': TIERS_3, 'tier_mode': 'retro', 'value_type': 'percent', 'cap': 40_000_000,
        'expected': 40_000_000,
        'note': '50 triệu bị giới hạn ở 40 triệu',
    },
    {
        'code': 'S08', 'th': 'TH-13', 'name': 'Trả hàng làm tụt bậc: bán 2,5 tỷ, trả 0,6 tỷ',
        'kind': 'tier', 'measure': 1_900_000_000, 'amount': 1_900_000_000, 'qty': 0,
        'tiers': TIERS_3, 'tier_mode': 'retro', 'value_type': 'percent',
        'expected': 19_000_000,
        'note': '(2,5 − 0,6) tỷ × 1%',
    },
    {
        'code': 'S09', 'th': 'TH-03', 'name': 'Ngưỡng theo số lượng, chiết khấu % doanh số',
        'kind': 'tier', 'measure': 12_000, 'amount': 1_800_000_000, 'qty': 12_000,
        'tiers': [(10_000, 0, 2.0)], 'tier_mode': 'retro', 'value_type': 'percent',
        'expected': 36_000_000,
        'note': 'Đạt 10.000 thùng → 2% × 1,8 tỷ',
    },
    {
        'code': 'S10', 'th': 'TH-19', 'name': 'Phân bổ 50 triệu về 3 hóa đơn, 2 thuế suất',
        'kind': 'allocate', 'total': 50_000_000,
        'weights': [1_000_000_000, 800_000_000, 700_000_000], 'tax_rates': [10, 8, 10], 'digits': 0,
        'expected': [20_000_000, 16_000_000, 14_000_000],
        'expected_tax': [2_000_000, 1_280_000, 1_400_000],
        'note': 'Theo tỷ trọng giá trị; thuế theo thuế suất hóa đơn gốc',
    },
    {
        'code': 'S11', 'th': '–', 'name': 'Làm tròn: 100 đ chia 3 hóa đơn bằng nhau',
        'kind': 'allocate', 'total': 100, 'weights': [1, 1, 1], 'tax_rates': [0, 0, 0], 'digits': 0,
        'expected': [34, 33, 33], 'expected_tax': [0, 0, 0],
        'note': 'Phần chênh dồn vào dòng lớn nhất (dòng đầu khi bằng nhau)',
    },
    {
        'code': 'S12', 'th': 'TH-23', 'name': 'CK mua 30 triệu: nhập 10.000, còn tồn 3.000',
        'kind': 'inventory', 'total': 30_000_000, 'qty_in': 10_000, 'qty_remaining': 3_000, 'qty_consumed': 0,
        'expected': {'to_inventory': 9_000_000, 'to_consumed': 0, 'to_cogs': 21_000_000},
        'note': '30% vào 156, 70% vào 632',
    },
    {
        'code': 'S13', 'th': 'TH-11', 'name': 'Đổi tỷ lệ giữa kỳ, tính theo đoạn',
        'kind': 'segment', 'total_measure': 2_500_000_000,
        'segments': [('v1', 1_000_000_000, 1_000_000_000, 0), ('v2', 1_500_000_000, 1_500_000_000, 0)],
        'tiers_by_segment': {
            'v1': [(1_000_000_000, 2_000_000_000, 1.0), (2_000_000_000, 0, 2.0)],
            'v2': [(1_000_000_000, 2_000_000_000, 1.0), (2_000_000_000, 0, 2.5)],
        },
        'tier_mode': 'retro', 'value_type': 'percent',
        'expected': 57_500_000,
        'note': 'Bậc xác định trên cả kỳ (2,5 tỷ); 1 tỷ × 2% + 1,5 tỷ × 2,5%',
    },
    {
        'code': 'S14', 'th': 'TH-07', 'name': 'Trả theo quý, quyết toán năm',
        'kind': 'trueup',
        'quarters': [400_000_000, 600_000_000, 700_000_000, 800_000_000],
        'quarter_tiers': [(500_000_000, 0, 1.0)],
        'year_tiers': [(1_000_000_000, 2_000_000_000, 1.0), (2_000_000_000, 0, 2.0)],
        'expected': 29_000_000,
        'note': 'Năm 2,5 tỷ × 2% = 50 triệu − đã trả quý (0 + 6 + 7 + 8 triệu) = 29 triệu',
    },
]
