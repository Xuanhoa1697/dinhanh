"""Pure-Python rebate calculation engine.

No Odoo import here on purpose: the functions can be unit-tested anywhere and
are the single source of truth for every computation made by the modules
(progress, accrual, settlement, simulation).
"""
from dataclasses import dataclass, field

INF = float('inf')


@dataclass
class Tier:
    from_value: float
    to_value: float = 0.0  # 0 / None => unbounded
    value: float = 0.0

    @property
    def upper(self):
        return self.to_value if self.to_value else INF


@dataclass
class TierResult:
    amount: float = 0.0
    tier_index: int = -1          # index of the highest tier reached (-1: none)
    tier_value: float = 0.0
    breakdown: list = field(default_factory=list)  # [(tier_index, portion_measure, amount)]
    next_tier_gap: float = 0.0    # measure still missing to reach the next tier (0: none)
    capped: bool = False


def sort_tiers(tiers):
    return sorted(tiers, key=lambda t: t.from_value)


def check_tiers(tiers):
    """Return a list of error strings: overlapping or inverted tiers."""
    errors = []
    tiers = sort_tiers(tiers)
    for i, tier in enumerate(tiers):
        if tier.to_value and tier.to_value <= tier.from_value:
            errors.append(f"Bậc {i + 1}: 'đến' phải lớn hơn 'từ'.")
        if i + 1 < len(tiers):
            nxt = tiers[i + 1]
            if tier.upper > nxt.from_value:
                errors.append(f"Bậc {i + 1} và {i + 2} chồng nhau.")
    return errors


def reached_index(measure, tiers):
    idx = -1
    for i, tier in enumerate(tiers):
        if measure >= tier.from_value:
            idx = i
    return idx


def compute_tier_amount(measure, amount_base, qty_base, tiers, tier_mode='retro',
                        value_type='percent', min_threshold=0.0, cap=0.0):
    """Compute the rebate for one rule.

    :param measure: value compared with the tier thresholds (qty, amount, weight…)
    :param amount_base: monetary base the percentage applies to
    :param qty_base: quantity the per-unit value applies to
    :param tier_mode: 'retro' (rate of the reached tier on everything) or
                      'progressive' (each slice gets the rate of its tier)
    :param value_type: 'percent' | 'amount' (fixed sum) | 'per_unit'
    """
    tiers = sort_tiers(tiers)
    res = TierResult()
    if not tiers or measure <= 0 or measure < (min_threshold or 0.0):
        if tiers and measure < tiers[0].from_value:
            res.next_tier_gap = tiers[0].from_value - max(measure, 0.0)
        return res

    idx = reached_index(measure, tiers)
    res.tier_index = idx
    if idx + 1 < len(tiers):
        res.next_tier_gap = tiers[idx + 1].from_value - measure
    if idx < 0:
        return res
    res.tier_value = tiers[idx].value

    def slice_amount(fraction, value):
        if value_type == 'percent':
            return amount_base * fraction * value / 100.0
        if value_type == 'per_unit':
            return qty_base * fraction * value
        return value  # fixed amount

    if tier_mode == 'progressive':
        total = 0.0
        for i, tier in enumerate(tiers[:idx + 1]):
            portion = max(0.0, min(measure, tier.upper) - tier.from_value)
            if portion <= 0 and value_type != 'amount':
                continue
            fraction = portion / measure if measure else 0.0
            amt = slice_amount(fraction, tier.value)
            res.breakdown.append((i, portion, amt))
            total += amt
        res.amount = total
    else:
        res.amount = slice_amount(1.0, tiers[idx].value)
        res.breakdown.append((idx, measure, res.amount))

    if cap and res.amount > cap:
        res.amount = cap
        res.capped = True
    return res


def allocate(total, weights, digits=2):
    """Split ``total`` proportionally to ``weights``.

    Rounded per item; the rounding difference is pushed onto the item with the
    largest absolute weight so that ``sum(result) == round(total)`` exactly.
    """
    n = len(weights)
    if not n:
        return []
    total = round(total, digits)
    wsum = sum(weights)
    if not wsum:
        return [0.0] * n
    result = [round(total * w / wsum, digits) for w in weights]
    diff = round(total - sum(result), digits)
    if diff:
        k = max(range(n), key=lambda i: abs(weights[i]))
        result[k] = round(result[k] + diff, digits)
    return result


def split_inventory(amount, qty_in, qty_remaining, qty_consumed=0.0, digits=2):
    """Split a purchase rebate between stock still on hand, goods consumed in
    production / expenses and goods already sold (COGS).

    :return: dict(to_inventory, to_consumed, to_cogs)
    """
    if not qty_in:
        return {'to_inventory': 0.0, 'to_consumed': 0.0, 'to_cogs': round(amount, digits)}
    qty_remaining = max(0.0, min(qty_remaining, qty_in))
    qty_consumed = max(0.0, min(qty_consumed, qty_in - qty_remaining))
    to_inv = round(amount * qty_remaining / qty_in, digits)
    to_cons = round(amount * qty_consumed / qty_in, digits)
    to_cogs = round(amount - to_inv - to_cons, digits)
    return {'to_inventory': to_inv, 'to_consumed': to_cons, 'to_cogs': to_cogs}


def segment_amount(segments, total_measure, tiers_by_segment, tier_mode, value_type,
                   min_threshold=0.0, cap=0.0):
    """Mid-period change computed by segment (TH-11).

    The tier is decided on the whole-period measure; each segment is paid with
    the rates of the version valid for that segment, pro-rata to its share.

    :param segments: list of (key, measure, amount_base, qty_base)
    :param tiers_by_segment: dict key -> list[Tier]
    """
    total = 0.0
    details = {}
    for key, seg_measure, seg_amount, seg_qty in segments:
        if not total_measure:
            continue
        share = seg_measure / total_measure
        res = compute_tier_amount(total_measure, seg_amount / share if share else 0.0,
                                  seg_qty / share if share else 0.0, tiers_by_segment[key],
                                  tier_mode, value_type, min_threshold, 0.0)
        amt = res.amount * share
        details[key] = amt
        total += amt
    if cap and total > cap:
        ratio = cap / total
        details = {k: v * ratio for k, v in details.items()}
        total = cap
    return total, details
