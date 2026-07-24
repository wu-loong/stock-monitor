from datetime import date
from scanner.indicators import sma, sample_index, windows_for, state_for_date
from tests.conftest import make_series, make_monotonic, BAR_TIMES

DATES = [date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17)]


def test_sma_basic():
    assert sma([1, 2, 3, 4, 5], 5) == 3
    assert sma([1, 2], 5) is None


def test_sample_index_finds_1030():
    bars = make_series({date(2026, 7, 20): list(range(1, 17))})
    i = sample_index(bars, date(2026, 7, 20), "10:30")
    assert bars[i].dt.strftime("%H:%M") == "10:30"


def test_state_all_above_on_strictly_increasing():
    # 全程严格递增 → 每个采样点尾部5小时窗口上行 → 60分MA5 > 15分MA20 → all_above
    bars = make_series(make_monotonic(DATES, start=100.0, step=1.0))
    assert state_for_date(bars, DATES[-1]) == "all_above"


def test_state_all_below_on_strictly_decreasing():
    # 全程严格递减 → all_below
    bars = make_series(make_monotonic(DATES, start=300.0, step=-1.0))
    assert state_for_date(bars, DATES[-1]) == "all_below"


def test_state_incomplete_when_no_history():
    bars = make_series({date(2026, 7, 20): [10.0]*16})
    # 只有一天,15分MA20(需20根)在 10:30 只有4根 → incomplete
    assert state_for_date(bars, date(2026, 7, 20)) == "incomplete"
