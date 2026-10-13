# GitHub Actions 自动化设计

日期：2026-10-13
适用仓库形态：**公开仓库**（前提：官方文档确认公开仓库 + 标准 hosted runner 完全免费，Actions 分钟数不设限）

---

## 1. 官方调度限制（已核实，2026-10-13 抓取自 docs.github.com）

| 事实 | 原文依据 | 对我们的影响 |
|---|---|---|
| 高负载时定时任务会延迟 | "The schedule event can be delayed during periods of high loads of GitHub Actions workflow runs." | 不能假设 10:00 准点 |
| **高负载时段是"每个整点开始"** | "High load times include the start of every hour." | **所有 cron 必须避开 `:00`** |
| **排队任务可能被直接丢弃** | "If the load is sufficiently high enough, some queued jobs may be dropped." | 单点触发 = 可能当天完全不跑 → **必须多触发点 + 幂等** |
| 最短间隔 5 分钟 | "The shortest interval you can run scheduled workflows is once every 5 minutes." | 触发点密度上限 |
| 默认 UTC，**支持 IANA 时区** | "By default, scheduled workflows run in UTC. You can optionally specify a timezone using an IANA timezone string" | 直接用 `timezone: Asia/Shanghai`，避免 UTC 换算错误 |
| 只在默认分支最新提交上运行 | "Scheduled workflows run on the latest commit on the default branch." | 定时任务用的是 main 的代码 |
| 公开仓库免费 | "GitHub Actions usage is free for ... public repositories that use standard GitHub-hosted runners." | 成本模型的基础 |
| 60 天无活动会停用定时任务 | （GitHub 长期政策，需在实现时复核） | 我们的日报本身每天提交，天然保活 |

---

## 2. 工作流总览

```
collect.yml  ──(artifact: raw-<shard>)──┐
  matrix: 6 shards                       │
  cron: 09:53 / 10:07 / 10:23 / 10:41     │   ← 北京时间，互为兜底（官方：任务可能被丢弃）
  + 关键源等待闸门（juya 当日版最多等 20 分钟）│
                                         ▼
analyze.yml  ──(artifact: digest)──► publish.yml
  needs: collect                        needs: analyze
  dedup → cluster → llm                 render 速览+深度 → 5 路分发
                                        cron 同上 + 幂等闸门
```

| 工作流 | 触发 | 职责 | 超时 | 权限 |
|---|---|---|---|---|
| `collect.yml` | schedule ×4（09:53/10:07/10:23/10:41）、workflow_dispatch、repository_dispatch | matrix 分片采集 100 源，产出原始 JSONL artifact；含关键源等待闸门 | 25 min | `contents: read` |
| `analyze.yml` | `workflow_run`(collect 成功)、workflow_dispatch | 去重 + 聚类 + LLM 分析，产出 digest artifact | 40 min | `contents: read` |
| `publish.yml` | `workflow_run`(analyze 成功)、workflow_dispatch | 幂等检查 → 渲染速览版+深度版 → 分发 → 提交 | 30 min | `contents: write`, `pages: write`, `id-token: write` |
| `health.yml` | 每周日 03:17 | 全源探测，更新 health，开 Issue 报告死源 | 60 min | `contents: write`, `issues: write` |
| `ci.yml` | push/PR | 单测 + 覆盖率 + **源覆盖守卫** + 密钥扫描 + PII 检查 | 15 min | `contents: read` |
| `pages.yml` | publish 提交后 | 构建 Pagefind 索引并部署 Pages | 15 min | `pages: write`, `id-token: write` |

---

## 3. 关键设计（逐条回答任务书 §七 的 8 个问题）

### Q1 定时任务的实际调度限制
见 §1。三条硬约束：**会延迟、可能被丢弃、整点最拥挤**。

### Q2 定时延迟的处理方式 —— 多触发点 + 幂等守卫 + 关键源等待闸门

```yaml
on:
  schedule:
    # 北京时间 10:00 目标窗口：4 个触发点互为兜底（避开整点，官方文档：整点最拥挤）
    # 第一个成功发布的生效，其余被幂等闸门 no-op
    - cron: "53 9 * * *"
    - cron: "7 10 * * *"
    - cron: "23 10 * * *"
    - cron: "41 10 * * *"
      timezone: "Asia/Shanghai"
  workflow_dispatch:
    inputs:
      force: {type: boolean, default: false}
```

**为什么最早是 09:53 而不是 10:00**：juya 实测 09:48 发布，需要给它一点余量；而 GitHub 的定时任务只会**延迟**不会提前，所以 09:53 触发、实际 09:55–10:15 启动，正好落在 juya 发布之后。

**关键源等待闸门**（`collect` 之后、`analyze` 之前，解决"juya 迟到就漏"的残留风险）：
```python
CRITICAL = ["rss:juya", "rss:dailydawn", "rss:hex2077"]
deadline = now + timedelta(minutes=cfg.critical_wait_minutes)   # 默认 20
while now < deadline and (missing := [s for s in CRITICAL if not has_today(s)]):
    sleep(120)
    refetch(missing)          # 只重抓缺失的关键源，不重跑全量（省时间也省配额）
if missing:
    digest.warnings.append(f"{missing} 当日版未发布，本期使用 T-1 版本")
    # 不阻塞发布 —— 宁可发一份标注清楚的日报，也不发半成品或什么都不发
```

`publish.yml` 的第一个 job 是**幂等闸门**（继承 daily-briefing 已验证的做法）：

```yaml
- name: Idempotency gate
  id: gate
  run: |
    python -m aidaily gate --date "$(TZ=Asia/Shanghai date +%F)"
    # 退出码 0 → 未发布过，继续；退出码 10 → 今日已发布 → 后续 job 全部 skip
```
判据来自 `data/state/runs.jsonl`：
```json
{"date":"2026-10-14","status":"published","at":"2026-10-14T10:12:03+08:00","digest_id":"...","kind":["brief","deep"]}
```
**注意**：速览版与深度版是**同一次发布的原子产物**，幂等以"天"为单位而不是以"档"为单位（10:00 单跑）。若深度版渲染失败但速览版成功，`runs.jsonl` 记录 `partial`，下次触发点会**只补深度版**。

### Q3 避免多个工作流同时改同一批文件

1. **单写者原则**：只有 `publish.yml` 有 `contents: write`。`collect.yml` / `analyze.yml` 只读，通过 **artifact** 传递数据，不写仓库。
2. **全局并发组**：
```yaml
concurrency:
  group: aidaily-publish          # 所有写入者共用同一组
  cancel-in-progress: false       # 不取消，排队即可（取消会丢已发布状态）
```
3. **push 冲突重试**（继承 ai-daily-sources 与 daily-briefing 已有做法）：`git push` 失败 → `git fetch + rebase` → 重试最多 5 次，冲突时对 `data/state/*.jsonl` 用 `--theirs` 后继续。
4. **文件级分区**：`state/items/2026-10.jsonl` 按天只追加不重写 → 两个并发 run 的 diff 天然不冲突。

### Q4 防止因 API 失败生成不完整日报

**三级闸门**：
```yaml
- name: Completeness gate
  run: |
    python -m aidaily verify --digest "$DIGEST" \
      --min-sources 20 \            # 至少 20 个源成功
      --max-source-failure-rate 0.5 \  # 失败率 > 50% 则拒绝发布
      --min-events 5 \              # 至少 5 个事件
      --require-schema
```
- 闸门不过 → **不发布**，改为开 Issue + 发一条"今日数据不全"的简短通知（而不是发半成品日报）
- digest 内**强制写入 `warnings`**（哪些源失败、覆盖率多少），日报页面上如实展示
- `source_coverage: {total: 100, active: 78, failed: 12, degraded: 10}` 每次都打进 digest，读者可见

### Q5 失败后重跑而不重复处理与发布

| 失败点 | 恢复方式 |
|---|---|
| collect 某分片失败 | matrix `fail-fast: false`；该分片缺失不影响其他分片；`workflow_dispatch` 可只重跑该分片 |
| analyze 失败 | 重跑从 artifact 读取同一批原始数据（**不重新抓取**，避免数据漂移） |
| publish 部分通道失败 | 每通道独立 try/except，失败通道写入 `state/delivery.jsonl`；**重跑只补发失败通道**（`--resume` 语义） |
| 全部失败 | 幂等闸门未写入 → 下一个触发点自动重试 |

**核心：artifact 是天然的检查点。** 重跑不重抓。

### Q6 避免仓库历史与日报无限膨胀

| 措施 | 细节 |
|---|---|
| 月度分片 zstd 压缩 | `state/items/2026-10.jsonl.zst`，比纯 JSONL 小 5–8 倍 |
| 正文分层 | 全文只留 30 天（`window/content/`），过期只留 simhash + 链接 |
| 图片不入仓 | 走 R2（你已有密钥）；或按 ai-daily-sources 策略镜像到 `img/<date>/` 且 30 天清理 |
| 年度归档 | 每年把上一年分片打成 `archive/2026.tar.zst` 提交一次，之后不再变动 |
| 日报产物 | 每日 2 个 md + 1 个 json ≈ 60 KB/天 ≈ 22 MB/年，可接受 |
| OG 图 | **不提交**（dailydawn 现在每天 2 张 PNG 入库，一年 ~35 MB，属于可优化项），改为构建时生成并只上传 Pages artifact |
| 定期体检 | `health.yml` 顺带统计仓库体积，超阈值开 Issue |

预估：**中等情景下每年 ~180 MB**（含压缩后分片 + 日报 + 站点）。

### Q7 不依赖常驻服务器

全部逻辑跑在 Actions；状态在 git；分发走 SMTP/Bot API/Webhook/Pages。`python -m aidaily run` 可在本地复现同一流程（本地跑用 `.env`，不依赖任何云端状态）。这也是"幂等 + artifact 检查点"设计带来的额外收益。

### Q8 什么时候才需要数据库/云函数/服务器

| 场景 | 是否已需要 | 建议 |
|---|---|---|
| 现在（100 源、2 档/天） | ❌ | Actions 足够 |
| 源 > 300 个，或需要每小时刷新 | ⚠️ 接近上限 | 先加分片；仍不够再考虑 |
| 需要跨全历史语义搜索（>7 天） | ✅ 需要 | 引入 Supabase pgvector 或本地 Qdrant |
| 需要 Web UI 管理源/查看实时状态 | ✅ 需要 | Cloudflare Pages + Workers + D1（你已有 CF 账号，成本最低） |
| 需要用户订阅/多租户 | ✅ 需要 | 独立服务 + 数据库 |
| 需要分钟级推送（突发事件） | ✅ 需要 | 常驻 Worker + Cron Triggers |

**结论**：以你当前目标（每日日报 + 三通道分发 + n8n），**Actions 足够，且是维护成本最低的选择**。等出现上表 ✅ 的需求再升级，架构已留好接口。

---

## 4. 工作流文件骨架

### 4.1 `collect.yml`
```yaml
name: collect
on:
  schedule:
    # 北京时间 09:53 / 10:07 / 10:23 / 10:41 —— 互为兜底，避开整点
    - cron: "53 9 * * *"
      timezone: "Asia/Shanghai"
    - cron: "7 10 * * *"
      timezone: "Asia/Shanghai"
    - cron: "23 10 * * *"
      timezone: "Asia/Shanghai"
    - cron: "41 10 * * *"
      timezone: "Asia/Shanghai"
  workflow_dispatch:
permissions: {contents: read}
concurrency: {group: aidaily-collect, cancel-in-progress: false}
jobs:
  collect:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    strategy:
      fail-fast: false
      matrix:
        shard: [rss-cn, rss-en, api-community, api-dev, scrape, relay-digest]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12", cache: pip}
      - run: pip install -e ".[fetchers]"
      - name: Fetch shard
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          PRODUCT_HUNT_TOKEN: ${{ secrets.PRODUCT_HUNT_TOKEN }}
          REDDIT_CLIENT_ID: ${{ secrets.REDDIT_CLIENT_ID }}
          REDDIT_CLIENT_SECRET: ${{ secrets.REDDIT_CLIENT_SECRET }}
        run: python -m aidaily collect --shard ${{ matrix.shard }} --out raw/${{ matrix.shard }}.jsonl
      - name: Critical-source wait gate   # 只对含关键源的分片执行
        if: matrix.shard == 'relay-digest' || matrix.shard == 'rss-cn'
        run: python -m aidaily wait-critical --raw raw/ --timeout-min 20
      - uses: actions/upload-artifact@v4
        if: always()          # 部分失败也要上传，保住已抓到的数据
        with:
          name: raw-${{ matrix.shard }}-${{ github.run_id }}
          path: raw/
          retention-days: 3
```

### 4.2 `analyze.yml`
```yaml
on:
  workflow_run: {workflows: [collect], types: [completed]}
jobs:
  analyze:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    timeout-minutes: 40
    steps:
      - uses: actions/download-artifact@v4     # 下载全部 raw-* 分片
      - run: python -m aidaily analyze --raw raw/ --out digest.json --deadline-s 1800
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          CEREBRAS_API_KEY: ${{ secrets.CEREBRAS_API_KEY }}
          RELAY_KEYS_JSON: ${{ secrets.RELAY_KEYS_JSON }}
          LLM_DAILY_BUDGET_CALLS: "400"
      - uses: actions/upload-artifact@v4
        with: {name: digest-${{ github.run_id }}, path: digest.json, retention-days: 7}
```

### 4.3 `publish.yml`（关键：幂等 + 分通道容错 + 防半成品）
```yaml
on:
  workflow_run: {workflows: [analyze], types: [completed]}
permissions: {contents: write, pages: write, id-token: write}
concurrency: {group: aidaily-publish, cancel-in-progress: false}
jobs:
  publish:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - uses: actions/download-artifact@v4      # digest
      - name: Idempotency gate
        id: gate
        run: python -m aidaily gate --digest digest.json >> "$GITHUB_OUTPUT"
      - name: Completeness gate
        if: steps.gate.outputs.skip != 'true'
        run: python -m aidaily verify --digest digest.json
      - name: Render
        if: steps.gate.outputs.skip != 'true'
        run: python -m aidaily render --digest digest.json --out out/
      - name: Deliver (per-channel isolated)
        if: steps.gate.outputs.skip != 'true'
        env:
          SMTP_HOST: ${{ secrets.SMTP_HOST }} # ...其余 secrets
        run: python -m aidaily publish --out out/ --resume   # 只补发未成功的通道
      - name: Commit state
        if: steps.gate.outputs.skip != 'true'
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/ site/
          git diff --staged --quiet && exit 0
          git commit -m "chore: daily digest $(TZ=Asia/Shanghai date +%F)"
          for i in 1 2 3; do git push && exit 0; git fetch origin main && git rebase origin/main || exit 1; done
          exit 1
```

### 4.4 `ci.yml` 的守卫测试（这是"不会丢失信息源"的制度保障）
```yaml
- name: Source coverage guard        # 六仓库每个源定义位置都必须仍被覆盖
  run: pytest tests/contract/test_source_coverage.py -q
- name: Secret leak scan             # 防止凭据入仓
  run: |
    pip install detect-secrets
    detect-secrets scan --baseline .secrets.baseline --exclude-files '\.lock$'
    git grep -nIE '(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{36}|cfat_[A-Za-z0-9]+|AKIA[0-9A-Z]{16})' -- . && exit 1 || exit 0
- name: No PII in config
  run: pytest tests/contract/test_no_pii.py -q   # 断言仓库内不出现邮箱/chat_id
```

---

## 5. 通知与可观测性

| 事件 | 通道 |
|---|---|
| 发布成功 | 日报本身即通知 |
| 完整性闸门拦截 | Issue（label: `data-incomplete`）+ Telegram 短消息 |
| 连续 2 天失败 | Issue（label: `urgent`） |
| 死源周报 | 每周 Issue，列出 `health_status=dead` 的源与最后成功时间 |
| LLM 预算超限 | 运行摘要中标注，不单独通知 |

每次运行产出 `data/state/runs.jsonl` 一条结构化摘要：`{date, kind, shards_ok, sources_ok, sources_failed, items_raw, items_after_l2, events, published, llm_calls, llm_tokens, cost_estimate, duration_s}`。这是后续优化的唯一真实数据来源——**所有成本与性能结论都必须从这里读，不许拍脑袋**。
