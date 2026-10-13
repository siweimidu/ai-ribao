# 运维手册

面向"明天早上日报没出来"这类情况的处置指南。

---

## 一、Secrets 与 Variables 清单

**一个都不配也能跑。** 日报会正常生成并发布到 Pages；未配置的通道会被标记为
`skipped` 并打印警告，不会让运行失败。这样新克隆的仓库永远可以跑绿。

### 模型（至少配一个）

| 名称 | 必填 | 说明 |
|---|---|---|
| `GEMINI_API_KEY` | 推荐 | 官方免费额度，实测可用 63 个模型。**模型名用 `gemini-flash-lite-latest` 别名** |
| `GROQ_API_KEY` | 推荐 | 官方免费额度。`gpt-oss-20b` 实测可用 |
| `CEREBRAS_API_KEY` / `SAMBANOVA_API_KEY` / `NVIDIA_API_KEY` / `MISTRAL_API_KEY` / `HUGGINGFACE_API_KEY` / `MODELSCOPE_API_KEY` / `OPENROUTER_API_KEY` | 可选 | 依次加入降级链，越多越不容易被单点限流拖垮 |
| `RELAY_KEYS_JSON` | 可选 | 第三方中转兜底。**来源不明的中转不可信**，只作最后手段；单次运行硬上限 20 次调用 |

> ⚠️ **模型名会退役。** 实测 `gemini-2.5-flash-lite` 已对新用户返回
> `404 no longer available`，而 `gemini-flash-lite-latest` 别名仍有效。
> 优先用厂商的 `-latest` 别名，不要钉死具体版本号。

### 分发

| 名称 | 说明 |
|---|---|
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `MAIL_FROM_EMAIL` / `MAIL_TO` | 邮件。465 走 SSL，其它端口走 STARTTLS |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Telegram。超长内容自动分块（4096 字符上限） |
| `N8N_WEBHOOK_URL` | n8n webhook。发送结构化 JSON（含每条的 `all_urls` 与 `source_ids`） |
| `R2_ACCESS_KEY_ID` 等 | 可选冷存。缺失时自动降级为本地，不影响运行 |

### Variables（非敏感）

| 名称 | 默认 | 说明 |
|---|---|---|
| `SITE_URL` | `https://<owner>.github.io/<repo>` | 用于 RSS 与 JSON Feed 的绝对链接 |
| `GEMINI_MODEL` / `GROQ_MODEL` | `gemini-flash-lite-latest` / `openai/gpt-oss-20b` | 模型退役时不用改代码 |

---

## 二、成本控制（按性价比排序）

1. **用 `GET /models` 而不是对话请求做探活** —— 0 token。`scripts/probe_llm_channels.py` 就是这么做的。
2. **规则先于模型**：L2 去重、质量打分、分类全是纯算法，零成本。
3. **L3 先用实体+时间桶粗筛**，把当日条目从 200+ 压到几十个候选簇，模型只看值得判的。
4. **批量与并发**：L3 判定并发 4，摘要并发 3。
5. **预算熔断**：`AIDAILY_LLM__MAX_CALLS_PER_RUN` / `MAX_TOKENS_PER_RUN` 超限即降级为规则摘录，运行不失败。
6. **`max_clusters` 是主要的成本与耗时杠杆**：每个候选簇一次调用。

本次真实运行的实际消耗：**约 10 次调用 / 7,800 token**。

---

## 三、调度：为什么是四个触发点

官方文档明确三条约束，工作流的设计直接对应：

| 官方事实 | 我们的应对 |
|---|---|
| schedule 事件在高负载时会延迟 | 四个触发点，间隔 16 分钟 |
| **排队任务可能被直接丢弃** | 单个触发点意味着当天可能完全不跑 |
| **整点是高负载时段** | cron 用 `:53 / :07 / :23 / :41`，避开 `:00` |
| 默认 UTC，但支持 IANA 时区 | 用 `timezone: Asia/Shanghai`，不手算 UTC |

**为什么是 10:00 而不是 07:00**：实测 juya 在 **09:48** 发布、dailydawn 在 08:00、
ai-daily-sources 在 08:02。07:00 运行会**系统性地**拿到这三个源的**前一天**版本。

**关键源等待闸门**：juya 的 12 分钟余量不是排期而是巧合。缺当日版的关键源会每 2 分钟
重抓一次（只重抓缺失的那几个），最多等 20 分钟；超时则**继续发布并在日报里写明**
哪个源退回了 T-1 版本。迟到的源永远不阻塞发布，也永远不会被悄悄掩盖。

---

## 四、故障处置

### 日报没出来

按顺序查：

1. **Actions 里 gate job 是否 exit 10** → 说明今天已经发布过了，属正常。
2. **collect 是否失败** → 看 `collect.log` 的跳过清单，每个跳过的源都有原因。
3. **事实校验是否拦下**（退出码 2）→ 说明生成的日报出现输入里没有的链接或日期。
   这是**应该拦的**，去 `publish.log` 看 `factcheck` 违规明细。
4. **分发是否失败**（退出码 3）→ 账本记为 `partial`，下一个触发点**只补失败的通道**。

### 手动补跑

```bash
# 强制忽略账本
python -m aidaily gate --date 2026-10-14 --force

# 工作流：workflow_dispatch 勾选 force，或勾选 skip_collect 复用上次采集的制品
```

`skip_collect` 是重要的一招：**重试时不要重新抓取**，否则同一天的日报会由两份不同的
数据快照拼成。

### 某个源挂了

1. 它不会让运行失败——每个源独立 `safe_exception`，失败只记录 verdict。
2. 周报会列出 `dead` 的源（`health.yml`）。
3. **不要删除它。** 在 `sources/overrides.yaml` 里禁用并写 `reason`：

```yaml
"rss:example-com":
  enabled: false
  reason: "2026-10-14 探测返回 TLS 握手失败；替代品已在册：rss:another-source"
```

CI 会拒绝**没有 reason 的禁用**，也会拒绝**引用不存在的 source_id**——这条规则在第一次
运行时就抓出了我自己拼错的两个 ID。

### 模型全部不可用

运行不会失败：所有条目降级为来源原文摘录，日报明确标注"未调用大模型"。
排查顺序：`provider_failures`（记录每个供应商最后一次错误）→ 是否模型名退役 →
是否额度耗尽（账本里的 `dead_providers`）。

---

## 五、维护节奏

| 周期 | 动作 |
|---|---|
| 每天 | 无需人工干预。失败会体现在 Actions 状态和日报的 `warnings` 里 |
| 每周 | 看 `health.yml` 开的死源 Issue；必要时在 overrides 里禁用并写原因 |
| 每月 | 检查仓库体积（见下）；`data/state/*.jsonl` 是追加式历史 |
| 每季 | 复核模型名是否退役（`scripts/probe_llm_channels.py`，0 token）；复核免费额度政策 |
| 按需 | 重跑 `scripts/probe_sources.py` 刷新 `docs/HEALTH_REPORT.md` |

---

## 五之二、仓库体积（实测）

每天提交的产物**实测 196 KB**：

| 文件 | 字节 | 能否精简 |
|---|---|---|
| `feed/zh.json` | 53,370 | n8n 的机器可读输出，含每条的全部来源链接——这是它的用途 |
| `feed/zh.xml` | 33,157 | RSS 2.0，同上 |
| `{date}.json` | 70,140 | 归档查询用 |
| `{date}.deep.md` | 17,222 | Pages 正文 |
| `site/{date}.html` | 17,619 | Pages 页面 |
| `{date}.brief.md` | 3,644 | 邮件/Telegram 正文 |
| `site/index.html` | 356 | 归档索引 |

**约 68 MB/年**（纯文本，git 压缩后实际增长更低）。已做过一次真实的体积优化：
`digest.json` 原本把 229 个事件存了两遍（`top_events` 与 `sections` 引用同一批对象），
**253 KB → 70 KB**，一年省下 64 MB 的 git 历史。

**如果将来要压缩**，按性价比排序：
1. 把 `feed/*.json|xml` 只保留最近 90 天（RSS 阅读器很少回看更久）
2. 把 `data/state/*.jsonl` 按年归档成 `archive/2026.tar.zst`
3. 不要动 `{date}.deep.md`——那是 Pages 的内容本体，也是这个项目存在的理由

---

## 五之三、保活

GitHub 会在仓库 60 天无活动后停用定时工作流。本项目的日报**每天都提交**，
天然保活，无需额外机制。

如果有一天日报连续多日没提交（比如所有触发点都被丢弃），定时工作流本身也会被停用——
所以「连续 N 天没有提交」应该被当成**最高优先级告警**来处理。


---

## 六、修改信息源

**唯一的正确入口是 `sources/overrides.yaml`**，不是 `sources/registry.yaml`。

- `registry.yaml` 是审计产物，由 `scripts/build_registry.py` 从 `audit/sources_ledger.json` 生成。
  手工改它会在下次重新生成时被覆盖。
- `overrides.yaml` 是人类修正层，可以改 `enabled / priority / polling_interval / category /
  adapter / fetch_method / dedup_group / needs_credential`。
- **`url` / `found_in` / `source_id` 不可覆盖**——它们是证据。改写 `url` 等于把源悄悄
  指向了别的内容，改写 `found_in` 等于伪造溯源。

新增一个源：先在 `audit/sources_ledger.json` 里加记录（保留源码位置），再重新生成注册表。
CI 会校验注册表可复现：重新生成必须产出**完全相同**的 `source_id`。
