from scanner.model import ScanResult
from scanner.persist import sql_escape, results_to_sql


def test_sql_escape():
    assert sql_escape(None) == "NULL"
    assert sql_escape(10.5) == "10.5"
    assert sql_escape("O'Brien") == "'O''Brien'"


def _r(sym, hit, quality):
    return ScanResult(symbol=sym, hit=hit, state_t="all_above", state_prev="all_below",
                      quality=quality, close=12.3,
                      samples={f"{k}_{t}": 1.0 for k in ("a", "b")
                               for t in ("1030", "1130", "1400", "1500")})


def test_results_to_sql_upserts_sample_and_signal():
    rows = [_r("600000", True, "confirmed"), _r("000001", False, "confirmed")]
    meta = {"600000": {"name": "浦发银行", "pool": "hs300"},
            "000001": {"name": "平安银行", "pool": "zz500"}}
    sql = results_to_sql(rows, "2026-07-24", meta, "2026-07-24T08:00:00Z")
    assert "INSERT INTO sample_daily" in sql
    assert sql.count("INSERT INTO sample_daily") == 2      # 每股一条明细
    assert sql.count("INSERT INTO signals") == 1           # 仅命中入 signals
    assert "ON CONFLICT(trade_date, symbol) DO UPDATE" in sql
    assert "浦发银行" in sql and "2026-07-24" in sql
