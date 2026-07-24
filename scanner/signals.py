from scanner.indicators import state_for_date


def detect_hit(bars, target_date):
    """T-1 = target_date 之前最近的有 bar 的交易日。
    命中 ⟺ state(T-1)==all_below 且 state(T)==all_above。"""
    dates = sorted({b.dt.date() for b in bars})
    prev_candidates = [d for d in dates if d < target_date]
    if not prev_candidates:
        return False, None
    prev = prev_candidates[-1]
    hit = (state_for_date(bars, prev) == "all_below"
           and state_for_date(bars, target_date) == "all_above")
    return hit, prev
