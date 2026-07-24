# 计算核心 (Compute Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一个独立的 Python 包:给定 A 股代码列表与目标交易日,从东财/腾讯/新浪三源抓取 5 日 15 分钟 K 线并交叉校验,计算 60分MA5 与 15分MA20 在 10:30/11:30/14:00/15:00 四点的状态,判定是否"昨日全小于→今日全大于"命中。纯 Python、可单测,不涉及 D1/GH Actions/Workers。

**Architecture:** 分层纯函数 + 数据源适配器。`sources/*` 各自把一个源的原始响应归一化为统一的 `Bar`(收盘时刻/Asia-Shanghai/收盘价);`crossvalidate` 做逐时间戳三源共识;`indicators`+`evaluate` 做均线/状态/命中/数据质量判定。核心逻辑用合成 K 线单测,网络适配器用 mock 单测 + 标记的真实 smoke 测试。

**Tech Stack:** Python 3.11、pandas、requests、akshare(东财)、pytest、unittest.mock(stdlib)。

## Global Constraints

- Python 版本:3.11(与已装 akshare 1.18.64 的环境一致)。
- 时区:所有 K 线时间统一为 tz-aware `Asia/Shanghai`,取 **bar 收盘时刻**。
- 采样时点:`("10:30","11:30","14:00","15:00")`(A 股 4 根 60 分钟 K 收盘时刻)。
- 指标:A = 60分钟收盘价 MA5(窗口 5);B = 15分钟收盘价 MA20(窗口 20);均用**收盘价**、简单均值。
- 60 分钟 K 收盘价 = 同一时刻 15 分钟 K 收盘价(两者同一收盘瞬间),故"60分钟收盘序列" = 15分钟序列中时间 ∈ 采样时点的子集。
- 状态判定**严格不等**,浮点比较 `EPS = 1e-9`:`all_below` ⟺ 四点全 `b-a > EPS`;`all_above` ⟺ 四点全 `a-b > EPS`;否则 `mixed`;窗口不足或含缺口 → `incomplete`。
- 命中 ⟺ `state(T-1)==all_below` 且 `state(T)==all_above`(T-1 为 T 之前最近的有数据交易日)。
- 交叉校验价格容差 `PRICE_TOL = 0.01` 元;逐时间戳:≥2 源两两在容差内一致→`confirmed`;恰 1 源→`unverified`;≥2 源超容差→`conflict`;0 源→`missing`。
- 数据质量优先级(取最差):`data_unavailable`(有缺口/窗口不足)> `data_conflict` > `unverified` > `confirmed`;质量为 `data_unavailable`/`data_conflict` 时**强制 hit=False**。
- 单元测试**不得联网**;真实网络测试用 `@pytest.mark.smoke` 标记,默认不跑。
- 频繁提交:每个 Task 完成即 commit。

---

### Task 1: 工程脚手架 + 数据源 Spike(先证伪)

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `scanner/__init__.py`(空)
- Create: `tests/__init__.py`(空)
- Create: `.gitignore`
- Create(throwaway): `spike_sources.py`
- Create(deliverable): `docs/superpowers/spikes/2026-07-24-data-sources.md`

**Interfaces:**
- Produces: 确认三源可达性、真实响应结构、**时间戳约定(开盘时刻 vs 收盘时刻、时区)**、每日 bar 数、历史深度;确认 `Bar.dt` 归一化到收盘时刻所需的偏移。这些结论写入 spike 文档,供 Task 7–9 的适配器解析参数使用。

- [ ] **Step 1: 建虚拟环境并装依赖**

`requirements.txt`:
```
akshare==1.18.64
pandas>=2.0
requests>=2.31
pytest>=8.0
```

Run:
```bash
cd /Users/edy/Documents/stock-monitor
git init 2>/dev/null || true         # 尚非 git 仓库时初始化(公开 GH 远端在计划②创建)
python3.11 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
```
Expected: 安装成功,`.venv/bin/python -c "import akshare, pandas, requests"` 无报错。

- [ ] **Step 2: 建 pytest 配置与包骨架**

`pytest.ini`:
```ini
[pytest]
testpaths = tests
markers =
    smoke: 真实联网冒烟测试(默认不跑,用 -m smoke 显式运行)
addopts = -m "not smoke"
```

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.pytest_cache/
spike_sources.py
out.sql
```

创建空文件 `scanner/__init__.py`、`tests/__init__.py`。

- [ ] **Step 3: 写 spike 脚本,实测三源**

`spike_sources.py`(一次性,验证后不入库):
```python
"""一次性 spike:实测东财/腾讯/新浪 15分钟K,记录结构与时间戳约定。"""
import akshare as ak
import requests, json

# 覆盖 沪深主板/中小/创业板/科创板 各一只
SYMBOLS = ["600000", "000001", "002415", "300750", "688981"]

def probe_eastmoney(code):
    df = ak.stock_zh_a_hist_min_em(symbol=code, period="15", adjust="")
    print("  [东财] rows=", len(df), "cols=", list(df.columns))
    print("  tail:\n", df.tail(3).to_string())

def to_secid(code):
    return ("sh" if code[0] in "6" or code[:3] in ("688","900") else "sz") + code

def probe_tencent(code):
    sec = to_secid(code)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/kline/mkline?param={sec},m15,,320"
    r = requests.get(url, timeout=10)
    data = r.json()["data"][sec]
    m15 = data.get("m15") or data.get("qfqm15")
    print("  [腾讯] n=", len(m15), "sample last:", m15[-2:])

def probe_sina(code):
    sec = to_secid(code)
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={sec}&scale=15&ma=no&datalen=100")
    r = requests.get(url, timeout=10)
    arr = json.loads(r.text)
    print("  [新浪] n=", len(arr), "sample last:", arr[-2:])

for c in SYMBOLS:
    print("=== ", c, " ===")
    for name, fn in (("east", probe_eastmoney), ("tx", probe_tencent), ("sina", probe_sina)):
        try:
            fn(c)
        except Exception as e:
            print(f"  {name} FAIL: {type(e).__name__}: {e}")
```

- [ ] **Step 4: 运行 spike 并记录结论**

Run:
```bash
.venv/bin/python spike_sources.py 2>&1 | tee /Users/edy/.claude/jobs/595115b3/tmp/spike_out.txt
```
Expected: 输出每源的行数/列名/末尾样本。**重点判读**:
- 每源哪些 code 可达、是否被限流;
- 时间字段是 `YYYY-MM-DD HH:MM` 形式;该时刻是 **bar 收盘还是开盘**(对比东财与腾讯/新浪同一根 bar 的时间标注:若东财标 10:30 而腾讯标 10:15,则约定不同,需在适配器里 +15min 归一);
- A 股每交易日应有 16 根 15 分钟 bar,时间落在 09:45–11:30 与 13:15–15:00;
- 历史是否≥5 个交易日。

- [ ] **Step 5: 写 spike 交付文档 + go/no-go**

创建 `docs/superpowers/spikes/2026-07-24-data-sources.md`,按此模板填入实测结论:
```markdown
# 数据源 Spike 结论 (2026-07-24)

## 可达性(本地/境内)
| 源 | 可达 | 备注 |
|---|---|---|
| 东财(akshare stock_zh_a_hist_min_em) | ? | |
| 腾讯(gtimg m15) | ? | |
| 新浪(getKLineData scale=15) | ? | |

## 响应结构与字段
- 东财:列名 = ...,收盘列 = ...,时间列 = ...
- 腾讯:m15 数组元素 = [time, open, close, high, low, volume, ...]
- 新浪:元素 = {day, open, high, low, close, volume}

## 时间戳约定(关键)
- 东财时间 = 收盘/开盘 ?
- 腾讯时间 = 收盘/开盘 ?  → 归一化偏移 = ?
- 新浪时间 = 收盘/开盘 ?  → 归一化偏移 = ?
- 统一目标:bar 收盘时刻,Asia/Shanghai。

## 每日 bar 数 / 历史深度
- ...

## go/no-go
- 每源是否纳入三源交叉校验:...
- 若某源不可用/字段异常,如何降级(仍保留≥2 源)。
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt pytest.ini .gitignore scanner/__init__.py tests/__init__.py docs/superpowers/spikes/2026-07-24-data-sources.md
git commit -m "chore: scaffold compute-core + data-source spike findings"
```

---

### Task 2: 数据模型与代码→secid 映射

**Files:**
- Create: `scanner/model.py`
- Create: `scanner/symbols.py`
- Test: `tests/test_symbols.py`

**Interfaces:**
- Produces:
  - `scanner.model.Bar(dt: datetime, close: float)`(frozen dataclass,`dt` tz-aware Asia/Shanghai 收盘时刻)
  - `scanner.model.ConsensusBar(dt: datetime, close: float | None, quality: str)`
  - `scanner.model.ScanResult`(见 Task 6)
  - 常量:`TZ`、`SAMPLE_TIMES`、`HOURLY_WINDOW=5`、`MIN15_WINDOW=20`、`PRICE_TOL=0.01`、`EPS=1e-9`
  - `scanner.symbols.to_secid(code: str) -> str`(`"600000"`→`"sh600000"`,`"300750"`→`"sz300750"`)

- [ ] **Step 1: 写 model.py**

`scanner/model.py`:
```python
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
SAMPLE_TIMES = ("10:30", "11:30", "14:00", "15:00")
HOURLY_WINDOW = 5
MIN15_WINDOW = 20
PRICE_TOL = 0.01
EPS = 1e-9


@dataclass(frozen=True)
class Bar:
    dt: datetime           # tz-aware Asia/Shanghai, bar close time
    close: float


@dataclass(frozen=True)
class ConsensusBar:
    dt: datetime
    close: float | None
    quality: str           # 'confirmed' | 'unverified' | 'conflict' | 'missing'


@dataclass(frozen=True)
class ScanResult:
    symbol: str
    hit: bool
    state_t: str
    state_prev: str
    quality: str           # 'confirmed'|'unverified'|'data_conflict'|'data_unavailable'
    close: float | None    # 目标日 15:00 收盘价
    samples: dict          # {"a_1030":.., "b_1030":.., ... , "a_1500":.., "b_1500":..}
```

- [ ] **Step 2: 写失败测试(to_secid)**

`tests/test_symbols.py`:
```python
from scanner.symbols import to_secid


def test_shanghai_main_board():
    assert to_secid("600000") == "sh600000"


def test_star_board_688():
    assert to_secid("688981") == "sh688981"


def test_shenzhen_main_and_chinext():
    assert to_secid("000001") == "sz000001"
    assert to_secid("300750") == "sz300750"
    assert to_secid("301001") == "sz301001"
```

- [ ] **Step 3: 运行,确认失败**

Run: `.venv/bin/python -m pytest tests/test_symbols.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'scanner.symbols'`。

- [ ] **Step 4: 写 symbols.py**

`scanner/symbols.py`:
```python
def to_secid(code: str) -> str:
    """6 位 A 股代码 → 带交易所前缀的 secid。
    上交所:6 开头(主板 60x)、688(科创)、900(B股);其余归深交所(000/001/002/003/300/301)。
    """
    code = str(code).zfill(6)
    if code[0] == "6" or code[:3] in ("688", "900"):
        return "sh" + code
    return "sz" + code
```

- [ ] **Step 5: 运行,确认通过**

Run: `.venv/bin/python -m pytest tests/test_symbols.py -v`
Expected: 3 passed。

- [ ] **Step 6: Commit**

```bash
git add scanner/model.py scanner/symbols.py tests/test_symbols.py
git commit -m "feat: add Bar/ConsensusBar/ScanResult model and to_secid"
```

---

### Task 3: 均线与单日状态(纯逻辑)

**Files:**
- Create: `scanner/indicators.py`
- Test: `tests/conftest.py`(合成 bar 构造器)
- Test: `tests/test_indicators.py`

**Interfaces:**
- Consumes: `scanner.model`(Bar/ConsensusBar/常量)
- Produces:
  - `scanner.indicators.sma(values: list[float], window: int) -> float | None`
  - `scanner.indicators.hhmm(dt) -> str`
  - `scanner.indicators.sample_index(bars: list, d, t: str) -> int | None`
  - `scanner.indicators.windows_for(bars: list, i: int) -> tuple[list[int], list[int]] | None`(返回 (15分窗口索引, 60分窗口索引);历史不足返回 None)
  - `scanner.indicators._ab_at(bars: list, i: int) -> tuple[float | None, float | None]`(该采样点 (60分MA5, 15分MA20);任一所需 close 为 None 或历史不足 → (None, None)。Task 6 复用)
  - `scanner.indicators.state_for_date(bars: list, d) -> str`(`'all_below'|'all_above'|'mixed'|'incomplete'`)

- [ ] **Step 1: 写合成 bar 构造器**

`tests/conftest.py`:
```python
from datetime import datetime, date, timedelta
from scanner.model import Bar, TZ

BAR_TIMES = ["09:45","10:00","10:15","10:30","10:45","11:00","11:15","11:30",
             "13:15","13:30","13:45","14:00","14:15","14:30","14:45","15:00"]


def make_day(d: date, closes: list[float]) -> list[Bar]:
    """按 16 根 15 分钟 bar 时刻,给定收盘价序列,生成一天的 Bar。"""
    assert len(closes) == 16
    out = []
    for t, c in zip(BAR_TIMES, closes):
        hh, mm = map(int, t.split(":"))
        out.append(Bar(datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ), float(c)))
    return out


def make_series(day_closes: dict) -> list[Bar]:
    """day_closes: {date: [16 closes]} → 按时间升序展平。"""
    bars = []
    for d in sorted(day_closes):
        bars.extend(make_day(d, day_closes[d]))
    return bars


def make_monotonic(dates: list, start: float = 100.0, step: float = 1.0) -> dict:
    """生成跨天严格单调的收盘序列:{date: [16 closes]}。
    step>0 → 全程递增(尾部5小时窗口上行,每个采样点 A>B → all_above);
    step<0 → 全程递减(→ all_below)。"""
    day_closes = {}
    i = 0
    for d in sorted(dates):
        day_closes[d] = [start + step * (i + k) for k in range(16)]
        i += 16
    return day_closes
```

- [ ] **Step 2: 写失败测试(sma / sample_index / state)**

`tests/test_indicators.py`:
```python
from datetime import date
from scanner.indicators import sma, sample_index, windows_for, state_for_date
from tests.conftest import make_series, make_monotonic, BAR_TIMES

DATES = [date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17)]


def test_sma_basic():
    assert sma([1, 2, 3, 4, 5], 5) == 3
    assert sma([1, 2], 5) is None


def test_sample_index_finds_1030():
    bars = make_series({date(2026, 7, 20): list(range(1, 17))})
    i = sample_index(bars, date(2026, 7, 20), "10:30")
    assert bars[i].dt.strftime("%H:%M") == "10:30"


def test_state_all_above_on_strictly_increasing():
    # 全程严格递增 → 每个采样点尾部5小时窗口上行 → 60分MA5 > 15分MA20 → all_above
    bars = make_series(make_monotonic(DATES, start=100.0, step=1.0))
    assert state_for_date(bars, DATES[-1]) == "all_above"


def test_state_all_below_on_strictly_decreasing():
    # 全程严格递减 → all_below
    bars = make_series(make_monotonic(DATES, start=300.0, step=-1.0))
    assert state_for_date(bars, DATES[-1]) == "all_below"


def test_state_incomplete_when_no_history():
    bars = make_series({date(2026, 7, 20): [10.0]*16})
    # 只有一天,15分MA20(需20根)在 10:30 只有4根 → incomplete
    assert state_for_date(bars, date(2026, 7, 20)) == "incomplete"
```

- [ ] **Step 3: 运行,确认失败**

Run: `.venv/bin/python -m pytest tests/test_indicators.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'scanner.indicators'`。

- [ ] **Step 4: 写 indicators.py**

`scanner/indicators.py`:
```python
from scanner.model import SAMPLE_TIMES, HOURLY_WINDOW, MIN15_WINDOW, EPS


def sma(values, window):
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def hhmm(dt):
    return dt.strftime("%H:%M")


def sample_index(bars, d, t):
    """bars 升序;返回日期==d 且时间==t 的下标,找不到返回 None。"""
    for i, b in enumerate(bars):
        if b.dt.date() == d and hhmm(b.dt) == t:
            return i
    return None


def windows_for(bars, i):
    """返回 (w15_idx, w60_idx):15分MA20 用的 20 个下标 + 60分MA5 用的 5 个下标。
    历史不足则返回 None。60分序列 = 时间 ∈ SAMPLE_TIMES 的 bar。"""
    if i - (MIN15_WINDOW - 1) < 0:
        return None
    w15 = list(range(i - MIN15_WINDOW + 1, i + 1))
    hourly = [j for j in range(0, i + 1) if hhmm(bars[j].dt) in SAMPLE_TIMES]
    if len(hourly) < HOURLY_WINDOW:
        return None
    w60 = hourly[-HOURLY_WINDOW:]
    return w15, w60


def _ab_at(bars, i):
    """返回该采样点 (a=60分MA5, b=15分MA20);任一所需 close 为 None → (None,None)。"""
    win = windows_for(bars, i)
    if win is None:
        return None, None
    w15, w60 = win
    v15 = [bars[j].close for j in w15]
    v60 = [bars[j].close for j in w60]
    if any(v is None for v in v15) or any(v is None for v in v60):
        return None, None
    return sma(v60, HOURLY_WINDOW), sma(v15, MIN15_WINDOW)


def state_for_date(bars, d):
    pairs = []
    for t in SAMPLE_TIMES:
        i = sample_index(bars, d, t)
        if i is None:
            return "incomplete"
        a, b = _ab_at(bars, i)
        if a is None or b is None:
            return "incomplete"
        pairs.append((a, b))
    if all(b - a > EPS for a, b in pairs):
        return "all_below"
    if all(a - b > EPS for a, b in pairs):
        return "all_above"
    return "mixed"
```

- [ ] **Step 5: 运行,确认通过**

Run: `.venv/bin/python -m pytest tests/test_indicators.py -v`
Expected: 5 passed。

- [ ] **Step 6: Commit**

```bash
git add scanner/indicators.py tests/conftest.py tests/test_indicators.py
git commit -m "feat: add MA/state indicators with synthetic-bar tests"
```

---

### Task 4: 命中判定

**Files:**
- Create: `scanner/signals.py`
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: `scanner.indicators.state_for_date`
- Produces: `scanner.signals.detect_hit(bars: list, target_date) -> tuple[bool, object]`(返回 (是否命中, prev_date 或 None))

- [ ] **Step 1: 写失败测试**

`tests/test_signals.py`:
```python
from datetime import date
from scanner.signals import detect_hit
from tests.conftest import make_series

# 构造:T-1 全部 A<B(all_below),T 全部 A>B(all_above)
# 价格形态:前段平稳使快线(15分MA20)高于慢线(60分MA5)→ all_below;
# 目标日大幅高开走高使 60分MA5 反超 → all_above。用 Task6 的集成夹具更稳,这里用直接构造的状态桩。


def test_detect_hit_true(monkeypatch):
    import scanner.signals as sig
    seq = {date(2026,7,21): "all_below", date(2026,7,22): "all_above"}
    monkeypatch.setattr(sig, "state_for_date", lambda bars, d: seq[d])
    bars = make_series({date(2026,7,21): [1.0]*16, date(2026,7,22): [1.0]*16})
    hit, prev = detect_hit(bars, date(2026,7,22))
    assert hit is True and prev == date(2026,7,21)


def test_detect_hit_false_when_prev_mixed(monkeypatch):
    import scanner.signals as sig
    seq = {date(2026,7,21): "mixed", date(2026,7,22): "all_above"}
    monkeypatch.setattr(sig, "state_for_date", lambda bars, d: seq[d])
    bars = make_series({date(2026,7,21): [1.0]*16, date(2026,7,22): [1.0]*16})
    hit, prev = detect_hit(bars, date(2026,7,22))
    assert hit is False and prev == date(2026,7,21)


def test_detect_hit_false_when_no_prev_day():
    bars = make_series({date(2026,7,22): [1.0]*16})
    hit, prev = detect_hit(bars, date(2026,7,22))
    assert hit is False and prev is None
```

- [ ] **Step 2: 运行,确认失败**

Run: `.venv/bin/python -m pytest tests/test_signals.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'scanner.signals'`。

- [ ] **Step 3: 写 signals.py**

`scanner/signals.py`:
```python
from scanner.indicators import state_for_date


def detect_hit(bars, target_date):
    """T-1 = target_date 之前最近的有 bar 的交易日。
    命中 ⟺ state(T-1)==all_below 且 state(T)==all_above。"""
    dates = sorted({b.dt.date() for b in bars})
    prev_candidates = [d for d in dates if d < target_date]
    if not prev_candidates:
        return False, None
    prev = prev_candidates[-1]
    hit = (state_for_date(bars, prev) == "all_below"
           and state_for_date(bars, target_date) == "all_above")
    return hit, prev
```

- [ ] **Step 4: 运行,确认通过**

Run: `.venv/bin/python -m pytest tests/test_signals.py -v`
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add scanner/signals.py tests/test_signals.py
git commit -m "feat: add adjacent-day flip hit detection"
```

---

### Task 5: 三源交叉校验

**Files:**
- Create: `scanner/crossvalidate.py`
- Test: `tests/test_crossvalidate.py`

**Interfaces:**
- Consumes: `scanner.model`(Bar/ConsensusBar/PRICE_TOL)
- Produces: `scanner.crossvalidate.cross_validate(series_by_source: dict[str, list[Bar]], tol: float = PRICE_TOL) -> list[ConsensusBar]`(按 dt 升序;逐时间戳共识 + 质量标注)

- [ ] **Step 1: 写失败测试(四种质量)**

`tests/test_crossvalidate.py`:
```python
from datetime import datetime
from scanner.model import Bar, TZ
from scanner.crossvalidate import cross_validate


def _b(minute, close):
    return Bar(datetime(2026, 7, 22, 10, minute, tzinfo=TZ), close)


def test_confirmed_two_sources_agree():
    out = cross_validate({"east": [_b(30, 10.00)], "tx": [_b(30, 10.005)]})
    assert len(out) == 1 and out[0].quality == "confirmed"
    assert abs(out[0].close - 10.0) < 0.01


def test_unverified_single_source():
    out = cross_validate({"east": [_b(30, 10.00)]})
    assert out[0].quality == "unverified" and out[0].close == 10.00


def test_conflict_beyond_tol():
    out = cross_validate({"east": [_b(30, 10.00)], "tx": [_b(30, 10.50)]})
    assert out[0].quality == "conflict" and out[0].close is None


def test_conflict_when_third_source_disagrees():
    out = cross_validate({"east": [_b(30, 10.00)], "tx": [_b(30, 10.00)], "sina": [_b(30, 11.00)]})
    assert out[0].quality == "conflict"


def test_sorted_and_union_of_timestamps():
    out = cross_validate({"east": [_b(45, 1.0), _b(30, 1.0)], "tx": [_b(30, 1.0)]})
    assert [b.dt.strftime("%H:%M") for b in out] == ["10:30", "10:45"]
```

- [ ] **Step 2: 运行,确认失败**

Run: `.venv/bin/python -m pytest tests/test_crossvalidate.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'scanner.crossvalidate'`。

- [ ] **Step 3: 写 crossvalidate.py**

`scanner/crossvalidate.py`:
```python
from scanner.model import ConsensusBar, PRICE_TOL


def cross_validate(series_by_source, tol=PRICE_TOL):
    maps = {name: {b.dt: b.close for b in bars} for name, bars in series_by_source.items()}
    all_dts = sorted({dt for m in maps.values() for dt in m})
    out = []
    for dt in all_dts:
        vals = [round(maps[n][dt], 2) for n in maps if dt in maps[n]]
        if not vals:
            out.append(ConsensusBar(dt, None, "missing"))
        elif len(vals) == 1:
            out.append(ConsensusBar(dt, vals[0], "unverified"))
        elif max(vals) - min(vals) <= tol + 1e-9:
            out.append(ConsensusBar(dt, sum(vals) / len(vals), "confirmed"))
        else:
            out.append(ConsensusBar(dt, None, "conflict"))
    return out
```

- [ ] **Step 4: 运行,确认通过**

Run: `.venv/bin/python -m pytest tests/test_crossvalidate.py -v`
Expected: 5 passed。

- [ ] **Step 5: Commit**

```bash
git add scanner/crossvalidate.py tests/test_crossvalidate.py
git commit -m "feat: add per-timestamp 3-source cross-validation"
```

---

### Task 6: 单股评估(整合:校验→状态→命中→质量)

**Files:**
- Create: `scanner/evaluate.py`
- Test: `tests/test_evaluate.py`

**Interfaces:**
- Consumes: `cross_validate`、`state_for_date`、`sample_index`、`windows_for`、`_ab_at`、`detect_hit`、`model.ScanResult`
- Produces: `scanner.evaluate.evaluate_symbol(symbol: str, series_by_source: dict[str, list[Bar]], target_date) -> ScanResult`

**质量规则(基于 T 与 T-1 两天四点所依赖的 bar):** 收集这两天 8 个采样点各自 15分/60分窗口涉及的所有 ConsensusBar 下标(needed set)。若任一采样点 bar 缺失或窗口不足 → `data_unavailable`;否则按 needed set 里最差质量:含 `missing`→`data_unavailable`,含 `conflict`→`data_conflict`,含 `unverified`→`unverified`,否则 `confirmed`。质量为 `data_unavailable`/`data_conflict` 时强制 `hit=False`。

- [ ] **Step 1: 写失败测试(命中 + 质量降级)**

`tests/test_evaluate.py`:
```python
from datetime import date, datetime
import scanner.indicators as ind
import scanner.signals as sig
from scanner.model import Bar, TZ
from scanner.evaluate import evaluate_symbol
from tests.conftest import make_day, make_series


def _b(d, hh, mm, c):
    return Bar(datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ), c)


def test_conflict_bar_forces_unavailable_or_conflict():
    # 目标日某采样点两源冲突 → 质量非 confirmed,hit=False
    d0, d1, d2, d3, dT = (date(2026,7,15), date(2026,7,16), date(2026,7,17),
                          date(2026,7,18), date(2026,7,21))
    days = {d: [10.0]*16 for d in (d0,d1,d2,d3,dT)}
    east = make_series(days)
    tx = make_series(days)
    # 篡改 tx 在 dT 10:30 的价,制造冲突
    tx = [Bar(b.dt, (b.close+5.0 if (b.dt.date()==dT and b.dt.strftime('%H:%M')=='10:30') else b.close))
          for b in tx]
    r = evaluate_symbol("000001", {"east": east, "tx": tx}, dT)
    assert r.quality in ("data_conflict", "data_unavailable")
    assert r.hit is False


def test_missing_history_unavailable():
    dT = date(2026,7,21)
    east = make_series({dT: [10.0]*16})   # 只有目标日一天,窗口不足
    r = evaluate_symbol("000001", {"east": east}, dT)
    assert r.quality == "data_unavailable"
    assert r.hit is False


def test_hit_wiring_with_forced_states(monkeypatch):
    # 真实"前日全小于→今日全大于"信号极严格、难用平滑价格构造(见设计:60分MA5 尾部5小时
    # 窗口跨日)。state 的数学正确性已在 test_indicators 用严格单调序列验证;此处只验证
    # evaluate 把 state/命中/质量正确接线:monkeypatch 强制两天状态,数据充足使 computable=True。
    d_prev, dT = date(2026, 7, 20), date(2026, 7, 21)
    dates = [date(2026,7,13), date(2026,7,14), date(2026,7,15), date(2026,7,16), d_prev, dT]
    east = make_series({d: [10.0]*16 for d in dates})   # 6 天 → 窗口填满 → computable
    forced = {d_prev: "all_below", dT: "all_above"}
    # evaluate 内部 `from scanner.indicators import state_for_date`(调用时取值)→ patch ind;
    # detect_hit 在 signals 模块加载时已绑定该名 → 同时 patch sig。
    monkeypatch.setattr(ind, "state_for_date", lambda bars, d: forced.get(d, "mixed"))
    monkeypatch.setattr(sig, "state_for_date", lambda bars, d: forced.get(d, "mixed"))
    r = evaluate_symbol("000001", {"east": east}, dT)
    assert r.state_prev == "all_below"
    assert r.state_t == "all_above"
    assert r.hit is True
    assert r.quality == "unverified"   # 单源 → unverified,但仍算命中
```

- [ ] **Step 2: 运行,确认失败**

Run: `.venv/bin/python -m pytest tests/test_evaluate.py -v`
Expected: FAIL,`No module named 'scanner.evaluate'`。

- [ ] **Step 3: 写 evaluate.py**

`scanner/evaluate.py`:
```python
from scanner.model import ScanResult, SAMPLE_TIMES
from scanner.crossvalidate import cross_validate
from scanner.indicators import sample_index, windows_for, _ab_at
from scanner.signals import detect_hit


_Q_RANK = {"confirmed": 0, "unverified": 1, "conflict": 2, "missing": 3}


def evaluate_symbol(symbol, series_by_source, target_date):
    bars = cross_validate(series_by_source)   # list[ConsensusBar] 升序
    dates = sorted({b.dt.date() for b in bars})
    prev_list = [d for d in dates if d < target_date]
    prev = prev_list[-1] if prev_list else None

    # 采集 needed set + 判断可算性
    needed = set()
    computable = target_date in dates and prev is not None
    if computable:
        for d in (prev, target_date):
            for t in SAMPLE_TIMES:
                i = sample_index(bars, d, t)
                if i is None:
                    computable = False
                    continue
                win = windows_for(bars, i)
                if win is None:
                    computable = False
                    continue
                w15, w60 = win
                needed.update(w15)
                needed.update(w60)

    # 质量
    if not computable:
        quality = "data_unavailable"
    else:
        quals = {bars[j].quality for j in needed}
        worst = max(quals, key=lambda q: _Q_RANK[q])
        quality = {"missing": "data_unavailable", "conflict": "data_conflict",
                   "unverified": "unverified", "confirmed": "confirmed"}[worst]

    # 状态与命中(state_for_date 在 indicators 中对 None close 已返回 incomplete)
    from scanner.indicators import state_for_date
    state_t = state_for_date(bars, target_date) if target_date in dates else "incomplete"
    state_prev = state_for_date(bars, prev) if prev else "incomplete"
    hit, _ = detect_hit(bars, target_date) if computable else (False, None)
    if quality in ("data_unavailable", "data_conflict"):
        hit = False

    # 采样明细与收盘价
    samples = {}
    for t in SAMPLE_TIMES:
        i = sample_index(bars, target_date, t)
        a, b = (_ab_at(bars, i) if i is not None else (None, None))
        key = t.replace(":", "")
        samples[f"a_{key}"] = a
        samples[f"b_{key}"] = b
    i1500 = sample_index(bars, target_date, "15:00")
    close = bars[i1500].close if i1500 is not None else None

    return ScanResult(symbol=symbol, hit=hit, state_t=state_t, state_prev=state_prev,
                      quality=quality, close=close, samples=samples)
```

> 注意:`state_for_date` 与 `_ab_at` 现接收 `ConsensusBar`(其 `.close` 可能为 None)。`_ab_at` 已处理 None → (None,None);`state_for_date` 遇 None → `incomplete`。无需改动它们(Bar 与 ConsensusBar 都有 `.dt`/`.close`,鸭子类型兼容)。

- [ ] **Step 4: 运行,确认通过**

Run: `.venv/bin/python -m pytest tests/test_evaluate.py -v`
Expected: 3 passed(冲突降级、缺历史不可用、命中接线)。

- [ ] **Step 5: Commit**

```bash
git add scanner/evaluate.py tests/test_evaluate.py
git commit -m "feat: integrate per-symbol evaluate (xval+state+hit+quality)"
```

---

### Task 7: 东财数据源适配器(akshare)

**Files:**
- Create: `scanner/sources/__init__.py`
- Create: `scanner/sources/base.py`
- Create: `scanner/sources/eastmoney.py`
- Test: `tests/test_sources_eastmoney.py`

**Interfaces:**
- Consumes: `scanner.model.Bar`、`scanner.symbols.to_secid`、spike 文档确认的东财时间戳约定
- Produces:
  - `scanner.sources.base.KLineSource`(协议:`name: str`,`fetch_15min(symbol: str, days: int = 5) -> list[Bar]`,升序、收盘时刻、失败抛异常)
  - `scanner.sources.eastmoney.EastmoneySource`

- [ ] **Step 1: 写 base 协议**

`scanner/sources/base.py`:
```python
from typing import Protocol
from scanner.model import Bar


class KLineSource(Protocol):
    name: str

    def fetch_15min(self, symbol: str, days: int = 5) -> list[Bar]:
        """返回最近 days 个交易日的 15 分钟收盘 Bar,升序,dt=收盘时刻/Asia-Shanghai。失败抛异常。"""
        ...
```
创建空 `scanner/sources/__init__.py`。

- [ ] **Step 2: 写失败测试(mock akshare 返回)**

`tests/test_sources_eastmoney.py`:
```python
import pandas as pd
from unittest.mock import patch
from datetime import date
from scanner.sources.eastmoney import EastmoneySource


def _fake_df():
    # 模拟 akshare stock_zh_a_hist_min_em 的返回(时间为收盘时刻,列名按 spike 文档)
    return pd.DataFrame({
        "时间": ["2026-07-21 10:30:00", "2026-07-21 10:45:00"],
        "收盘": [10.11, 10.22],
    })


def test_eastmoney_normalizes_to_bars():
    with patch("scanner.sources.eastmoney.ak.stock_zh_a_hist_min_em", return_value=_fake_df()):
        bars = EastmoneySource().fetch_15min("000001", days=5)
    assert len(bars) == 2
    assert bars[0].close == 10.11
    assert bars[0].dt.strftime("%Y-%m-%d %H:%M") == "2026-07-21 10:30"
    assert str(bars[0].dt.tzinfo) == "Asia/Shanghai"


def test_eastmoney_sorted_ascending():
    df = pd.DataFrame({"时间": ["2026-07-21 10:45:00", "2026-07-21 10:30:00"], "收盘": [2.0, 1.0]})
    with patch("scanner.sources.eastmoney.ak.stock_zh_a_hist_min_em", return_value=df):
        bars = EastmoneySource().fetch_15min("000001")
    assert [b.close for b in bars] == [1.0, 2.0]
```

> 若 spike 文档显示东财实际列名不是 `时间`/`收盘`,在此按实测列名修改测试与实现(保持接口不变)。

- [ ] **Step 3: 运行,确认失败**

Run: `.venv/bin/python -m pytest tests/test_sources_eastmoney.py -v`
Expected: FAIL,`No module named 'scanner.sources.eastmoney'`。

- [ ] **Step 4: 写 eastmoney.py**

`scanner/sources/eastmoney.py`:
```python
from datetime import datetime, timedelta
import akshare as ak
from scanner.model import Bar, TZ

# SPIKE 实测确认:东财时间为收盘时刻,offset=0;列名 ['时间','开盘','收盘',...],时间格式 YYYY-MM-DD HH:MM:SS。
# 东财连接高频抖动(spike 单次 5/5 失败过);本适配器保持"单次尝试、失败即抛",重试策略由
# scan.fetch_all_sources(Task 10)统一承担;若东财整体不可用,3 源交叉校验降级为腾讯+新浪≥2 源。
CLOSE_OFFSET_MIN = 0
_TIME_COL = "时间"
_CLOSE_COL = "收盘"


class EastmoneySource:
    name = "east"

    def fetch_15min(self, symbol: str, days: int = 5) -> list[Bar]:
        df = ak.stock_zh_a_hist_min_em(symbol=symbol, period="15", adjust="")
        bars = []
        for _, row in df.iterrows():
            dt = datetime.strptime(str(row[_TIME_COL]).strip(), "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=TZ) + timedelta(minutes=CLOSE_OFFSET_MIN)
            bars.append(Bar(dt, float(row[_CLOSE_COL])))
        bars.sort(key=lambda b: b.dt)
        # 只保留最近 days 个交易日
        keep = sorted({b.dt.date() for b in bars})[-days:]
        return [b for b in bars if b.dt.date() in set(keep)]
```

- [ ] **Step 5: 运行单测,确认通过**

Run: `.venv/bin/python -m pytest tests/test_sources_eastmoney.py -v`
Expected: 2 passed。

- [ ] **Step 6: 写并运行真实 smoke 测试**

在 `tests/test_sources_eastmoney.py` 追加(东财抖动大,smoke 里包一层重试,验证的是"可达且能解析",非重试策略):
```python
import time
import pytest


@pytest.mark.smoke
def test_eastmoney_smoke_real():
    last = None
    for attempt in range(5):
        try:
            bars = EastmoneySource().fetch_15min("000001", days=5)
            break
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    else:
        pytest.skip(f"东财 5 次重试仍不可达(境内抖动),非解析问题:{last}")
    assert len(bars) >= 16                      # 至少一天
    times = {b.dt.strftime("%H:%M") for b in bars}
    assert "15:00" in times and "10:30" in times
```
Run: `.venv/bin/python -m pytest tests/test_sources_eastmoney.py -v -m smoke`
Expected: PASS(联网);若东财持续抖动 5 次仍失败则 SKIP(可接受,生产端由 scan 层重试 + 3 源降级兜底)。若是解析错误(KeyError/格式),回到 spike 文档核对 `_TIME_COL`/`_CLOSE_COL`。

- [ ] **Step 7: Commit**

```bash
git add scanner/sources/__init__.py scanner/sources/base.py scanner/sources/eastmoney.py tests/test_sources_eastmoney.py
git commit -m "feat: add Eastmoney(akshare) 15min source adapter"
```

---

### Task 8: 腾讯数据源适配器

**Files:**
- Create: `scanner/sources/tencent.py`
- Test: `tests/test_sources_tencent.py`

**Interfaces:**
- Consumes: `Bar`、`to_secid`、spike 文档确认的腾讯时间戳约定
- Produces: `scanner.sources.tencent.TencentSource`(同 `KLineSource` 接口)

- [ ] **Step 1: 写失败测试(mock requests)**

`tests/test_sources_tencent.py`:
```python
from unittest.mock import patch, MagicMock
from scanner.sources.tencent import TencentSource


def _fake_resp():
    # SPIKE 实测:时间是紧凑串 YYYYMMDDHHMM(无分隔符),data[secid] 除 m15 外还含 qt/prec,
    # m15 元素 = [time, open, close, high, low, volume, {}, extra];close 在索引 2。
    m = MagicMock()
    m.json.return_value = {"data": {"sz000001": {
        "qt": {}, "prec": "9.9",
        "m15": [
            ["202607211030", "10.0", "10.11", "10.2", "9.9", "1000.00", {}, "0.64"],
            ["202607211045", "10.1", "10.22", "10.3", "10.0", "900.00", {}, "0.55"],
        ]}}}
    return m


def test_tencent_normalizes():
    with patch("scanner.sources.tencent.requests.get", return_value=_fake_resp()):
        bars = TencentSource().fetch_15min("000001", days=5)
    assert len(bars) == 2
    assert bars[0].close == 10.11
    assert bars[0].dt.strftime("%Y-%m-%d %H:%M") == "2026-07-21 10:30"
    assert str(bars[0].dt.tzinfo) == "Asia/Shanghai"
```

> SPIKE 实测:腾讯 m15 元素 = `[time, open, close, high, low, volume, {}, extra]`,close 在索引 2;`time` 为 12 位紧凑串 `YYYYMMDDHHMM`(无分隔符/无秒),用 `%Y%m%d%H%M` 解析。

- [ ] **Step 2: 运行,确认失败**

Run: `.venv/bin/python -m pytest tests/test_sources_tencent.py -v`
Expected: FAIL,`No module named 'scanner.sources.tencent'`。

- [ ] **Step 3: 写 tencent.py**

`scanner/sources/tencent.py`:
```python
from datetime import datetime, timedelta
import requests
from scanner.model import Bar, TZ
from scanner.symbols import to_secid

CLOSE_OFFSET_MIN = 0        # SPIKE 实测确认:腾讯时间为收盘时刻,offset=0
_CLOSE_IDX = 2


class TencentSource:
    name = "tx"

    def fetch_15min(self, symbol: str, days: int = 5) -> list[Bar]:
        sec = to_secid(symbol)
        # SPIKE 实测:必须用 ifzq.gtimg.cn;web.ifzq.gtimg.cn 会 301 到已失效的 web3.* (NXDOMAIN)
        url = (f"https://ifzq.gtimg.cn/appstock/app/kline/mkline"
               f"?param={sec},m15,,320")
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        node = r.json()["data"][sec]
        rows = node.get("m15") or node.get("qfqm15") or []
        bars = []
        for row in rows:
            dt = datetime.strptime(row[0].strip(), "%Y%m%d%H%M")   # 紧凑格式,无分隔符
            dt = dt.replace(tzinfo=TZ) + timedelta(minutes=CLOSE_OFFSET_MIN)
            bars.append(Bar(dt, float(row[_CLOSE_IDX])))
        bars.sort(key=lambda b: b.dt)
        keep = set(sorted({b.dt.date() for b in bars})[-days:])
        return [b for b in bars if b.dt.date() in keep]
```

- [ ] **Step 4: 运行单测,确认通过**

Run: `.venv/bin/python -m pytest tests/test_sources_tencent.py -v`
Expected: 1 passed。

- [ ] **Step 5: 写并运行 smoke**

追加:
```python
import pytest


@pytest.mark.smoke
def test_tencent_smoke_real():
    bars = TencentSource().fetch_15min("000001", days=5)
    assert len(bars) >= 16
    assert {b.dt.strftime("%H:%M") for b in bars} >= {"10:30", "15:00"}
```
Run: `.venv/bin/python -m pytest tests/test_sources_tencent.py -v -m smoke`
Expected: PASS。失败则核对 spike 里腾讯 close 索引与时间约定,修正 `_CLOSE_IDX`/`CLOSE_OFFSET_MIN`。

- [ ] **Step 6: Commit**

```bash
git add scanner/sources/tencent.py tests/test_sources_tencent.py
git commit -m "feat: add Tencent 15min source adapter"
```

---

### Task 9: 新浪数据源适配器

**Files:**
- Create: `scanner/sources/sina.py`
- Test: `tests/test_sources_sina.py`

**Interfaces:**
- Consumes: `Bar`、`to_secid`、spike 文档确认的新浪时间戳约定
- Produces: `scanner.sources.sina.SinaSource`(同 `KLineSource` 接口)

- [ ] **Step 1: 写失败测试(mock requests)**

`tests/test_sources_sina.py`:
```python
import json
from unittest.mock import patch, MagicMock
from scanner.sources.sina import SinaSource


def _fake_resp():
    m = MagicMock()
    m.text = json.dumps([
        {"day": "2026-07-21 10:30:00", "open": "10.0", "high": "10.2", "low": "9.9", "close": "10.11", "volume": "1000"},
        {"day": "2026-07-21 10:45:00", "open": "10.1", "high": "10.3", "low": "10.0", "close": "10.22", "volume": "900"},
    ])
    return m


def test_sina_normalizes():
    with patch("scanner.sources.sina.requests.get", return_value=_fake_resp()):
        bars = SinaSource().fetch_15min("000001", days=5)
    assert len(bars) == 2
    assert bars[0].close == 10.11
    assert bars[0].dt.strftime("%Y-%m-%d %H:%M") == "2026-07-21 10:30"
    assert str(bars[0].dt.tzinfo) == "Asia/Shanghai"
```

- [ ] **Step 2: 运行,确认失败**

Run: `.venv/bin/python -m pytest tests/test_sources_sina.py -v`
Expected: FAIL,`No module named 'scanner.sources.sina'`。

- [ ] **Step 3: 写 sina.py**

`scanner/sources/sina.py`:
```python
import json
from datetime import datetime, timedelta
import requests
from scanner.model import Bar, TZ
from scanner.symbols import to_secid

CLOSE_OFFSET_MIN = 0        # SPIKE 实测确认:新浪时间为收盘时刻,offset=0(day 字段 YYYY-MM-DD HH:MM:SS)
# 注:新浪成交量单位为"股"(东财/腾讯为"手",差 100 倍);本项目只用收盘价,不受影响。


class SinaSource:
    name = "sina"

    def fetch_15min(self, symbol: str, days: int = 5) -> list[Bar]:
        sec = to_secid(symbol)
        url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               f"CN_MarketData.getKLineData?symbol={sec}&scale=15&ma=no&datalen=120")
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        arr = json.loads(r.text)
        bars = []
        for row in arr:
            dt = datetime.strptime(row["day"].strip(), "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=TZ) + timedelta(minutes=CLOSE_OFFSET_MIN)
            bars.append(Bar(dt, float(row["close"])))
        bars.sort(key=lambda b: b.dt)
        keep = set(sorted({b.dt.date() for b in bars})[-days:])
        return [b for b in bars if b.dt.date() in keep]
```

- [ ] **Step 4: 运行单测,确认通过**

Run: `.venv/bin/python -m pytest tests/test_sources_sina.py -v`
Expected: 1 passed。

- [ ] **Step 5: 写并运行 smoke**

追加:
```python
import pytest


@pytest.mark.smoke
def test_sina_smoke_real():
    bars = SinaSource().fetch_15min("000001", days=5)
    assert len(bars) >= 16
    assert {b.dt.strftime("%H:%M") for b in bars} >= {"10:30", "15:00"}
```
Run: `.venv/bin/python -m pytest tests/test_sources_sina.py -v -m smoke`
Expected: PASS。失败则核对 spike 里新浪时间约定,修正 `CLOSE_OFFSET_MIN`。

- [ ] **Step 6: Commit**

```bash
git add scanner/sources/sina.py tests/test_sources_sina.py
git commit -m "feat: add Sina 15min source adapter"
```

---

### Task 10: 批量扫描 + 重试 + fail-fast 阈值

**Files:**
- Create: `scanner/scan.py`
- Test: `tests/test_scan.py`

**Interfaces:**
- Consumes: `evaluate_symbol`、三个 Source、`ScanResult`
- Produces:
  - `scanner.scan.fetch_all_sources(symbol, sources, retries=3, sleep_s=0.4) -> dict[str, list[Bar]]`(逐源抓取,单源失败重试后置空,不抛)
  - `scanner.scan.scan_symbols(symbols: list[str], sources: list, target_date, fail_ratio: float = 0.05) -> tuple[list[ScanResult], dict]`(返回 (结果列表, 汇总);若 `data_unavailable+data_conflict` 占比 > fail_ratio,抛 `RuntimeError`)

- [ ] **Step 1: 写失败测试(用假源)**

`tests/test_scan.py`:
```python
import pytest
from datetime import date
from scanner.model import Bar, TZ
from scanner.scan import scan_symbols, fetch_all_sources
from tests.conftest import make_series


class FakeSource:
    def __init__(self, name, days_map=None, fail=False):
        self.name = name
        self._bars = make_series(days_map) if days_map else []
        self._fail = fail

    def fetch_15min(self, symbol, days=5):
        if self._fail:
            raise ConnectionError("boom")
        return self._bars


def test_fetch_all_sources_skips_failures():
    good = FakeSource("east", {date(2026,7,21): [10.0]*16})
    bad = FakeSource("tx", fail=True)
    out = fetch_all_sources("000001", [good, bad], retries=2, sleep_s=0)
    assert "east" in out and len(out["east"]) == 16
    assert out["tx"] == []          # 失败源置空,不抛


def test_scan_symbols_raises_when_too_many_unavailable():
    # 所有股票都无数据 → 100% unavailable > 5% → 抛
    bad = FakeSource("east", fail=True)
    with pytest.raises(RuntimeError):
        scan_symbols(["000001", "000002"], [bad], date(2026,7,21), fail_ratio=0.05)
```

- [ ] **Step 2: 运行,确认失败**

Run: `.venv/bin/python -m pytest tests/test_scan.py -v`
Expected: FAIL,`No module named 'scanner.scan'`。

- [ ] **Step 3: 写 scan.py**

`scanner/scan.py`:
```python
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
```

- [ ] **Step 4: 运行,确认通过**

Run: `.venv/bin/python -m pytest tests/test_scan.py -v`
Expected: 2 passed。

- [ ] **Step 5: 全量单测回归**

Run: `.venv/bin/python -m pytest -v`
Expected: 全部 passed(smoke 默认跳过)。

- [ ] **Step 6: Commit**

```bash
git add scanner/scan.py tests/test_scan.py
git commit -m "feat: add batch scan with retry and fail-fast threshold"
```

---

## 交付物(计划① 完成后)

- `scanner/` 包:给定 `symbols + target_date + [三个 Source]` → `scan_symbols` 返回命中 `ScanResult` 列表 + 汇总,数据异常超阈值即报错。
- 全套单测(纯逻辑合成数据)+ 标记的真实 smoke 测试。
- `docs/superpowers/spikes/2026-07-24-data-sources.md`:三源可达性/字段/时间戳约定实测结论。

## 后续计划(② / ③,在①跑通后据 spike 结果编写)

- **计划②(编排 + D1)**:`universe.py` 解析成分并集(沪深300/500/1000/全创业板/科创50);D1 建表(`run_state`/`sample_daily`/`signals`);Python 生成幂等 upsert SQL + `wrangler d1 execute --file` 写入;GitHub Actions 工作流(hourly cron `5 7-19 * * 1-5`、`concurrency` group、交易日判定、游标状态机、`BATCH_SIZE=300`、fail-fast 阈值联动)。
- **计划③(展示)**:Workers + Static Assets;Worker Function `/api/signals`、`/api/symbol`、`/api/status` 查 D1;单页前端(当日命中 + 历史 + 数据不完整提示、深浅色自适应)。
