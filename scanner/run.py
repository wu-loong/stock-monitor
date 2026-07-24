"""每日扫描入口:判交易日/收盘 → 推进游标状态机一批。runner 与本地通用。"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.universe import load_universe
from scanner.sources.tencent import TencentSource
from scanner.sources.sina import SinaSource
from scanner.d1client import WranglerD1Client
from scanner.orchestrate import is_trading_closed, run_once

TZ = ZoneInfo("Asia/Shanghai")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "300"))


def main():
    now = datetime.now(TZ)
    trade_date = now.date()
    sources = [TencentSource(), SinaSource()]     # 东财境外 runner 不可达,生产不用
    if not is_trading_closed(sources, "000001", trade_date):
        print(f"[{now.isoformat()}] 非交易日或未收盘,退出。")
        return
    universe = load_universe("universe.json")
    meta = {r["symbol"]: {"name": r["symbol"], "pool": ",".join(r["pools"])} for r in universe}
    client = WranglerD1Client(db="stock-monitor", remote=True)
    tstr = trade_date.isoformat()
    res = run_once(client, sources, universe, meta, tstr, now.isoformat(), BATCH_SIZE)
    print(f"[{now.isoformat()}] run_once -> {res}")


if __name__ == "__main__":
    main()
