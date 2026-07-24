import json
from scanner.scan import scan_symbols
from scanner.persist import results_to_sql, sql_escape
from scanner.indicators import sample_index


def is_trading_closed(sources, benchmark, target_date):
    """target_date(date) 当日基准股是否已有 15:00 bar。任一源命中即 True。"""
    for src in sources:
        try:
            bars = src.fetch_15min(benchmark, days=2)
        except Exception:
            continue
        if sample_index(bars, target_date, "15:00") is not None:
            return True
    return False


def ensure_run_state(client, trade_date, universe, batch_size):
    rows = client.query(f"SELECT * FROM run_state WHERE trade_date={sql_escape(trade_date)};")
    if rows:
        return rows[0]
    syms = [r["symbol"] for r in universe]
    total = (len(syms) + batch_size - 1) // batch_size
    uni_json = json.dumps(syms)
    client.execute(
        f"INSERT INTO run_state (trade_date, universe_json, total_batches, next_batch, status, updated_at) "
        f"VALUES ({sql_escape(trade_date)}, {sql_escape(uni_json)}, {total}, 0, {sql_escape('running')}, {sql_escape(trade_date)});")
    return client.query(f"SELECT * FROM run_state WHERE trade_date={sql_escape(trade_date)};")[0]


def run_batch(client, sources, universe, meta, trade_date, created_at, batch_size):
    st = client.query(f"SELECT * FROM run_state WHERE trade_date={sql_escape(trade_date)};")[0]
    if st["status"] == "done":
        return {"status": "done", "note": "already done"}
    nb = st["next_batch"]
    syms = [r["symbol"] for r in universe]
    batch = syms[nb * batch_size:(nb + 1) * batch_size]
    results, summary = scan_symbols(batch, sources, _to_date(trade_date))
    sql = results_to_sql(results, trade_date, meta, created_at)
    if sql.strip():
        client.execute(sql)
    nb += 1
    status = "done" if nb >= st["total_batches"] else "running"
    client.execute(
        f"UPDATE run_state SET next_batch={nb}, status={sql_escape(status)}, updated_at={sql_escape(created_at)} "
        f"WHERE trade_date={sql_escape(trade_date)};")
    return {"status": status, "batch": nb - 1, "summary": summary}


def run_once(client, sources, universe, meta, trade_date, created_at, batch_size):
    ensure_run_state(client, trade_date, universe, batch_size)
    return run_batch(client, sources, universe, meta, trade_date, created_at, batch_size)


def _to_date(s):
    from datetime import date
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)
