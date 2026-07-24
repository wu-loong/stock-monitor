from scanner.model import SAMPLE_TIMES, HOURLY_WINDOW, MIN15_WINDOW, EPS


def sma(values, window):
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def hhmm(dt):
    return dt.strftime("%H:%M")


def sample_index(bars, d, t):
    """bars 升序;返回日期==d 且时间==t 的下标,找不到返回 None。"""
    for i, b in enumerate(bars):
        if b.dt.date() == d and hhmm(b.dt) == t:
            return i
    return None


def windows_for(bars, i):
    """返回 (w15_idx, w60_idx):15分MA20 用的 20 个下标 + 60分MA5 用的 5 个下标。
    历史不足则返回 None。60分序列 = 时间 ∈ SAMPLE_TIMES 的 bar。"""
    if i - (MIN15_WINDOW - 1) < 0:
        return None
    w15 = list(range(i - MIN15_WINDOW + 1, i + 1))
    hourly = [j for j in range(0, i + 1) if hhmm(bars[j].dt) in SAMPLE_TIMES]
    if len(hourly) < HOURLY_WINDOW:
        return None
    w60 = hourly[-HOURLY_WINDOW:]
    return w15, w60


def _ab_at(bars, i):
    """返回该采样点 (a=60分MA5, b=15分MA20);任一所需 close 为 None → (None,None)。"""
    win = windows_for(bars, i)
    if win is None:
        return None, None
    w15, w60 = win
    v15 = [bars[j].close for j in w15]
    v60 = [bars[j].close for j in w60]
    if any(v is None for v in v15) or any(v is None for v in v60):
        return None, None
    return sma(v60, HOURLY_WINDOW), sma(v15, MIN15_WINDOW)


def state_for_date(bars, d):
    pairs = []
    for t in SAMPLE_TIMES:
        i = sample_index(bars, d, t)
        if i is None:
            return "incomplete"
        a, b = _ab_at(bars, i)
        if a is None or b is None:
            return "incomplete"
        pairs.append((a, b))
    if all(b - a > EPS for a, b in pairs):
        return "all_below"
    if all(a - b > EPS for a, b in pairs):
        return "all_above"
    return "mixed"
