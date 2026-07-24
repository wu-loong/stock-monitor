from scanner.model import SAMPLE_TIMES

_SAMPLE_COLS = [f"{k}_{t.replace(':', '')}" for t in SAMPLE_TIMES for k in ("a", "b")]


def sql_escape(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def results_to_sql(results, trade_date, meta, created_at):
    """meta[symbol] = {"name": str, "pool": str}。生成 sample_daily(全部)+ signals(仅命中)幂等 upsert。"""
    stmts = []
    for r in results:
        info = meta.get(r.symbol, {})
        name, pool = info.get("name"), info.get("pool", "")
        sample_vals = [sql_escape(r.samples.get(c)) for c in _SAMPLE_COLS]
        cols = (["trade_date", "symbol", "name", "pool"] + _SAMPLE_COLS
                + ["state_t", "state_prev", "data_quality"])
        vals = ([sql_escape(trade_date), sql_escape(r.symbol), sql_escape(name), sql_escape(pool)]
                + sample_vals + [sql_escape(r.state_t), sql_escape(r.state_prev), sql_escape(r.quality)])
        upd = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in ("trade_date", "symbol"))
        stmts.append(
            f"INSERT INTO sample_daily ({', '.join(cols)}) VALUES ({', '.join(vals)}) "
            f"ON CONFLICT(trade_date, symbol) DO UPDATE SET {upd};")
        if r.hit:
            scols = ["trade_date", "symbol", "name", "pool", "close", "data_quality", "created_at"]
            svals = [sql_escape(trade_date), sql_escape(r.symbol), sql_escape(name), sql_escape(pool),
                     sql_escape(r.close), sql_escape(r.quality), sql_escape(created_at)]
            supd = ", ".join(f"{c}=excluded.{c}" for c in scols if c not in ("trade_date", "symbol"))
            stmts.append(
                f"INSERT INTO signals ({', '.join(scols)}) VALUES ({', '.join(svals)}) "
                f"ON CONFLICT(trade_date, symbol) DO UPDATE SET {supd};")
    return "\n".join(stmts)
