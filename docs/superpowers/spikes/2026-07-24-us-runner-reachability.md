# US-Runner 可达性 Spike 结论 (2026-07-24)

计划② 头号风险验证:三源数据能否从 GitHub 托管(美国/Azure)runner 拿到。

## 方法

- 仓库:`wu-loong/stock-monitor`(公开),workflow `us-runner-spike.yml`,`ubuntu-latest`。
- 脚本:`ci/us_runner_probe.py`,对 4 只(600000/000001/300750/688981)各源抓 5 日 15minK,每源 3 次重试。
- Run: https://github.com/wu-loong/stock-monitor/actions/runs/30067248761

## 结果

| 源 | US runner 可达 | 备注 |
|---|---|---|
| 东财 (east) | **0/4** | 全部 `ConnectionError: RemoteDisconnected`。境外 runner 上基本恒不可达(本地境内则是间歇抖动)。 |
| 腾讯 (tx) | **4/4** | 每只 72 bars(3 日 × 16 + 半日),收盘价正确(如 300750=384.89)。首请求即成功。 |
| 新浪 (sina) | **4/4** | 同上,数据与腾讯完全一致。 |

**VERDICT: GO** —— ≥2 源(腾讯+新浪)可达,交叉校验在 US runner 上可行。

## 决策(影响计划②)

1. **方案成立**:GitHub Actions(美国 runner)+ 腾讯/新浪 两源交叉校验可行,无需自建境内 runner / 代理。
2. **生产数据源 = 腾讯 + 新浪(runner 上移除东财)**:
   - 东财在境外恒挂,若保留则 2867 只 × 3 重试 × 退避 ≈ 57 分钟纯浪费 sleep。
   - 与 spec §4 降级策略"优先保留新浪+腾讯"一致;东财保留在代码中作为本地/可选源(`EastmoneySource` 不删,只是不进 runner 的 source 列表)。
   - 请求量降为 ~2870 × 2 ≈ 5700/天。
3. **两源交叉校验语义**:两源在容差 0.01 内一致 → `confirmed`;不一致 → `conflict`(排除命中);一源缺失 → 另一源 `unverified`。本次 4/4 两源收盘价完全一致,`confirmed` 为常态。

## 残留

- 单一交易日/单次探针,未观测长期稳定性与限流阈值;生产运行需保留 fail-fast(数据异常占比 >5% 报错)以监控腾讯/新浪任一劣化。
- Node20→24 弃用告警(actions/checkout、setup-python)属 GitHub 平台提示,不影响本探针;后续可升级 action 版本。
