from odoo import models


class RebateSettlement(models.Model):
    _inherit = 'rebate.settlement'

    def _rebate_apply_conditions(self, lines, evaluation):
        res = super()._rebate_apply_conditions(lines, evaluation)
        base = sum(lines.mapped('amount'))
        for cond in self.agreement_id.condition_ids:
            ok, message = cond._evaluate(self, lines, evaluation)
            if cond.effect == 'bonus':
                if ok:
                    res['bonus'] += base * cond.effect_value / 100.0
                    message += self.env._(' → thưởng thêm %g%%', cond.effect_value)
                res['messages'].append((True, message) if ok else (False, message))
                continue
            if not ok:
                if cond.effect == 'block':
                    res['blocked'] = True
                    message += self.env._(' → không được hưởng')
                else:
                    res['factor'] *= max(0.0, 1 - cond.effect_value / 100.0)
                    message += self.env._(' → giảm %g%%', cond.effect_value)
            res['messages'].append((ok, message))
        return res

    def _rebate_after_done(self):
        res = super()._rebate_after_done()
        self.env['rebate.accrual']._release_for_settlement(self)
        return res
