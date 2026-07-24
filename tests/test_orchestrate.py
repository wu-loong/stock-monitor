from datetime import date
from scanner.d1client import SqliteD1Client
from scanner.orchestrate import ensure_run_state, run_once
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
