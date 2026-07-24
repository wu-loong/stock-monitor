import time
from scanner.evaluate import evaluate_symbol


def fetch_all_sources(symbol, sources, retries=3, sleep_s=0.4):
    out = {}
    for src in sources:
        bars = []
        for attempt in range(retries):
            try:
                bars = src.fetch_15min(symbol, days=5)
                break
            except Exception:
                if attempt < retries - 1:
                    time.sleep(sleep_s * (2 ** attempt))
        out[src.name] = bars
        if sleep_s:
            time.sleep(sleep_s)
    return out


def scan_symbols(symbols, sources, target_date, fail_ratio=0.05):
    results = []
    for sym in symbols:
        series = fetch_all_sources(sym, sources)
        results.append(evaluate_symbol(sym, series, target_date))
    bad = sum(1 for r in results if r.quality in ("data_unavailable", "data_conflict"))
    summary = {
        "total": len(results),
        "hits": sum(1 for r in results if r.hit),
        "bad": bad,
        "bad_ratio": (bad / len(results)) if results else 0.0,
    }
    if results and summary["bad_ratio"] > fail_ratio:
        raise RuntimeError(f"数据异常占比 {summary['bad_ratio']:.1%} 超阈值 {fail_ratio:.0%}: {summary}")
    return results, summary
