from datetime import date
from scanner.signals import detect_hit
from tests.conftest import make_series

# 构造:T-1 全部 A<B(all_below),T 全部 A>B(all_above)
# 价格形态:前段平稳使快线(15分MA20)高于慢线(60分MA5)→ all_below;
# 目标日大幅高开走高使 60分MA5 反超 → all_above。用 Task6 的集成夹具更稳,这里用直接构造的状态桩。


def test_detect_hit_true(monkeypatch):
    import scanner.signals as sig
    seq = {date(2026,7,21): "all_below", date(2026,7,22): "all_above"}
    monkeypatch.setattr(sig, "state_for_date", lambda bars, d: seq[d])
    bars = make_series({date(2026,7,21): [1.0]*16, date(2026,7,22): [1.0]*16})
    hit, prev = detect_hit(bars, date(2026,7,22))
    assert hit is True and prev == date(2026,7,21)


def test_detect_hit_false_when_prev_mixed(monkeypatch):
    import scanner.signals as sig
    seq = {date(2026,7,21): "mixed", date(2026,7,22): "all_above"}
    monkeypatch.setattr(sig, "state_for_date", lambda bars, d: seq[d])
    bars = make_series({date(2026,7,21): [1.0]*16, date(2026,7,22): [1.0]*16})
    hit, prev = detect_hit(bars, date(2026,7,22))
    assert hit is False and prev == date(2026,7,21)


def test_detect_hit_false_when_no_prev_day():
    bars = make_series({date(2026,7,22): [1.0]*16})
    hit, prev = detect_hit(bars, date(2026,7,22))
    assert hit is False and prev is None
