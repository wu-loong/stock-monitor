# A 股均线翻转日频扫描器 — 设计文档

- 日期:2026-07-24
- 状态:待用户 review

## 1. 背景与目标

每个交易日收盘后,扫描指定成分池(约 2870 只,实测 2026-07-24 去重后 2867),找出满足以下自定义**多周期均线翻转**条件的股票,结果写入 Cloudflare D1,并通过一个**公开**网页展示当日命中 + 历史记录。无鉴权、无推送。

- 计算层:GitHub Actions(Python)
- 存储层:Cloudflare D1
- 展示层:Cloudflare Workers + Static Assets

成本目标:全部使用免费额度,$0 运行。

## 2. 术语与信号定义(精确)

### 2.1 A 股 K 线时间结构

- 交易时段:上午 09:30–11:30,下午 13:00–15:00。
- **15 分钟 K 线**:每日 16 根,收盘时刻为
  `09:45,10:00,10:15,10:30,10:45,11:00,11:15,11:30`(上午 8 根)、
  `13:15,13:30,13:45,14:00,14:15,14:30,14:45,15:00`(下午 8 根)。
- **60 分钟 K 线**:每日 4 根,收盘时刻为 `10:30,11:30,14:00,15:00`。
  由 15 分钟 K 聚合:每根 60 分钟 K 的收盘价 = 对应时刻的 15 分钟 K 收盘价。

### 2.2 两个指标

- **指标 A(60分MA5)**:60 分钟 K 收盘价的 5 周期简单均值(取到并含当前时点)。
- **指标 B(15分MA20)**:15 分钟 K 收盘价的 20 周期简单均值(取到并含当前时点)。
- 均线一律用**收盘价**计算(锁定假设 #1)。

### 2.3 采样与状态

- 采样时点 `t ∈ {10:30, 11:30, 14:00, 15:00}`。
- 在每个 `t` 计算 `A(t)`、`B(t)`。
- 某交易日状态:
  - `all_below` ⟺ 四个时点全部满足 `A(t) < B(t)`
  - `all_above` ⟺ 四个时点全部满足 `A(t) > B(t)`
  - 否则 `mixed`
  - 严格不等,`A(t) == B(t)`(容差内相等)视为既非小于也非大于 → 破坏 all_below/all_above(锁定假设 #2)。

### 2.4 命中(信号)

对交易日 T:**命中 ⟺ `state(T-1) == all_below` 且 `state(T) == all_above`**(相邻交易日翻转,T-1 为 T 的上一交易日)。

### 2.5 数据窗口

计算 T 与 T-1 各 4 个时点的 A/B,需回溯到约 T-2 起(15分MA20 在 T-1 10:30 需 20 根 15 分钟 K,回溯至 T-2 全天)。**每只股票抓取最近 5 个交易日的 15 分钟 K 线**,留余量应对停牌/节假日缺口。

## 3. 系统架构

```
┌─ GitHub Actions (Python) ── hourly cron(收盘后时段)+ D1 游标,分批抓取/校验/计算
│        │ 写入(wrangler d1 execute --file / REST)
│        ▼
├─ Cloudflare D1 ── run_state(游标) + sample_daily(明细) + signals(命中)
│        ▲ 查询
│        │
└─ Cloudflare Workers + Static Assets ── 公开网页,Worker Function 实时查 D1(无鉴权)
```

## 4. 数据层

### 4.1 多源冗余 + 交叉校验

- 三个数据源,每只股票**都请求**,交叉校验:
  1. 东方财富(经 akshare `stock_zh_a_hist_min_em`,period=15)
  2. 腾讯(`web.ifzq.gtimg.cn` kline m15,历史约 320 根足够)
  3. 新浪(分钟线接口)
- 各源结果归一化为 `{bar_close_datetime(Asia/Shanghai): close}`。
  **时间戳约定统一到"bar 收盘时刻"**;三家原始标法(开盘时刻 vs 收盘时刻、时区)不同 → spike 阶段逐一验证并写入归一化适配层。

### 4.2 逐时间戳共识规则

对窗口内每个需要的时间戳,收集各源该时刻的收盘价(四舍五入到 2 位小数),容差 `ε = 0.01 元`:

| 情形 | 判定 | 处理 |
|---|---|---|
| ≥2 源存在且两两在 ε 内一致 | `confirmed` | 采用共识值 |
| 恰好 1 源存在 | `unverified` | 采用该值,标记 |
| ≥2 源存在但超出 ε | `conflict` | 记录各源值,标记 |
| 0 源存在 | `missing` | 无法构窗 |

### 4.3 股票级数据质量

- 任一"命中所依赖"的 bar 为 `conflict` → 该股 `data_conflict`:**排除命中**,但入 `sample_daily` 留痕。
- 构窗所需 bar 存在 `missing`(无法算齐 A/B) → `data_unavailable`:跳过。
- 全部依赖 bar 均 `confirmed` → `confirmed`。
- 含 `unverified`(单源)但无 conflict/missing → `unverified`:**允许命中,页面标记**。

### 4.4 成分池

- 默认成分范围(config,可增删):
  - 沪深300(000300,300 只)、中证500(000905,500 只)、中证1000(000852,1000 只)——CSI 三档设计上互斥,合计 1800。
  - **全创业板**(深市代码 300/301 开头,实测 1398 只)——注意是**全部创业板个股**,非创业板指成分。
  - 科创50(000688,50 只)。
- 经 akshare 取各指数成分 + 全 A 股代码表筛创业板 → 并集去重 → 按代码排序。**每个交易日首批运行时重新解析**(成分/上市会变动),快照存入当日 `run_state.universe_json`。
- **实测去重后 2867 只(2026-07-24)**;全创业板与 CSI 三档重叠 335,科创50 与其余重叠 46。规模按 ~2870 估。
- **每日请求量**:~2870 × 3 源 ≈ 8600 次。

## 5. 计算层(GitHub Actions + hourly cron + D1 游标)

### 5.1 触发

- cron(UTC):`5 7-19 * * 1-5`(北京 15:05 – 次日 03:05,约 13 个整点时槽)。
- workflow 设 `concurrency` group,禁止并行 run 争抢游标。
- 注:GitHub 定时 workflow 在仓库连续 60 天无活动后会被自动停用,需偶尔提交/手动触发唤醒。

### 5.2 单次触发流程

1. `now_sh = now(Asia/Shanghai)`;`trade_date = date(now_sh)`。
2. **交易日判定**:优先用交易日历(akshare `tool_trade_date_hist_sina`);不可用则探针(取某指数当日 15minK 是否存在)。非交易日 → 退出。
3. **收盘守卫**:`now_sh < 15:05` → 退出(等收盘)。
4. 读 `run_state[trade_date]`:
   - 不存在 → 初始化:解析成分并集去重排序,切成 `BATCH_SIZE=300` 只/批(约 10 批),写 `universe_json / total_batches / next_batch=0 / status='running'`。
   - `status == 'done'` → 退出。
5. 取 `batch = universe[next_batch]`。对批内每只股票:三源抓 5 日 15minK → 交叉校验 → 聚合 60min → 算 A/B 四点(T 与 T-1)→ 定 `state(T-1)`、`state(T)` → `hit = (all_below, all_above)`。
6. upsert `sample_daily`;命中则 upsert `signals`。
7. `next_batch++`;若 `>= total_batches` → `status='done'`。更新 `run_state`。
8. 输出进度日志。

### 5.3 自愈与幂等

- cron 漏跑/延迟 → 下一整点接着跑未完成批次。
- 重复跑同一批 → upsert 覆盖同键,结果一致。
- 时槽(13)> 批数(10),预留重试余量。

### 5.4 抓取限速

- 批内逐股请求,源间/股间 `sleep`(初值 0.3–0.5s,spike 后调);失败指数退避重试(上限 3 次)。

## 6. 存储层(Cloudflare D1)

```sql
-- 游标 / 当日运行状态
CREATE TABLE run_state (
  trade_date    TEXT PRIMARY KEY,
  universe_json TEXT NOT NULL,      -- 当日成分快照(排序后的 symbol 列表)
  total_batches INTEGER NOT NULL,
  next_batch    INTEGER NOT NULL,
  status        TEXT NOT NULL,      -- 'running' | 'done'
  updated_at    TEXT NOT NULL
);

-- 每日每股采样明细(留痕/回看/审计)
CREATE TABLE sample_daily (
  trade_date    TEXT NOT NULL,
  symbol        TEXT NOT NULL,
  name          TEXT,
  pool          TEXT,               -- 命中的所属池(可多个,逗号分隔)
  a_1030 REAL, b_1030 REAL,
  a_1130 REAL, b_1130 REAL,
  a_1400 REAL, b_1400 REAL,
  a_1500 REAL, b_1500 REAL,
  state_t       TEXT,               -- 'all_below'|'all_above'|'mixed'
  state_prev    TEXT,
  data_quality  TEXT,               -- 'confirmed'|'unverified'|'data_conflict'|'data_unavailable'
  PRIMARY KEY (trade_date, symbol)
);

-- 命中记录(页面主表)
CREATE TABLE signals (
  trade_date    TEXT NOT NULL,
  symbol        TEXT NOT NULL,
  name          TEXT,
  pool          TEXT,
  close         REAL,
  data_quality  TEXT,               -- 'confirmed' | 'unverified'
  created_at    TEXT NOT NULL,
  PRIMARY KEY (trade_date, symbol)
);
```

- 写入一律 `INSERT ... ON CONFLICT(...) DO UPDATE`(幂等)。
- 写路径:GitHub Actions 内 `npx wrangler d1 execute <DB> --remote --file=out.sql`(Python 生成 SQL 文件),CF API Token 存 GH Secret,权限仅 D1 Edit。

## 7. 展示层(Workers + Static Assets)

- 单页静态前端(HTML+JS,轻量,深浅色自适应):
  - **当日命中**:表格(代码 / 名称 / 所属池 / 收盘价 / 数据质量标记),默认最近一个交易日。
  - **历史**:选日期看当天命中;按代码搜某股历史命中日期。
  - 若某日 `run_state.status != 'done'`,页面顶部提示"该日数据不完整"。
- Worker 路由:
  - `GET /api/signals?date=YYYY-MM-DD` → 查 `signals`(默认最近交易日)。
  - `GET /api/symbol?code=XXXXXX` → 查该股历史命中。
  - `GET /api/status?date=YYYY-MM-DD` → 查 `run_state`(完整性)。
  - 其余路径 → 静态资源。
- 静态资源请求不计入 Workers 额度;D1 读远低于免费上限。

## 8. 错误处理与数据质量(fail-fast)

- 停牌 / 次新股 / 数据不足 MA 窗口 → `data_unavailable`,跳过(不可能命中)。
- 单股抓取失败 → 有界退避重试;仍失败入 `data_unavailable` 并继续。
- **系统级 fail-fast**:一日结束时,若 `data_unavailable + data_conflict` 占比 > 5%(阈值 config),该 run 退出非零(CI 标红),避免"看起来成功其实数据残缺"。
- 非交易日 → 干净退出,不写库。
- 某日直到次日仍 `status='running'` → 页面标注"数据不完整",不假装跑全。
- 时区:市场逻辑统一 `Asia/Shanghai`;cron 用 UTC。

## 9. 测试策略

- **算法单测(核心)**:构造合成 15 分钟 K 线,覆盖:
  - all_below(T-1) → all_above(T) = 命中
  - 部分翻转 / mixed = 不命中
  - 含等号(A==B)边界
  - 数据缺口、停牌
  - 60 分钟聚合正确性(收盘对齐 10:30/11:30/14:00/15:00)
- **交叉校验单测**:三源一致 / 单源 / 冲突 / 缺失 四种情形的判定。
- **数据源集成 smoke test**:少量真实股票,验证三源可达性、时间戳归一、字段。
- **D1 读写**:本地 `wrangler d1 --local` 验证建表 / upsert / 查询。

## 10. 分阶段落地

1. **Spike 数据源(最优先,先证伪)**:沪深300 中 ~20 只,实测三源从 GitHub US runner 的可达性、限速、时间戳约定、字段。数据路不通则整体方案需调整。
2. 打通单批(抓取 + 交叉校验 + 算法 + 单测)。
3. 全池分批 + D1 游标 + hourly cron。
4. D1 建库 + 写入路径。
5. Workers + Static Assets 页面 + Worker Function。

## 11. 非目标(YAGNI / 本期不做)

- 推送通知(Telegram/Bark/企业微信 等)。
- 盘中实时监控(仅收盘后日频)。
- 均线类以外的其他技术指标。
- 页面鉴权(数据无敏感性,公开)。
- 每股迷你走势图 / 指标明细下钻(本期仅命中列表 + 历史)。
- 回测 / 收益统计。

## 12. 待验证 / 风险清单

- 三源从美国 GitHub runner 的**可达性与限流**(最大不确定性)——spike 先验证。
  - **本地(境内)实测发现**(2026-07-24):东财 spot 分页接口拉到一半被断、深交所 szse.cn SSL 直接失败;仅轻量接口(中证成分、全 A 股代码表)稳定。**重接口即使在境内也会抖**,美国 runner 只会更糟 → 坚持用轻量单只 15minK 接口 + 强重试。
- 三源**时间戳约定差异**——归一化适配层需实测校准。
- GitHub Actions 定时**不准 / 漏跑**——游标自愈缓解;某日可能延迟至晚间完成。
- 仓库可见性:**已定为公开仓**(GH Actions 分钟无限;代码不含密钥,CF Token 在 GH Secret;D1 数据本就经公开页面展示,无额外泄露)。约 10 实跑 run/天 × ~10 min ≈ 2400+ min/月,私有仓 2000 免费分钟不够。
- 成分池含**全部创业板个股**(1398 只),故 universe 达 2867、请求量 ~8600/天;若改回创业板指成分(~100 只)可显著降载。
```
