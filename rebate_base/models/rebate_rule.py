import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

from . import selections as sel
from ..tools import engine

RULE_FREE_FIELDS = {'date_end', 'is_current', 'approved', 'sequence', 'active'}


class RebateRule(models.Model):
    _name = 'rebate.rule'
    _description = 'Quy tắc chiết khấu cuối kỳ'
    _order = 'agreement_id, version desc, sequence, id'

    agreement_id = fields.Many2one('rebate.agreement', string='Thỏa thuận', required=True, ondelete='cascade',
                                   index=True)
    company_id = fields.Many2one(related='agreement_id.company_id', store=True)
    currency_id = fields.Many2one(related='agreement_id.currency_id')
    sequence = fields.Integer('Thứ tự', default=10)
    name = fields.Char('Tên quy tắc', required=True)
    active = fields.Boolean(default=True)
    key = fields.Char('Mã quy tắc', required=True, default=lambda self: uuid.uuid4().hex[:8], copy=False,
                      help='Giữ nguyên qua các phiên bản để so sánh và quyết toán.')
    version = fields.Integer('Phiên bản', default=1)
    date_start = fields.Date('Áp dụng từ')
    date_end = fields.Date('Áp dụng đến')
    approved = fields.Boolean('Đã duyệt', copy=False)
    is_current = fields.Boolean('Hiện hành', default=True)

    product_scope = fields.Selection([
        ('all', 'Tất cả sản phẩm'),
        ('category', 'Theo nhóm sản phẩm'),
        ('product', 'Theo danh sách sản phẩm'),
        ('domain', 'Theo điều kiện'),
    ], string='Phạm vi hàng hóa', required=True, default='all')
    product_categ_ids = fields.Many2many('product.category', 'rebate_rule_product_category_rel', 'rule_id',
                                         'categ_id', string='Nhóm sản phẩm')
    product_ids = fields.Many2many('product.product', 'rebate_rule_product_rel', 'rule_id', 'product_id',
                                   string='Sản phẩm')
    exclude_product_ids = fields.Many2many('product.product', 'rebate_rule_exclude_product_rel', 'rule_id',
                                           'product_id', string='Loại trừ sản phẩm')
    product_domain = fields.Char('Điều kiện sản phẩm', default='[]')

    basis = fields.Selection(sel.BASIS, string='Cơ sở tính', required=True, default='amount')
    uom_id = fields.Many2one('uom.uom', string='Đơn vị quy đổi',
                             help='Số lượng được quy đổi về đơn vị này trước khi cộng (để trống: ĐVT gốc).')
    tier_mode = fields.Selection(sel.TIER_MODE, string='Kiểu bậc', required=True, default='retro')
    value_type = fields.Selection(sel.VALUE_TYPE, string='Giá trị chiết khấu', required=True, default='percent')
    min_threshold = fields.Float('Ngưỡng tối thiểu', digits=(16, 2))
    cap_amount = fields.Monetary('Trần chiết khấu', currency_field='currency_id')
    tier_ids = fields.One2many('rebate.tier', 'rule_id', string='Bậc thang', copy=True)
    tier_summary = fields.Char('Bậc', compute='_compute_tier_summary')

    @api.depends('tier_ids.from_value', 'tier_ids.to_value', 'tier_ids.value', 'value_type')
    def _compute_tier_summary(self):
        unit = {'percent': '%', 'amount': '', 'per_unit': '/đv'}
        for rule in self:
            parts = []
            for t in rule.tier_ids.sorted('from_value'):
                parts.append('≥%s: %s%s' % ('{:,.0f}'.format(t.from_value), '{:,.2f}'.format(t.value).rstrip('0').rstrip('.'),
                                            unit[rule.value_type]))
            rule.tier_summary = ' | '.join(parts)

    @api.constrains('tier_ids')
    def _check_tiers(self):
        for rule in self:
            errors = engine.check_tiers(rule._engine_tiers())
            if errors:
                raise ValidationError('%s: %s' % (rule.name, ' '.join(errors)))

    @api.constrains('product_domain')
    def _check_domain(self):
        for rule in self.filtered(lambda r: r.product_scope == 'domain'):
            try:
                domain = safe_eval(rule.product_domain or '[]')
                self.env['product.product'].search_count(domain, limit=1)
            except Exception as e:  # noqa: BLE001
                raise ValidationError(self.env._('Điều kiện sản phẩm không hợp lệ: %s', e)) from e

    def write(self, vals):
        if not self.env.context.get('rebate_force') and set(vals) - RULE_FREE_FIELDS:
            if any(rule.approved for rule in self):
                raise UserError(self.env._('Quy tắc đã duyệt không sửa được. Hãy tạo phiên bản mới.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get('rebate_force') and any(rule.approved for rule in self):
            raise UserError(self.env._('Không xóa được quy tắc đã duyệt.'))
        return super().unlink()

    # ------------------------------------------------------------------
    def _engine_tiers(self):
        self.ensure_one()
        return [engine.Tier(t.from_value, t.to_value, t.value) for t in self.tier_ids]

    def _applies_on(self, on_date):
        self.ensure_one()
        return (self.approved
                and (not self.date_start or self.date_start <= on_date)
                and (not self.date_end or on_date <= self.date_end))

    def _matches_product(self, product):
        """T09 – product scope matcher."""
        self.ensure_one()
        if product and product in self.exclude_product_ids:
            return False
        scope = self.product_scope
        if scope == 'all':
            return True
        if not product:
            return False
        if scope == 'product':
            return product in self.product_ids
        if scope == 'category':
            path = product.categ_id.parent_path or ''
            return any(path.startswith(c.parent_path) for c in self.product_categ_ids if c.parent_path)
        if scope == 'domain':
            return bool(product.filtered_domain(safe_eval(self.product_domain or '[]')))
        return False

    def _convert_qty(self, qty, product):
        """T11 – convert a quantity in the product base UoM into the rule UoM."""
        self.ensure_one()
        if not self.uom_id or not product or product.uom_id == self.uom_id:
            return qty
        return product.uom_id._compute_quantity(qty, self.uom_id, round=False, raise_if_failure=False)


class RebateTier(models.Model):
    _name = 'rebate.tier'
    _description = 'Bậc chiết khấu'
    _order = 'from_value'

    rule_id = fields.Many2one('rebate.rule', required=True, ondelete='cascade', index=True)
    from_value = fields.Float('Từ (≥)', required=True, digits=(16, 2))
    to_value = fields.Float('Đến (<)', digits=(16, 2), help='0 = không giới hạn')
    value = fields.Float('Giá trị', required=True, digits=(16, 4),
                         help='% doanh số, số tiền cố định hoặc đơn giá / đơn vị tùy quy tắc.')

    def _check_editable(self):
        if not self.env.context.get('rebate_force') and any(t.rule_id.approved for t in self):
            raise UserError(self.env._('Bậc của quy tắc đã duyệt không sửa được. Hãy tạo phiên bản mới.'))

    @api.model_create_multi
    def create(self, vals_list):
        tiers = super().create(vals_list)
        tiers._check_editable()
        return tiers

    def write(self, vals):
        self._check_editable()
        return super().write(vals)

    def unlink(self):
        self._check_editable()
        return super().unlink()
