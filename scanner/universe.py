import json
import akshare as ak

# (指数代码, pool 标签)
CSI_INDICES = [("000300", "hs300"), ("000905", "zz500"), ("000852", "zz1000"), ("000688", "kc50")]
CHINEXT_POOL = "cyb"


def _csi_codes(sym):
    df = ak.index_stock_cons_csindex(symbol=sym)
    col = "成分券代码" if "成分券代码" in df.columns else [c for c in df.columns if "代码" in c and "指数" not in c][0]
    return [str(c).zfill(6) for c in df[col].tolist()]


def _chinext_codes():
    df = ak.stock_info_a_code_name()
    col = "code" if "code" in df.columns else [c for c in df.columns if "code" in c.lower() or "代码" in c][0]
    codes = [str(c).zfill(6) for c in df[col].tolist()]
    return [c for c in codes if c.startswith(("300", "301"))]


def resolve_universe():
    pools = {}  # symbol -> set(pool)
    for sym, tag in CSI_INDICES:
        for code in _csi_codes(sym):
            pools.setdefault(code, set()).add(tag)
    for code in _chinext_codes():
        pools.setdefault(code, set()).add(CHINEXT_POOL)
    return [{"symbol": s, "pools": sorted(pools[s])} for s in sorted(pools)]


def save_universe(rows, path="universe.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2, sort_keys=True)


def load_universe(path="universe.json"):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
