# 编排 + D1 (Plan ②) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把 Plan ① 的计算核心接上真实数据流与存储:本地解析成分池快照 → 每交易日收盘后 GitHub Actions(hourly cron + D1 游标)分批用腾讯+新浪抓 15minK、evaluate、幂等写入 Cloudflare D1。产出:一个能自动跑、把命中与采样明细落库的日频管线。

**Architecture:** 纯 Python 编排层复用 Plan ① 的 `scanner`;D1 访问抽象为 `D1Client`(真实实现 shell 到 `wrangler d1 execute`,测试实现用 stdlib `sqlite3`,D1 本就是 SQLite),使编排逻辑可全本地单测。成分池离线解析成 `universe.json` 快照提交,runner 只读快照。GitHub Actions 每整点(收盘后窗口)触发,读 D1 游标跑下一批,游标自愈。

**Tech Stack:** Python 3.11 + `scanner`(Plan ①);Cloudflare D1 via `wrangler`(需 Node ≥22);stdlib `sqlite3`(测试替身);GitHub Actions;`gh`/`wrangler` CLI。

## Global Constraints

- **Node 版本**:wrangler 需 Node ≥22。本地用 `/Users/edy/.nvm/versions/node/v22.23.1/bin`(PATH 前置);CI 用 `actions/setup-node@v4` node 22。
- **Cloudflare Account ID**:`3b629bc8851543c10495cd19fc52ea32`。
- **生产数据源 = 腾讯 + 新浪两源**(东财境外 runner 0/4 不可达,移出 runner 列表;`EastmoneySource` 代码保留供本地/可选用)。见 `docs/superpowers/spikes/2026-07-24-us-runner-reachability.md`。
- **成分池 = 提交的 `universe.json` 快照**(本地 akshare 解析;runner 不依赖成分接口境外可达性)。默认成分:沪深300(000300)+中证500(000905)+中证1000(000852)+全创业板(深市 300/301 开头)+科创50(000688),并集去重排序,实测 ~2867 只。
- **D1 数据库名**:`stock-monitor`(binding `DB`)。表:`run_state` / `sample_daily` / `signals`(schema 见 spec §6 与 Task 1)。
- **批大小** `BATCH_SIZE=300`(~10 批);**cron** UTC `5 7-19 * * 1-5`(北京 15:05–次日 03:05,~13 时槽 > 批数);workflow 设 `concurrency` 防并发争抢游标。
- **时区**:市场逻辑 `Asia/Shanghai`;cron UTC。
- **交易日/收盘判定**:不依赖交易日历接口——探针取一个基准股(如 000001)当日 15minK,若无当日 `15:00` bar → 非交易日或未收盘 → 干净退出。
- **幂等**:所有写入 `INSERT ... ON CONFLICT(...) DO UPDATE`。
- **fail-fast**:复用 `scan_symbols` 的 `bad_ratio>5%` 抛错;编排层未捕获异常即让 CI run 失败(红)。
- **单元测试不得联网、不得依赖真实 D1**:数据源用 fake、D1 用 `sqlite3` 内存库。真实网络/真实 D1 验证走标记的 smoke/手动步骤。

---

### Task 1: D1 数据库 + schema 迁移 + wrangler.toml

**Files:**
- Create: `wrangler.toml`
- Create: `migrations/0001_init.sql`
- (external) 创建远程 D1 数据库 `stock-monitor`

**Interfaces:**
- Produces: 远程 D1 数据库(binding `DB`)含 `run_state`/`sample_daily`/`signals` 三表;`wrangler.toml` 供后续 `wrangler d1 execute` 引用。

> 本任务是基础设施 + SQL,不是 TDD。所有 `wrangler` 命令用 Node 22:`export PATH="/Users/edy/.nvm/versions/node/v22.23.1/bin:$PATH"` 后 `npx wrangler ...`。

- [ ] **Step 1: 创建远程 D1 数据库**

```bash
export PATH="/Users/edy/.nvm/versions/node/v22.23.1/bin:$PATH"
cd /Users/edy/Documents/stock-monitor
npx wrangler d1 create stock-monitor
```
Expected: 输出新建库的 `database_id`(形如 `xxxxxxxx-xxxx-...`)。**记下该 id 写入 wrangler.toml。** 若已存在,`npx wrangler d1 list` 取其 id。

- [ ] **Step 2: 写 wrangler.toml**

`wrangler.toml`(把 `<DATABASE_ID>` 替换为 Step 1 的真实 id):
```toml
name = "stock-monitor"
account_id = "3b629bc8851543c10495cd19fc52ea32"
compatibility_date = "2026-07-01"

[[d1_databases]]
binding = "DB"
database_name = "stock-monitor"
database_id = "<DATABASE_ID>"
migrations_dir = "migrations"
```

- [ ] **Step 3: 写迁移 SQL**

`migrations/0001_init.sql`:
```sql
CREATE TABLE IF NOT EXISTS run_state (
  trade_date    TEXT PRIMARY KEY,
  universe_json TEXT NOT NULL,
  total_batches INTEGER NOT NULL,
  next_batch    INTEGER NOT NULL,
  status        TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sample_daily (
  trade_date   TEXT NOT NULL,
  symbol       TEXT NOT NULL,
  name         TEXT,
  pool         TEXT,
  a_1030 REAL, b_1030 REAL,
  a_1130 REAL, b_1130 REAL,
  a_1400 REAL, b_1400 REAL,
  a_1500 REAL, b_1500 REAL,
  state_t      TEXT,
  state_prev   TEXT,
  data_quality TEXT,
  PRIMARY KEY (trade_date, symbol)
);

CREATE TABLE IF NOT EXISTS signals (
  trade_date   TEXT NOT NULL,
  symbol       TEXT NOT NULL,
  name         TEXT,
  pool         TEXT,
  close        REAL,
  data_quality TEXT,
  created_at   TEXT NOT NULL,
  PRIMARY KEY (trade_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(trade_date);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
```

- [ ] **Step 4: 应用迁移(本地 + 远程)并验证**

```bash
export PATH="/Users/edy/.nvm/versions/node/v22.23.1/bin:$PATH"
npx wrangler d1 migrations apply stock-monitor --local
npx wrangler d1 migrations apply stock-monitor --remote
npx wrangler d1 execute stock-monitor --remote --command "SELECT name FROM sqlite_master WHERE type='table';"
```
Expected: 远程查询列出 `run_state`、`sample_daily`、`signals`。

- [ ] **Step 5: Commit**

```bash
git add wrangler.toml migrations/0001_init.sql
git commit -m "feat(orchestration): create D1 database + schema migration"
```

---

### Task 2: 成分池解析与加载 `scanner/universe.py`

**Files:**
- Create: `scanner/universe.py`
- Test: `tests/test_universe.py`

**Interfaces:**
- Consumes: `akshare`(仅 `resolve_universe` 用,单测 mock 掉)
- Produces:
  - `resolve_universe() -> list[dict]`:返回 `[{"symbol": "600000", "pools": ["hs300"]}, ...]`,按 symbol 升序、去重(合并 pools)。
  - `load_universe(path="universe.json") -> list[dict]`:读快照 JSON。
  - `save_universe(rows, path)`:写快照 JSON(排序、稳定)。

- [ ] **Step 1: 写失败测试(mock akshare)**

`tests/test_universe.py`:
```python
import json
from unittest.mock import patch
import pandas as pd
from scanner.universe import resolve_universe, load_universe, save_universe


def _csi_df(codes):
    return pd.DataFrame({"成分券代码": codes})


def test_resolve_dedupes_and_sorts_and_merges_pools():
    def fake_csi(symbol):
        return {"000300": _csi_df(["600000", "300750"]),
                "000905": _csi_df(["000001"]),
                "000852": _csi_df([]),
                "000688": _csi_df(["688981"])}[symbol]
    fake_codes = pd.DataFrame({"code": ["600000", "300750", "301001", "000001", "688981"]})
    with patch("scanner.universe.ak.index_stock_cons_csindex", side_effect=fake_csi), \
         patch("scanner.universe.ak.stock_info_a_code_name", return_value=fake_codes):
        rows = resolve_universe()
    syms = [r["symbol"] for r in rows]
    assert syms == sorted(syms)                       # 升序
    assert len(syms) == len(set(syms))                # 去重
    assert "301001" in syms                            # 全创业板(301)纳入
    hs = next(r for r in rows if r["symbol"] == "600000")
    assert "hs300" in hs["pools"]                      # pool 标注


def test_save_and_load_roundtrip(tmp_path):
    rows = [{"symbol": "000001", "pools": ["zz500"]}, {"symbol": "600000", "pools": ["hs300"]}]
    p = tmp_path / "u.json"
    save_universe(rows, str(p))
    assert load_universe(str(p)) == rows
```

- [ ] **Step 2: 运行,确认失败**

Run: `.venv/bin/python -m pytest tests/test_universe.py -v`
Expected: FAIL,`No module named 'scanner.universe'`。

- [ ] **Step 3: 写 universe.py**

`scanner/universe.py`:
```python
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
```

- [ ] **Step 4: 运行,确认通过**

Run: `.venv/bin/python -m pytest tests/test_universe.py -v`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
git add scanner/universe.py tests/test_universe.py
git commit -m "feat(orchestration): universe resolve/load/save"
```

---

### Task 3: 生成并提交 `universe.json` 快照

**Files:**
- Create: `scripts/refresh_universe.py`
- Create (generated): `universe.json`

**Interfaces:**
- Consumes: `scanner.universe.resolve_universe/save_universe`
- Produces: 提交的 `universe.json`(~2867 行 symbol),runner 只读它。

> 本任务是真实本地运行(联网 akshare),非 TDD。

- [ ] **Step 1: 写刷新脚本**

`scripts/refresh_universe.py`:
```python
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
```

- [ ] **Step 2: 运行生成快照**

Run: `.venv/bin/python -m scripts.refresh_universe`
Expected: 打印 `universe.json written: ~2867 symbols` 及各 pool 计数(hs300≈300, zz500≈500, zz1000≈1000, cyb≈1398, kc50≈50)。若数字明显偏离,排查成分接口。

- [ ] **Step 3: Commit**

```bash
git add scripts/refresh_universe.py universe.json
git commit -m "feat(orchestration): committed universe.json snapshot (~2867 symbols)"
```

---

### Task 4: 结果 → 幂等 upsert SQL `scanner/persist.py`

**Files:**
- Create: `scanner/persist.py`
- Test: `tests/test_persist.py`

**Interfaces:**
- Consumes: `scanner.model.ScanResult`
- Produces:
  - `sql_escape(v) -> str`:SQL 字面量(None→NULL,字符串转义单引号,数字原样)。
  - `results_to_sql(results: list[ScanResult], trade_date: str, names: dict, created_at: str) -> str`:生成 `sample_daily`(全部)+ `signals`(仅命中)的幂等 upsert 语句串(以 `;` 分隔)。

- [ ] **Step 1: 写失败测试**

`tests/test_persist.py`:
```python
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
```

- [ ] **Step 2: 运行,确认失败**

Run: `.venv/bin/python -m pytest tests/test_persist.py -v`
Expected: FAIL,`No module named 'scanner.persist'`。

- [ ] **Step 3: 写 persist.py**

`scanner/persist.py`:
```python
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
```

- [ ] **Step 4: 运行,确认通过**

Run: `.venv/bin/python -m pytest tests/test_persist.py -v`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
git add scanner/persist.py tests/test_persist.py
git commit -m "feat(orchestration): ScanResult -> idempotent D1 upsert SQL"
```

---

### Task 5: D1 访问抽象 `scanner/d1client.py`

**Files:**
- Create: `scanner/d1client.py`
- Test: `tests/test_d1client.py`

**Interfaces:**
- Produces:
  - `class D1Client(Protocol)`:`query(sql) -> list[dict]`;`execute(sql) -> None`。
  - `class SqliteD1Client`:构造 `SqliteD1Client(path=":memory:")`,用 stdlib `sqlite3`;`query` 返回 `list[dict]`,`execute` 执行(支持多语句 `executescript`)。测试与本地用。
  - `class WranglerD1Client`:构造 `WranglerD1Client(db="stock-monitor", remote=True, node_bin=...)`;`query`/`execute` shell 到 `npx wrangler d1 execute ... --json`(query 解析 JSON 的 `[0].results`)。真实用,不在单测覆盖(标 smoke/手动)。

- [ ] **Step 1: 写失败测试(sqlite 实现)**

`tests/test_d1client.py`:
```python
from scanner.d1client import SqliteD1Client


def test_sqlite_execute_and_query():
    c = SqliteD1Client(":memory:")
    c.execute("CREATE TABLE t (a TEXT PRIMARY KEY, b INTEGER);")
    c.execute("INSERT INTO t (a,b) VALUES ('x',1); INSERT INTO t (a,b) VALUES ('y',2);")
    rows = c.query("SELECT a,b FROM t ORDER BY a;")
    assert rows == [{"a": "x", "b": 1}, {"a": "y", "b": 2}]


def test_sqlite_upsert_idempotent():
    c = SqliteD1Client(":memory:")
    c.execute("CREATE TABLE t (a TEXT PRIMARY KEY, b INTEGER);")
    stmt = "INSERT INTO t (a,b) VALUES ('x',1) ON CONFLICT(a) DO UPDATE SET b=excluded.b;"
    c.execute(stmt)
    c.execute(stmt.replace(",1)", ",9)"))
    assert c.query("SELECT b FROM t WHERE a='x';") == [{"b": 9}]
```

- [ ] **Step 2: 运行,确认失败**

Run: `.venv/bin/python -m pytest tests/test_d1client.py -v`
Expected: FAIL,`No module named 'scanner.d1client'`。

- [ ] **Step 3: 写 d1client.py**

`scanner/d1client.py`:
```python
import json
import sqlite3
import subprocess
from typing import Protocol


class D1Client(Protocol):
    def query(self, sql: str) -> list: ...
    def execute(self, sql: str) -> None: ...


class SqliteD1Client:
    def __init__(self, path=":memory:"):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def query(self, sql: str) -> list:
        cur = self._conn.execute(sql)
        return [dict(r) for r in cur.fetchall()]

    def execute(self, sql: str) -> None:
        self._conn.executescript(sql)
        self._conn.commit()


class WranglerD1Client:
    def __init__(self, db="stock-monitor", remote=True, wrangler=("npx", "wrangler")):
        self._db = db
        self._flag = "--remote" if remote else "--local"
        self._wrangler = list(wrangler)

    def _run(self, sql, json_out):
        cmd = self._wrangler + ["d1", "execute", self._db, self._flag, "--command", sql]
        if json_out:
            cmd.append("--json")
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        return out

    def query(self, sql: str) -> list:
        out = self._run(sql, json_out=True)
        data = json.loads(out)
        return data[0]["results"] if data else []

    def execute(self, sql: str) -> None:
        self._run(sql, json_out=False)
```

> 说明:`WranglerD1Client.execute` 对多语句串,`wrangler d1 execute --command` 支持分号分隔多条;大批量写用 `--file`(见 Task 6 用 `execute_file`,可后续加)。本任务只需 `--command` 路径 + sqlite 单测。

- [ ] **Step 4: 运行,确认通过**

Run: `.venv/bin/python -m pytest tests/test_d1client.py -v`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
git add scanner/d1client.py tests/test_d1client.py
git commit -m "feat(orchestration): D1Client (sqlite test double + wrangler impl)"
```

---

### Task 6: 编排 + 游标状态机 `scanner/orchestrate.py`

**Files:**
- Create: `scanner/orchestrate.py`
- Test: `tests/test_orchestrate.py`

**Interfaces:**
- Consumes: `D1Client`、`scan_symbols`、`results_to_sql`、`load_universe`、`Bar`
- Produces:
  - `is_trading_closed(sources, benchmark, target_date) -> bool`:探针基准股当日是否有 `15:00` bar。
  - `ensure_run_state(client, trade_date, universe, batch_size) -> dict`:无则初始化 `run_state` 行(total_batches/next_batch=0/status='running'),返回当前状态。
  - `run_batch(client, sources, universe, meta, trade_date, created_at, batch_size) -> dict`:跑 `next_batch` 这一批 → 写 sample/signals → 游标 +1 →(到末批)status='done';返回 summary。
  - `run_once(client, sources, universe, meta, trade_date, created_at, batch_size)`:组合上面,状态机单次推进。

- [ ] **Step 1: 写失败测试(fake 源 + sqlite)**

`tests/test_orchestrate.py`:
```python
from datetime import date
from scanner.d1client import SqliteD1Client
from scanner.orchestrate import ensure_run_state, run_once
from tests.conftest import make_series


class FakeSource:
    def __init__(self, name, days_map):
        self.name = name
        self._bars = make_series(days_map)
    def fetch_15min(self, symbol, days=5):
        return self._bars


def _fresh_client():
    c = SqliteD1Client(":memory:")
    c.execute(open("migrations/0001_init.sql").read())
    return c


def test_ensure_run_state_initializes_once():
    c = _fresh_client()
    uni = [{"symbol": f"{i:06d}", "pools": ["hs300"]} for i in range(1, 8)]
    st = ensure_run_state(c, "2026-07-24", uni, batch_size=3)
    assert st["total_batches"] == 3 and st["next_batch"] == 0 and st["status"] == "running"
    st2 = ensure_run_state(c, "2026-07-24", uni, batch_size=3)   # 幂等
    assert st2["next_batch"] == 0


def test_run_once_advances_cursor_and_writes(monkeypatch):
    c = _fresh_client()
    uni = [{"symbol": f"{i:06d}", "pools": ["hs300"]} for i in range(1, 8)]
    meta = {r["symbol"]: {"name": r["symbol"], "pool": "hs300"} for r in uni}
    # 让每只都命中:monkeypatch evaluate_symbol 返回 hit
    import scanner.orchestrate as orch
    from scanner.model import ScanResult
    def fake_scan(symbols, sources, target_date, fail_ratio=0.05):
        res = [ScanResult(s, True, "all_above", "all_below", "confirmed", 1.0,
                          {f"{k}_{t}":1.0 for k in ("a","b") for t in ("1030","1130","1400","1500")})
               for s in symbols]
        return res, {"total": len(res), "hits": len(res), "bad": 0, "bad_ratio": 0.0}
    monkeypatch.setattr(orch, "scan_symbols", fake_scan)
    for _ in range(3):
        run_once(c, sources=[], universe=uni, meta=meta,
                 trade_date="2026-07-24", created_at="t", batch_size=3)
    assert c.query("SELECT status FROM run_state;")[0]["status"] == "done"
    assert c.query("SELECT COUNT(*) n FROM signals;")[0]["n"] == 7
    assert c.query("SELECT COUNT(*) n FROM sample_daily;")[0]["n"] == 7
```

- [ ] **Step 2: 运行,确认失败**

Run: `.venv/bin/python -m pytest tests/test_orchestrate.py -v`
Expected: FAIL,`No module named 'scanner.orchestrate'`。

- [ ] **Step 3: 写 orchestrate.py**

`scanner/orchestrate.py`:
```python
import json
from scanner.scan import scan_symbols
from scanner.persist import results_to_sql
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
    rows = client.query(f"SELECT * FROM run_state WHERE trade_date='{trade_date}';")
    if rows:
        return rows[0]
    syms = [r["symbol"] for r in universe]
    total = (len(syms) + batch_size - 1) // batch_size
    uni_json = json.dumps(syms).replace("'", "''")
    client.execute(
        f"INSERT INTO run_state (trade_date, universe_json, total_batches, next_batch, status, updated_at) "
        f"VALUES ('{trade_date}', '{uni_json}', {total}, 0, 'running', '{trade_date}');")
    return client.query(f"SELECT * FROM run_state WHERE trade_date='{trade_date}';")[0]


def run_batch(client, sources, universe, meta, trade_date, created_at, batch_size):
    st = client.query(f"SELECT * FROM run_state WHERE trade_date='{trade_date}';")[0]
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
        f"UPDATE run_state SET next_batch={nb}, status='{status}', updated_at='{created_at}' "
        f"WHERE trade_date='{trade_date}';")
    return {"status": status, "batch": nb - 1, "summary": summary}


def run_once(client, sources, universe, meta, trade_date, created_at, batch_size):
    ensure_run_state(client, trade_date, universe, batch_size)
    return run_batch(client, sources, universe, meta, trade_date, created_at, batch_size)


def _to_date(s):
    from datetime import date
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)
```

- [ ] **Step 4: 运行,确认通过**

Run: `.venv/bin/python -m pytest tests/test_orchestrate.py -v`
Expected: 2 passed。

- [ ] **Step 5: 全量单测回归**

Run: `.venv/bin/python -m pytest -q`
Expected: 全绿(smoke 默认跳过)。

- [ ] **Step 6: Commit**

```bash
git add scanner/orchestrate.py tests/test_orchestrate.py
git commit -m "feat(orchestration): cursor state machine + batch runner"
```

---

### Task 7: 入口脚本 + GitHub Actions 每日工作流 + 部署

**Files:**
- Create: `scanner/run.py`(CLI 入口)
- Create: `.github/workflows/daily-scan.yml`
- (external) 创建 D1 作用域 API token → 设为 GH secret

**Interfaces:**
- Consumes: `orchestrate`、`WranglerD1Client`、`load_universe`、`TencentSource`、`SinaSource`
- Produces: 可在 runner 上 `python -m scanner.run` 跑一次状态机推进的入口;每整点 cron 触发的工作流。

- [ ] **Step 1: 写入口 `scanner/run.py`**

```python
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
    sources = [TencentSource(), SinaSource()]     # 东财境外不可达,生产不用
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
```

> 注:名称暂用 symbol 占位(`meta.name = symbol`);若要真实中文名,可在 refresh_universe 时一并抓 `stock_info_a_code_name` 的 name 存入 universe.json 的 `name` 字段(后续增强,非本期阻塞)。

- [ ] **Step 2: 创建 D1 作用域 API token → 设 GH secret**

**(需人工一步)** 在 Cloudflare Dashboard → My Profile → API Tokens → Create Token,权限 **Account · D1 · Edit**(Account 选 "Dashborad Controller")。复制 token 后:
```bash
gh secret set CLOUDFLARE_API_TOKEN --body "<token>"
gh secret set CLOUDFLARE_ACCOUNT_ID --body "3b629bc8851543c10495cd19fc52ea32"
```
Expected: `gh secret list` 显示两个 secret。

- [ ] **Step 3: 写工作流 `.github/workflows/daily-scan.yml`**

```yaml
name: daily-scan
on:
  schedule:
    - cron: "5 7-19 * * 1-5"      # UTC; 北京 15:05–次日 03:05
  workflow_dispatch:

concurrency:
  group: daily-scan
  cancel-in-progress: false

jobs:
  scan:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
      CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - uses: actions/setup-node@v4
        with: { node-version: "22" }
      - run: pip install -r requirements.txt
      - run: npm install -g wrangler
      - run: python -m scanner.run
```

- [ ] **Step 4: 部署验证(手动触发一次)**

```bash
export PATH="/Users/edy/.nvm/versions/node/v22.23.1/bin:$PATH"
git add scanner/run.py .github/workflows/daily-scan.yml
git commit -m "feat(orchestration): daily-scan entrypoint + workflow"
git push origin main
gh workflow run daily-scan.yml
# 跟踪
RID=$(gh run list --workflow=daily-scan.yml -L1 --json databaseId -q '.[0].databaseId')
gh run watch "$RID" --exit-status
```
Expected: 若当前是交易日收盘后 → run_once 推进一批,D1 有数据(`npx wrangler d1 execute stock-monitor --remote --command "SELECT COUNT(*) FROM sample_daily;"`);若非交易日/未收盘 → 干净退出打印提示。**首次可能因非交易时段只打印"未收盘退出",属正常**。

- [ ] **Step 5: 确认 secrets 不泄露 + 收尾**

确认工作流日志未打印 token;`git log` 无 secret。Plan ② 完成。

---

## 交付物(Plan ② 完成后)

- 远程 D1 `stock-monitor`(三表 + 索引)。
- `scanner/universe.py` + 提交的 `universe.json` 快照。
- `scanner/persist.py`(结果→幂等 SQL)、`scanner/d1client.py`(sqlite 替身 + wrangler 实现)、`scanner/orchestrate.py`(游标状态机)、`scanner/run.py`(入口)。
- `.github/workflows/daily-scan.yml`(cron + 游标 + 部署)。
- 全套新单测通过(universe/persist/d1client/orchestrate),无联网、无真实 D1 依赖。

## 后续(Plan ③ 展示页)

Workers + Static Assets 公开页:Worker Function 查 D1(`/api/signals`、`/api/symbol`、`/api/status`)+ 单页前端(当日命中 + 历史 + 数据不完整提示,深浅色自适应)。等 Plan ② 有数据入库后再做。
```
