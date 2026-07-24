from datetime import datetime, date, timedelta
from scanner.model import Bar, TZ

BAR_TIMES = ["09:45","10:00","10:15","10:30","10:45","11:00","11:15","11:30",
             "13:15","13:30","13:45","14:00","14:15","14:30","14:45","15:00"]


def make_day(d: date, closes: list[float]) -> list[Bar]:
    """按 16 根 15 分钟 bar 时刻,给定收盘价序列,生成一天的 Bar。"""
    assert len(closes) == 16
    out = []
    for t, c in zip(BAR_TIMES, closes):
        hh, mm = map(int, t.split(":"))
        out.append(Bar(datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ), float(c)))
    return out


def make_series(day_closes: dict) -> list[Bar]:
    """day_closes: {date: [16 closes]} → 按时间升序展平。"""
    bars = []
    for d in sorted(day_closes):
        bars.extend(make_day(d, day_closes[d]))
    return bars


def make_monotonic(dates: list, start: float = 100.0, step: float = 1.0) -> dict:
    """生成跨天严格单调的收盘序列:{date: [16 closes]}。
    step>0 → 全程递增(尾部5小时窗口上行,每个采样点 A>B → all_above);
    step<0 → 全程递减(→ all_below)。"""
    day_closes = {}
    i = 0
    for d in sorted(dates):
        day_closes[d] = [start + step * (i + k) for k in range(16)]
        i += 16
    return day_closes
