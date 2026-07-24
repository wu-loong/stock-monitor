"""US-runner reachability probe for the 3 A-share data sources.

Runs on GitHub Actions to answer the Plan-② head-risk deferred by the local
data-source spike: can GitHub's (US/Azure) hosted runners actually reach
East/Tencent/Sina 15-min endpoints, or are they throttled/blocked from
overseas IPs? Prints a per-source reachability report; always exits 0 so the
full log is visible (the SUMMARY line carries the verdict).
"""
import time

from scanner.sources.eastmoney import EastmoneySource
from scanner.sources.tencent import TencentSource
from scanner.sources.sina import SinaSource

SYMBOLS = ["600000", "000001", "300750", "688981"]  # sh主板/深主板/创业板/科创板
SOURCES = [EastmoneySource(), TencentSource(), SinaSource()]


def probe(src, symbol, retries=3):
    last = None
    for i in range(retries):
        try:
            bars = src.fetch_15min(symbol, days=5)
            if bars:
                return True, f"{len(bars)} bars, last={bars[-1].dt.isoformat()} close={bars[-1].close}"
            return False, "0 bars returned"
        except Exception as e:  # noqa: BLE001 - probe reports every failure kind
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (i + 1))
    return False, last


def main():
    results = {}
    for src in SOURCES:
        ok_count = 0
        print(f"\n=== {src.name} ===", flush=True)
        for sym in SYMBOLS:
            ok, info = probe(src, sym)
            print(f"  {sym}: {'OK  ' if ok else 'FAIL'} {info}", flush=True)
            ok_count += int(ok)
        results[src.name] = ok_count
        print(f"  -> {src.name}: {ok_count}/{len(SYMBOLS)} reachable", flush=True)

    print("\n=== SUMMARY (US runner reachability) ===", flush=True)
    for name, c in results.items():
        print(f"  {name}: {c}/{len(SYMBOLS)}")
    reachable_sources = sum(1 for c in results.values() if c > 0)
    print(f"  sources with >=1 symbol reachable: {reachable_sources}/3")
    if reachable_sources >= 2:
        print("  VERDICT: GO — >=2 sources reachable, cross-validation viable on US runner.")
    elif reachable_sources == 1:
        print("  VERDICT: DEGRADED — only 1 source; cross-validation impossible (all 'unverified').")
    else:
        print("  VERDICT: BLOCKED — no source reachable; GitHub-US-runner approach not viable as-is.")


if __name__ == "__main__":
    main()
