from datetime import datetime
from scanner.model import Bar, TZ
from scanner.crossvalidate import cross_validate


def _b(minute, close):
    return Bar(datetime(2026, 7, 22, 10, minute, tzinfo=TZ), close)


def test_confirmed_two_sources_agree():
    out = cross_validate({"east": [_b(30, 10.00)], "tx": [_b(30, 10.005)]})
    assert len(out) == 1 and out[0].quality == "confirmed"
    assert abs(out[0].close - 10.0) < 0.01


def test_unverified_single_source():
    out = cross_validate({"east": [_b(30, 10.00)]})
    assert out[0].quality == "unverified" and out[0].close == 10.00


def test_conflict_beyond_tol():
    out = cross_validate({"east": [_b(30, 10.00)], "tx": [_b(30, 10.50)]})
    assert out[0].quality == "conflict" and out[0].close is None


def test_conflict_when_third_source_disagrees():
    out = cross_validate({"east": [_b(30, 10.00)], "tx": [_b(30, 10.00)], "sina": [_b(30, 11.00)]})
    assert out[0].quality == "conflict"


def test_sorted_and_union_of_timestamps():
    out = cross_validate({"east": [_b(45, 1.0), _b(30, 1.0)], "tx": [_b(30, 1.0)]})
    assert [b.dt.strftime("%H:%M") for b in out] == ["10:30", "10:45"]
