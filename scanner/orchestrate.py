import json
from scanner.scan import scan_symbols
from scanner.persist import results_to_sql, sql_escape
from scanner.indicators import sample_index


def is_trading_closed(sources, benchmarks: list[str], target_date):
    """target_date(date) 当日是否已有任一基准股在任一数据源出现 15:00 bar。
    任一 (benchmark, source) 命中 → True。
    未命中但至少一次抓取成功(有数据无 15:00 bar) → False(非交易日/未收盘,正常跳过)。
    所有 (benchmark, source) 组合均抛异常(零成功抓取) → 抛 RuntimeError,
    不静默吞掉数据源整体故障(区别于"非交易日"这种正常跳过)。"""
    any_success = False
    for benchmark in benchmarks:
        for src in sources:
            try:
                bars = src.fetch_15min(benchmark, days=2)
            except Exception:
                continue
            any_success = True
            if sample_index(bars, target_date, "15:00") is not None:
                return True
    if any_success:
        return False
    raise RuntimeError("data-source outage: no benchmark reachable")


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
    # fail_ratio=1.0:单批次内绝不因数据质量抛错——游标必须推进、结果必须落库,
    # 否则一批数据差就会把游标卡死,好数据也写不进去,当天永远跑不完。
    # 质量把关改为整天粒度(见下方 _check_whole_day_quality),在最后一批之后进行。
    results, summary = scan_symbols(batch, sources, _to_date(trade_date), fail_ratio=1.0)
    sql = results_to_sql(results, trade_date, meta, created_at)
    if sql.strip():
        client.execute(sql)
    nb += 1
    status = "done" if nb >= st["total_batches"] else "running"
    client.execute(
        f"UPDATE run_state SET next_batch={nb}, status={sql_escape(status)}, updated_at={sql_escape(created_at)} "
        f"WHERE trade_date={sql_escape(trade_date)};")
    if status == "done":
        _check_whole_day_quality(client, trade_date)
    return {"status": status, "batch": nb - 1, "summary": summary}


def _check_whole_day_quality(client, trade_date):
    """spec §8 整天粒度质量闸门:在游标已置 'done'、所有批次已落库之后检查。
    坏数据占比超阈值就抛错——此时游标已完成、数据已写入,重跑只会 no-op(绿),
    但完成本次的这次 run 会置红,保证 CI 可见性,不会卡住游标。"""
    row = client.query(
        f"SELECT COUNT(*) AS total, "
        f"SUM(CASE WHEN data_quality IN ('data_unavailable','data_conflict') THEN 1 ELSE 0 END) AS bad "
        f"FROM sample_daily WHERE trade_date={sql_escape(trade_date)};")[0]
    total, bad = row["total"], row["bad"] or 0
    if total and bad / total > 0.05:
        raise RuntimeError(f"whole-day bad ratio {bad}/{total}={bad/total:.1%} 超阈值 5%")


def run_once(client, sources, universe, meta, trade_date, created_at, batch_size):
    ensure_run_state(client, trade_date, universe, batch_size)
    return run_batch(client, sources, universe, meta, trade_date, created_at, batch_size)


def _to_date(s):
    from datetime import date
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)
