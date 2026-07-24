from datetime import date, datetime
import pytest
from scanner.d1client import SqliteD1Client
from scanner.model import Bar, TZ
from scanner.orchestrate import ensure_run_state, run_once, is_trading_closed
from tests.conftest import make_series


class FakeSource:
    def __init__(self, name, days_map):
        self.name = name
        self._bars = make_series(days_map)
    def fetch_15min(self, symbol, days=5):
        return self._bars


def _fresh_client():
    c = SqliteD1Client(":memory:")
    c.execute(open("migrations/0001_init.sql").read())
    return c


def test_ensure_run_state_initializes_once():
    c = _fresh_client()
    uni = [{"symbol": f"{i:06d}", "pools": ["hs300"]} for i in range(1, 8)]
    st = ensure_run_state(c, "2026-07-24", uni, batch_size=3)
    assert st["total_batches"] == 3 and st["next_batch"] == 0 and st["status"] == "running"
    st2 = ensure_run_state(c, "2026-07-24", uni, batch_size=3)   # 幂等
    assert st2["next_batch"] == 0


def test_run_once_advances_cursor_and_writes(monkeypatch):
    c = _fresh_client()
    uni = [{"symbol": f"{i:06d}", "pools": ["hs300"]} for i in range(1, 8)]
    meta = {r["symbol"]: {"name": r["symbol"], "pool": "hs300"} for r in uni}
    # 让每只都命中:monkeypatch evaluate_symbol 返回 hit
    import scanner.orchestrate as orch
    from scanner.model import ScanResult
    def fake_scan(symbols, sources, target_date, fail_ratio=0.05):
        res = [ScanResult(s, True, "all_above", "all_below", "confirmed", 1.0,
                          {f"{k}_{t}":1.0 for k in ("a","b") for t in ("1030","1130","1400","1500")})
               for s in symbols]
        return res, {"total": len(res), "hits": len(res), "bad": 0, "bad_ratio": 0.0}
    monkeypatch.setattr(orch, "scan_symbols", fake_scan)
    for _ in range(3):
        run_once(c, sources=[], universe=uni, meta=meta,
                 trade_date="2026-07-24", created_at="t", batch_size=3)
    assert c.query("SELECT status FROM run_state;")[0]["status"] == "done"
    assert c.query("SELECT COUNT(*) n FROM signals;")[0]["n"] == 7
    assert c.query("SELECT COUNT(*) n FROM sample_daily;")[0]["n"] == 7


def test_run_once_whole_day_bad_ratio_raises_after_cursor_done(monkeypatch):
    """I1: 单批次内 scan_symbols 绝不因质量抛错(fail_ratio=1.0),游标必须推进到底。
    质量把关放到整天粒度:最后一批把游标置 'done'、把所有行落库之后才检查,
    发现整体 bad_ratio 超阈值就抛错——但此时游标已经是 'done'、数据已经写入
    (不是卡在半路),重跑只会 no-op(幂等),这次完成本次的 run 置红用于 CI 可见。"""
    c = _fresh_client()
    uni = [{"symbol": f"{i:06d}", "pools": ["hs300"]} for i in range(1, 8)]
    meta = {r["symbol"]: {"name": r["symbol"], "pool": "hs300"} for r in uni}
    import scanner.orchestrate as orch
    from scanner.model import ScanResult

    def fake_scan_all_bad(symbols, sources, target_date, fail_ratio=0.05):
        res = [ScanResult(s, False, "incomplete", "incomplete", "data_unavailable", None, {})
               for s in symbols]
        return res, {"total": len(res), "hits": 0, "bad": len(res), "bad_ratio": 1.0}

    monkeypatch.setattr(orch, "scan_symbols", fake_scan_all_bad)

    # 3 个批次(batch_size=3, 7 支股票):前两批非最终批,绝不应该抛错。
    for _ in range(2):
        res = run_once(c, sources=[], universe=uni, meta=meta,
                        trade_date="2026-07-24", created_at="t", batch_size=3)
        assert res["status"] == "running"

    # 最后一批:游标置 done + 全部落库之后,整天 bad_ratio=100% > 5% → 抛错。
    with pytest.raises(RuntimeError):
        run_once(c, sources=[], universe=uni, meta=meta,
                 trade_date="2026-07-24", created_at="t", batch_size=3)

    # 抛错发生在游标推进、数据落库之后:不是卡死(wedge),重跑会 no-op。
    assert c.query("SELECT status FROM run_state;")[0]["status"] == "done"
    assert c.query("SELECT next_batch FROM run_state;")[0]["next_batch"] == 3
    assert c.query("SELECT COUNT(*) n FROM sample_daily;")[0]["n"] == 7

    # 重跑 no-op(green):cursor 已 done,不再触发扫描/质量检查。
    res2 = run_once(c, sources=[], universe=uni, meta=meta,
                     trade_date="2026-07-24", created_at="t", batch_size=3)
    assert res2 == {"status": "done", "note": "already done"}


class _FetchOnceSource:
    """I2 测试用:fetch_15min 返回预设 bars 或抛异常。"""
    def __init__(self, name, bars=None, raises=False):
        self.name = name
        self._bars = bars or []
        self._raises = raises

    def fetch_15min(self, symbol, days=2):
        if self._raises:
            raise ConnectionError(f"{self.name} unreachable")
        return self._bars


def test_is_trading_closed_true_when_any_benchmark_source_hits_15h00():
    d = date(2026, 7, 24)
    bars_with_close = make_series({d: [10.0 + i for i in range(16)]})
    ok_src = _FetchOnceSource("tencent", bars=bars_with_close)
    bad_src = _FetchOnceSource("sina", raises=True)
    assert is_trading_closed([bad_src, ok_src], ["600519", "000001"], d) is True


def test_is_trading_closed_false_when_data_present_but_no_15h00_bar():
    d = date(2026, 7, 24)
    # 有数据抓取成功,但没有当日 15:00 这根 bar(比如还没收盘,或非交易日)。
    partial_bars = [Bar(datetime(d.year, d.month, d.day, 14, 45, tzinfo=TZ), 10.0)]
    src = _FetchOnceSource("tencent", bars=partial_bars)
    assert is_trading_closed([src], ["600519", "000001", "300750", "688981"], d) is False


def test_is_trading_closed_raises_when_all_sources_raise():
    d = date(2026, 7, 24)
    src1 = _FetchOnceSource("tencent", raises=True)
    src2 = _FetchOnceSource("sina", raises=True)
    with pytest.raises(RuntimeError):
        is_trading_closed([src1, src2], ["600519", "000001", "300750", "688981"], d)
