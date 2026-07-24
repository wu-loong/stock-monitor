from datetime import date, datetime
import scanner.indicators as ind
import scanner.signals as sig
from scanner.model import Bar, TZ
from scanner.evaluate import evaluate_symbol
from tests.conftest import make_day, make_series


def _b(d, hh, mm, c):
    return Bar(datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ), c)


def test_conflict_bar_forces_unavailable_or_conflict():
    # 目标日某采样点两源冲突 → 质量非 confirmed,hit=False
    d0, d1, d2, d3, dT = (date(2026,7,15), date(2026,7,16), date(2026,7,17),
                          date(2026,7,18), date(2026,7,21))
    days = {d: [10.0]*16 for d in (d0,d1,d2,d3,dT)}
    east = make_series(days)
    tx = make_series(days)
    # 篡改 tx 在 dT 10:30 的价,制造冲突
    tx = [Bar(b.dt, (b.close+5.0 if (b.dt.date()==dT and b.dt.strftime('%H:%M')=='10:30') else b.close))
          for b in tx]
    r = evaluate_symbol("000001", {"east": east, "tx": tx}, dT)
    assert r.quality in ("data_conflict", "data_unavailable")
    assert r.hit is False


def test_missing_history_unavailable():
    dT = date(2026,7,21)
    east = make_series({dT: [10.0]*16})   # 只有目标日一天,窗口不足
    r = evaluate_symbol("000001", {"east": east}, dT)
    assert r.quality == "data_unavailable"
    assert r.hit is False


def test_hit_wiring_with_forced_states(monkeypatch):
    # 真实"前日全小于→今日全大于"信号极严格、难用平滑价格构造(见设计:60分MA5 尾部5小时
    # 窗口跨日)。state 的数学正确性已在 test_indicators 用严格单调序列验证;此处只验证
    # evaluate 把 state/命中/质量正确接线:monkeypatch 强制两天状态,数据充足使 computable=True。
    d_prev, dT = date(2026, 7, 20), date(2026, 7, 21)
    dates = [date(2026,7,13), date(2026,7,14), date(2026,7,15), date(2026,7,16), d_prev, dT]
    east = make_series({d: [10.0]*16 for d in dates})   # 6 天 → 窗口填满 → computable
    forced = {d_prev: "all_below", dT: "all_above"}
    # evaluate 内部 `from scanner.indicators import state_for_date`(调用时取值)→ patch ind;
    # detect_hit 在 signals 模块加载时已绑定该名 → 同时 patch sig。
    monkeypatch.setattr(ind, "state_for_date", lambda bars, d: forced.get(d, "mixed"))
    monkeypatch.setattr(sig, "state_for_date", lambda bars, d: forced.get(d, "mixed"))
    r = evaluate_symbol("000001", {"east": east}, dT)
    assert r.state_prev == "all_below"
    assert r.state_t == "all_above"
    assert r.hit is True
    assert r.quality == "unverified"   # 单源 → unverified,但仍算命中
