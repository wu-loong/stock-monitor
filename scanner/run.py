"""每日扫描入口:判交易日/收盘 → 推进游标状态机。runner 与本地通用。

环境变量:
  TRADE_DATE     指定交易日 YYYY-MM-DD(留空=今天);用于回填。
  BACKFILL_LOOP  =1 时单次进程循环跑完该日所有剩余批次(回填/一次性跑完);默认只推进一批(cron)。
  BATCH_SIZE     每批只数,默认 300。
"""
import os
from datetime import datetime, date
from zoneinfo import ZoneInfo

from scanner.universe import load_universe
from scanner.sources.tencent import TencentSource
from scanner.sources.sina import SinaSource
from scanner.d1client import WranglerD1Client
from scanner.orchestrate import is_trading_closed, run_once

TZ = ZoneInfo("Asia/Shanghai")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "300"))
BENCHMARKS = ["600519", "000001", "300750", "688981"]


def main():
    now = datetime.now(TZ)
    td_env = os.environ.get("TRADE_DATE", "").strip()
    trade_date = date.fromisoformat(td_env) if td_env else now.date()
    loop = os.environ.get("BACKFILL_LOOP", "").strip() == "1"

    sources = [TencentSource(), SinaSource()]     # 东财境外 runner 不可达,生产不用
    if not is_trading_closed(sources, BENCHMARKS, trade_date):
        print(f"[{now.isoformat()}] {trade_date} 非交易日或未收盘,退出。", flush=True)
        return

    universe = load_universe("universe.json")
    meta = {r["symbol"]: {"name": r["symbol"], "pool": ",".join(r["pools"])} for r in universe}
    client = WranglerD1Client(db="stock-monitor", remote=True)
    tstr = trade_date.isoformat()

    while True:
        res = run_once(client, sources, universe, meta, tstr, now.isoformat(), BATCH_SIZE)
        print(f"[{datetime.now(TZ).isoformat()}] {tstr} -> {res}", flush=True)
        if not loop or res.get("status") == "done":
            break


if __name__ == "__main__":
    main()
