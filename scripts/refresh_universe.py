"""本地运行:解析成分池并集去重,写 universe.json 快照。成分变动(季度调仓)后重跑。"""
from scanner.universe import resolve_universe, save_universe

rows = resolve_universe()
save_universe(rows, "universe.json")
print(f"universe.json written: {len(rows)} symbols")
pools = {}
for r in rows:
    for p in r["pools"]:
        pools[p] = pools.get(p, 0) + 1
print("by pool:", pools)
