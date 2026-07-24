import pytest
from datetime import date
from scanner.model import Bar, TZ
from scanner.scan import scan_symbols, fetch_all_sources
from tests.conftest import make_series


class FakeSource:
    def __init__(self, name, days_map=None, fail=False):
        self.name = name
        self._bars = make_series(days_map) if days_map else []
        self._fail = fail

    def fetch_15min(self, symbol, days=5):
        if self._fail:
            raise ConnectionError("boom")
        return self._bars


def test_fetch_all_sources_skips_failures():
    good = FakeSource("east", {date(2026,7,21): [10.0]*16})
    bad = FakeSource("tx", fail=True)
    out = fetch_all_sources("000001", [good, bad], retries=2, sleep_s=0)
    assert "east" in out and len(out["east"]) == 16
    assert out["tx"] == []          # 失败源置空,不抛


def test_scan_symbols_raises_when_too_many_unavailable():
    # 所有股票都无数据 → 100% unavailable > 5% → 抛
    bad = FakeSource("east", fail=True)
    with pytest.raises(RuntimeError):
        scan_symbols(["000001", "000002"], [bad], date(2026,7,21), fail_ratio=0.05)
