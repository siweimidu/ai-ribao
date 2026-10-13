# 统一 AI 日报平台 · 架构设计

版本：v1（基于六仓库实测审计 + 第 1 轮需求澄清）
日期：2026-10-13
上游依据：`audit/AUDIT_REPORT.md`、`audit/sources_ledger.json`、`audit/DECISIONS.md`

---

## 1. 一句话架构

> **一个 Python 模块化单体内核（继承 Horizon，MIT）+ 可插拔采集适配器（继承你自有的 6 个文件）+ 三层去重引擎 + 统一 LLM 分层调用 + 单次采集渲染双版本（速览/深度）+ 文件即数据库（JSONL 月度分片 + 静态搜索），全部跑在 GitHub Actions 上，零常驻服务器。**

**运行节奏**：北京时间 **10:00 单跑一次**。一次采集 → 去重聚类 → 分析一次 → 渲染两份产物：
- **速览版**（≤15 条）→ QQ 邮件 + Telegram
- **深度版**（≤60 条 + 趋势段落）→ GitHub Pages + RSS + n8n + 历史归档

即"数据只算一遍，产物出两份"，比跑两遍省一半 LLM 额度。

---

## 2. 四套方案对比与推荐（你说"你推荐"，这是我的判断依据）

### 2.1 方案定义

| | 方案 A 纯 Actions 极简 | 方案 B 模块化 Python 单体 | 方案 C 工作流编排并行 | **方案 D 数据库完整平台** |
|---|---|---|---|---|
| 形态 | 1 个 workflow，1 个脚本 | 1 个 workflow，多模块包 | N 个 workflow 分片采集 | 常驻服务 + Postgres |
| 状态 | 无 | 文件 | 文件 | 数据库 |
| 代表 | ai-daily-sources 现状 | dailydawn 现状 | — | Horizon + Supabase |
| 上线速度 | 1 天 | 3–5 天 | 1 周 | 3 周+ |

### 2.2 统一维度比较（依据见下方脚注）

| 维度 | A | B | C | D |
|---|---|---|---|---|
| 信息源完整性 | 中（单点失败即丢源） | 高 | **最高**（分片隔离，单片失败不拖累全局） | 最高 |
| 去重准确性 | 低（仅 URL） | 中高 | 中高 | **最高**（可跨全历史语义检索） |
| 运行速度 | 快（源少时） | 中 | **快**（并行矩阵） | 快 |
| 稳定性 | 低 | 中 | **高** | 高 |
| LLM 兼容性 | 低（硬编码） | **高**（统一层） | 高 | 高 |
| 部署难度 | **极易** | 易 | 中 | 难 |
| 维护成本 | 低 | 中 | 中 | **高** |
| 运行成本 | **0** | **0** | **0** | $0–25/月（Supabase 免费档/Pro） |
| 扩展能力 | 差 | 好 | **好** | 最好 |
| 数据持久化 | 弱 | 中（git 即存储） | 中 | **强** |
| 安全性 | 中 | 好 | 好 | 好（但多一个攻击面） |
| 对 Actions 依赖 | 100% | 100% | 100% | 部分 |

脚注（技术依据）：
- A 的"信息源完整性中"：单 workflow 内一个源异常若未被 per-source try/except 包裹会中断全批。实测 `dailydawn/scripts/fetchers/base.py::safe_fetch` 已做兜底，说明这个坑是真实存在的。
- C 的"最高完整性"：GitHub Actions 矩阵任务之间相互隔离，单 job 崩溃只影响自己的分片。官方文档明确 schedule 事件"部分排队任务可能被丢弃"——分片后丢掉一片只损失该片源，不分片则全丢。
- D 的"最高去重准确性"：跨全历史的语义去重需要向量检索；纯文件方案只能做滚动窗口（见 §6.3）。
- **运行成本 0 的前提**：官方文档（2026-10-13 核实）"GitHub Actions usage is free for ... **public repositories** that use standard GitHub-hosted runners"。私有仓库仅 2000 分钟/月，本规模下会超。

### 2.3 推荐：**B + C 融合**，并保留升级到 D 的接口

**为什么不是纯 B**：100 个源、单日 2000+ 条目、速览+深度两份产物，单 job 串行很容易撞上 Actions 的 job 时长上限（官方上限 6 小时，但我们自设 25/40 分钟更保守）与"定时任务被丢弃"双重风险。
**为什么不是 D**：你要的是"零维护、自动跑"。Postgres 会带来备份、迁移、连接池、密钥轮换四类新维护面。而你的真实数据量（日均 300 篇摘要）**远未到需要数据库的规模**。
**为什么不是 A**：六仓库有 100 条源、三种采集范式、三层去重，A 撑不住，且你已经吃过"源挂了没人知道"的苦。

**升级路径（关键）**：内核的存储层抽象成 `StorageBackend` 接口，v1 实现 `JsonlBackend`（文件）。将来若某天你确实需要跨全历史语义检索，只需新增 `PostgresBackend` 实现同一接口，**上层模块一行不改**。

**接受的代价（必须明说）**：
1. 语义去重只能做 **7 天滚动窗口**，超过 7 天的"同一事件不同报道"无法自动合并（会各自成条）。
2. 全文搜索基于 Pagefind 静态索引，**只索引已发布日报**，不能搜索未入选的原文。
3. 月度 JSONL 分片会让仓库每年增长约 165 MB（中等假设），需要季度归档压缩。
4. 依然 100% 依赖 GitHub Actions：Actions 全面故障时无兜底（可用本地 `python -m aidaily run` 手动补跑）。

---

## 3. 系统架构图

```
                          ┌──────────────────────────────────────┐
                          │  sources/registry.yaml  (100 条唯一源) │
                          │  + sources/provenance.jsonl (溯源)     │
                          └───────────────┬──────────────────────┘
                                          │ 读
        ┌─────────────────────────────────┼──────────────────────────────────┐
        │            GitHub Actions: collect.yml (matrix 分片 × 6)            │
        │  shard=rss-cn | rss-en | api-community | api-dev | scrape | relay    │
        └───────┬─────────────┬──────────────┬─────────────┬───────────┬──────┘
                │             │              │             │           │
        ┌───────▼──┐  ┌───────▼──┐  ┌────────▼───┐  ┌──────▼───┐  ┌────▼─────┐
        │RSS/Atom/ │  │ 官方 API │  │ 社区 API   │  │ 网页抓取 │  │ 聚合日报 │
        │JSONFeed  │  │ HN/GH/HF │  │ Reddit/V2EX│  │  BS4     │  │ juya 等  │
        └───────┬──┘  └───────┬──┘  └────────┬───┘  └──────┬───┘  └────┬─────┘
                └─────────────┴──────────────┴─────────────┴───────────┘
                                          │  RawItem[]
                          ┌───────────────▼───────────────┐
                          │  ingest: 清洗 / 规范化 / 时间归一 │
                          └───────────────┬───────────────┘
                                          │ NormalizedItem[]
                    ┌─────────────────────▼─────────────────────┐
                    │  L1 源级去重 (registry 构建期, 一次性)      │
                    │  L2 文章级去重 (URL/canonical/simhash/标题) │
                    └─────────────────────┬─────────────────────┘
                                          │ 当日候选集
                          ┌───────────────▼───────────────┐
                          │  规则过滤 + 质量打分 (无 LLM)   │
                          └───────────────┬───────────────┘
                                          │ 精选 ~150 条
                          ┌───────────────▼───────────────┐
                          │  L3 语义事件聚类 (LLM+嵌入)     │
                          │  仅对候选集，7 天滚动窗口       │
                          └───────────────┬───────────────┘
                                          │ Event[]
                          ┌───────────────▼───────────────┐
                          │  LLM 分层调用层 (official-free │
                          │  → official-paid → relay)      │
                          │  分类/摘要/深度分析/事实校验    │
                          └───────────────┬───────────────┘
                                          │ Digest
        ┌─────────────────────────────────┼──────────────────────────────────┐
        │                        publish.yml (单 job，幂等)                   │
        └──┬──────────┬──────────┬──────────┬──────────┬──────────┬─────────┘
           │          │          │          │          │          │
      ┌────▼───┐ ┌───▼────┐ ┌───▼────┐ ┌───▼────┐ ┌───▼─────┐ ┌──▼──────┐
      │GitHub  │ │  RSS   │ │  QQ    │ │Telegram│ │  n8n    │ │ 历史    │
      │Pages   │ │ feed   │ │ 邮件   │ │ 推送   │ │ Webhook │ │ JSONL   │
      │+Pagefind│ │xml+json│ │ SMTP   │ │ Bot API│ │         │ │ +归档页 │
      └────────┘ └────────┘ └────────┘ └────────┘ └─────────┘ └─────────┘
```

---

## 4. 模块清单（职责 / 输入 / 输出 / 异常）

| # | 模块 | 职责 | 输入 | 输出 | 异常处理 |
|---|---|---|---|---|---|
| M1 | `scheduler` | 决定"现在该跑哪一档"（速览/深度），幂等判定 | workflow 触发参数、`state/runs.jsonl` | `RunPlan` | 已跑过则直接退出 0（幂等守卫） |
| M2 | `registry` | 加载/校验/合并信息源总账 | `sources/registry.yaml` | `SourceSpec[]` | schema 校验失败 → 失败退出（这是配置错误，必须人修） |
| M3 | `fetchers/*` | 6 类采集适配器 | `SourceSpec` | `RawItem[]` | **per-source try/except**，失败写 `health` 不抛全局 |
| M4 | `http` | 统一 HTTP：超时/重试/UA/缓存/限速 | URL+策略 | `Response` | 指数退避 3 次；ETag/Last-Modified 条件请求；429 读 `Retry-After` |
| M5 | `parse` | RSS/Atom/JSONFeed/HTML 抽取 | 原始字节 | `RawItem` | 解析失败 → 该源标 degraded，不中断 |
| M6 | `normalize` | URL 规范化、时间归一 UTC、文本清洗、语言识别 | `RawItem` | `NormalizedItem` | 时间缺失 → 标 `unknown`，绝不猜 |
| M7 | `dedup.l1_source` | 源级去重（构建期） | registry 原始条目 | 唯一源 + 合并画像 | 冲突分类**保留全部**（不覆盖） |
| M8 | `dedup.l2_item` | 文章级去重 | `NormalizedItem[]` | `ItemCluster[]` | 低置信度 → 不合并（保守优先） |
| M9 | `dedup.l3_event` | 语义事件聚类 | 候选集 + 7 天窗口锚 | `Event[]` | LLM 失败 → 退化为 L2 结果，流水线继续 |
| M10 | `quality` | 规则质量打分（长度/来源权重/时效/热度） | `ItemCluster` | `score: float` | 纯函数，无外部依赖 |
| M11 | `rank` | 分类 + 优先级排序 + 配额分配 | scored items | `SelectedSet` | 配额不足 → 按类目降级而非丢弃 |
| M12 | `llm` | 统一 LLM 调用层（多供应商/降级/限流/成本） | prompt + 约束 | `LLMResult` | 三层降级 + 预算熔断 |
| M13 | `analyze` | 摘要/深度分析/交叉验证 | `SelectedSet` | `Analysis` | 单条失败 → 跳过该条并记录 |
| M14 | `render` | 渲染速览版/深度版/Markdown/HTML/邮件 | `Digest` | 字符串 | 模板错误 → 失败退出（不发送半成品） |
| M15 | `publish/*` | Pages/邮件/Telegram/RSS/n8n 五路分发 | 渲染结果 | 送达回执 | **每路独立 try/except**，一路失败不影响其余 |
| M16 | `store` | JSONL 分片读写 + 归档 + R2 冷存（可选） | `Digest`/`Item` | 文件 | 写失败 → 中止发布（宁可重跑） |
| M17 | `health` | 源健康检查与报表 | 历史 `health.jsonl` | 健康报告 | — |
| M18 | `obs` | 结构化日志、运行摘要、失败通知 | 全局 | `logs/*.jsonl` + Issue | 通知失败不阻断 |
| M19 | `search_index` | 生成 Pagefind 静态索引 | 已发布 HTML | 索引文件 | — |

**依赖方向（严格单向，禁止反向 import）**：
`registry → fetchers → http/parse → normalize → dedup → quality → rank → llm/analyze → render → publish → store → obs`

---

## 5. 数据模型

### 5.1 核心结构（Pydantic v2）

```python
class SourceSpec(BaseModel):
    source_id: str                # 稳定 ID，形如 "rss:juya"（永不变，用于跨版本追踪）
    name: str
    url: str                      # 原始 URL（原样保留，禁止改写）
    normalized_url: str           # 规范化后（去重键）
    domain: str
    category: str                 # zh-media / lab-official / lab-blog / paper / digest /
                                  # community / media / dev / model / dataset / trend / search
    language: str | None          # zh / en / mixed / None(未知)
    source_type: str              # rss | atom | jsonfeed | api | scrape
    fetch_method: str             # feedparser | httpx_json | bs4 | playwright
    adapter: str                  # 适配器类名
    original_repository: str      # 溯源：来自哪个仓库
    original_file: str            # 溯源：文件路径
    original_config_key: str      # 溯源：配置键（或行号）
    enabled: bool
    priority: int                 # 1..5
    polling_interval: str         # 如 "6h" / "1d"
    timeout_s: int
    needs_credential: str | None  # 环境变量名，如 "PRODUCT_HUNT_TOKEN"
    dedup_group: str | None       # 同站多频道分组，防止过度合并
    health_status: str            # healthy | degraded | dead | needs_credential | unverified | disabled
    last_success_at: str | None
    last_failure_at: str | None
    notes: str | None
    aliases: list[str] = []       # 在其他仓库中的叫法（保留差异，不覆盖）

class NormalizedItem(BaseModel):
    item_id: str                  # sha256(canonical_url or native_id)[:16]
    source_id: str
    title: str
    title_norm: str               # 小写、去标点、去空白、去版本噪声
    url: str
    canonical_url: str | None     # 从页面 <link rel=canonical> 提取（仅必要时抓取）
    published_at: datetime | None # UTC；缺失为 None，绝不用抓取时间冒充
    fetched_at: datetime          # UTC
    first_seen_at: datetime
    updated_at: datetime
    language: str | None
    summary: str
    content_text: str | None      # 只保留 30 天滚动
    content_sha256: str
    simhash: int                  # 64-bit
    author: str | None
    metrics: dict                 # {score, comments, stars_today, ...} 保留源特有指标
    age_bucket: str               # today | past_72h | older | today_window | unknown（继承 dailydawn）
    dup_group_id: str | None      # L2 聚类结果
    event_id: str | None          # L3 聚类结果
    also_seen_in: list[str] = []  # 其他也报道该文的 source_id（跨源证据）

class Event(BaseModel):
    event_id: str
    title: str                    # 事件级标题（LLM 生成，非原文标题）
    member_item_ids: list[str]
    primary_item_id: str          # 代表条目
    source_ids: list[str]         # 全部报道来源（**完整性核心字段**）
    all_urls: list[str]           # 全部原始链接（**永不丢失**）
    first_seen_at: datetime
    last_updated_at: datetime
    published_range: tuple[datetime, datetime] | None
    unique_facts: dict[str, list[str]]  # 各源独有信息：{source_id: [fact, ...]}
    confidence: float             # 聚类置信度 0-1
    evidence_level: str           # single_source | multi_source | official_confirmed
    needs_review: bool            # 低置信度 → 人工复核队列

class Digest(BaseModel):
    date: str                     # 发布日（Asia/Shanghai）
    kind: str                     # brief | deep
    generated_at: datetime
    window: tuple[datetime, datetime]
    headline: str
    top_events: list[Event]
    sections: dict[str, list[Event]]   # 分类分组
    trend_notes: list[str] | None      # 深度版才有
    source_coverage: dict              # {total, active, failed, degraded}
    llm_usage: dict                    # {provider, model, calls, tokens_in, tokens_out, cost_estimate}
    warnings: list[str]                # 数据不全时的显式声明
```

### 5.2 存储布局（文件即数据库）

```
data/
├─ registry/
│  ├─ sources.yaml            # 100 条唯一源（构建产物，人审后提交）
│  └─ provenance.jsonl        # 每条源的完整溯源链（一个源多行 = 多仓库出现）
├─ items/
│  ├─ 2026-10.jsonl.zst       # 月度文章分片（元数据+摘要，永久）
│  └─ 2026-11.jsonl.zst
├─ events/
│  └─ 2026-10.jsonl.zst       # 事件聚类结果（含全部来源链接）
├─ digests/
│  ├─ 2026/2026-10-14.brief.md
│  ├─ 2026/2026-10-14.deep.md
│  └─ 2026/2026-10-14.json    # 机器可读版（给 n8n）
├─ state/
│  ├─ runs.jsonl              # 幂等账本：哪天跑了哪档、结果如何
│  ├─ health.jsonl            # 每个源的滚动健康记录
│  ├─ llm_usage.jsonl         # 每次调用的 token/成本
│  └─ seen_index.sqlite       # ⚠️ 运行期缓存，**不提交**（.gitignore）
└─ window/
   └─ content/2026-10-14/     # 正文全文滚动 30 天，过期清理
```

**为什么 SQLite 不提交**：SQLite 每次写入会改写整个文件，git 会每天存一份完整二进制副本，一年膨胀数十 GB。它只作为**单次运行内的去重索引缓存**，运行结束即丢弃，由 JSONL 分片重建。

---

## 6. 三层去重算法设计（对应任务书 §三.2，三层规则严格分离）

> 核心原则：**重复的源、同一篇文章的多次抓取、多篇不同文章报道同一事件——这是三个不同的问题，用三套不同的键、不同的阈值、不同的动作。**

### 6.1 L1 源级去重（构建期，一次）

**目的**：把 107 条原始记录合并成 100 条唯一源，且**不丢信息**。

**判定键（按优先级）**：
1. `normalized_url` 完全相等 → 同一源
2. 同域名 + 同 path + 仅 query 不同 → 需人工规则判定（例：`lwn.net/headlines/rss` vs `lwn.net/headlines/full_text?key=` 是**不同源**，因为内容不同）
3. 同站不同语言频道（`dailydawn.dev/zh.json`）→ **不同源，但互相标记 `dedup_group=dailydawn`**

**URL 规范化规则**（实现于 `normalize.py`，可单测）：
```
1. 协议统一为 https
2. host 小写、去 www.
3. 去 fragment
4. 去追踪参数：utm_*, ref, source, fbclid, gclid, mc_cid, mc_eid, spm, from
5. 保留功能性参数：listId, id, q, hl, gl, ceid, key（这些决定内容）
6. path 去尾斜杠（但 "/" 保留）
7. **不做** 大小写归一（path 大小写敏感，如 GitHub 用户名）
```

**合并策略（关键：保留而非覆盖）**：
```yaml
# 合并后同一源的多个画像全部保留
- source_id: "rss:juya"
  url: "https://daily.juya.uk/rss.xml"
  categories: ["zh-media"]         # 三仓库都是 zh-media，无冲突
  aliases: ["AI日报 juya", "橘鸦AI早报", "Juya AI 早报"]   # 三个仓库三种叫法，全保留
  found_in:                        # 完整溯源链
    - {repo: "Horizon", file: "data/config.github.json", key: "sources.rss[0]"}
    - {repo: "daybrief", file: "config.yaml", key: "sources.rss[0]"}
    - {repo: "ai-daily-sources", file: "scripts/collect.py", key: "SOURCES[0]"}
```

**分类冲突处理**：不做"投票取胜"。合并为 `categories: [...]` 数组，并记录各仓库原始分类。展示时用 primary（优先级最高的仓库），但数据不丢。

**防误删机制**：`tests/test_source_coverage.py` 断言 —— 对六仓库每一个 `original_repository+original_file+original_config_key` 三元组，registry 中必须存在至少一条源指向它。**新增/删除源若破坏覆盖，CI 直接红。**

### 6.2 L2 文章级去重（每次运行）

**目的**：同一篇文章被抓多次 / 被转载 / 被镜像 → 合并成一条，保留全部链接。

**分层判定（从严到宽，命中即停）**：

| 层级 | 键 | 动作 | 阈值 |
|---|---|---|---|
| L2-a | `canonical_url` 完全相等 | 合并，保留所有 url | 精确 |
| L2-b | `normalized_url` 相等 | 合并 | 精确 |
| L2-c | `content_sha256` 相等 | 合并（完全同文，含镜像站） | 精确 |
| L2-d | `simhash` 汉明距离 ≤ 3 **且** 发布时间差 ≤ 72h | 合并 | 距离≤3，标题相似度≥0.85 |
| L2-e | `title_norm` 相等 **且** 同域名 | 合并（同站改标题重发） | 精确 |
| L2-f | `title_norm` 相似度 ≥ 0.92 **且** 发布时间差 ≤ 24h **且** 不同域名 | **标记为疑似**，不自动合并 | 保守 |

**为什么 L2-f 不自动合并**：不同媒体的相似标题可能是不同的两件事（例如"OpenAI 发布新模型"在两天的两篇报道）。误合并比漏合并代价高得多——**丢失信息不可逆，重复只是噪音**。

**标题规范化 `title_norm`**：
```
1. Unicode NFKC 归一
2. 转小写
3. 去标点/空白/emoji
4. 去常见噪声前缀："【】"、"独家 |"、"Breaking:"、"| 机器之心"
5. 去版本号噪声：v1.0 / 2026 之类保留（可能是关键区分）
```

**合并结果结构**（保证"保留不同来源提供的独有信息"）：
```json
{
  "dup_group_id": "d3f2...",
  "primary_item_id": "a1b2...",       // 信息最全的那条
  "member_item_ids": ["a1b2", "c3d4"],
  "all_urls": ["https://...", "https://mirror..."],
  "source_ids": ["rss:juya", "rss:ainewslog"],
  "first_seen_at": "2026-10-14T06:12:00Z",
  "updated_at": "2026-10-14T07:45:00Z",
  "published_at": "2026-10-13T09:48:17+08:00",   // 取最早的原始发布时间
  "merged_content": "主文全文\n\n--- 来自 rss:ainewslog 的补充 ---\n<独有段落>"
}
```
即：继承 Horizon 已验证的做法（`orchestrator.py` 中跨源合并正文），而不是 dailydawn 的"仅 URL 去重"或 ai-daily-sources 的"标题前 60 字"。

### 6.3 L3 语义事件聚类（每次运行，仅对候选集）

**目的**：不同文章报道同一事件 → 聚成一个 Event，交叉验证。

**为什么只对候选集做**：100 源全量做嵌入的成本与时间都不可接受。先用规则把当日几千条压到 ~150 条候选。

**流程**：
```
1. 候选集 = 通过 L2 去重 + 质量分的 top N（默认 N=150）
2. 生成聚类特征（低成本，不用嵌入模型）：
   - 实体抽取：正则 + 词典（模型名/公司名/人名，词典从 registry 的 name 字段自动构建）
   - 时间桶：按 6 小时分桶
   - 关键词：TF-IDF top 8（本地计算，零成本）
3. 粗聚类：实体重叠 ≥ 2 且同一时间桶 → 候选簇（纯算法，零 LLM 成本）
4. 精判定：对每个候选簇，用**小模型**（免费额度）问一个二分类问题：
   "以下 N 条标题是否在报道同一件事？回答 JSON: {same_event: bool, confidence: 0-1, reason}"
5. 置信度 < 0.75 → needs_review=true，**不合并**，但记录在案
6. 跨日合并：读取最近 7 天 events 分片中标题+实体的轻量锚，
   若新事件与旧事件实体重叠 ≥3 且相似度 ≥0.9 → 并入旧事件（更新 last_updated_at）
```

**成本**：150 条 → 粗聚类后通常 20–40 个候选簇 → 20–40 次小模型调用/天。这就是"哪些任务必须用大模型"的答案（见 §7.3）。

**"防止把相关但不同的新闻错误合并"的四道闸**：
1. 实体重叠门槛（≥2 个不同实体）
2. 时间窗限制（同 6 小时桶）
3. 置信度阈值（0.75）
4. `needs_review` 队列 + 深度版显式标注"本事件由 N 个来源报道，聚簇置信度 0.82"

### 6.4 三层统计口径（日报中如实展示，不夸大）

```
原始抓取条目数        raw_fetched
→ L2 去重后条目数      after_l2        （差值 = 重复抓取/转载）
→ 聚类后事件数         after_l3        （差值 = 同一事件的多篇报道）
→ 入选日报条目数       published
→ 其中多源事件数       multi_source    （质量指标，越高说明交叉验证越好）
```

---

## 7. 统一 LLM 调用层设计

### 7.1 三层供应商架构

```yaml
llm:
  tiers:
    - name: official-free          # 主力：官方免费额度
      providers:
        - {id: gemini,   type: native-gemini,  base_url: "https://generativelanguage.googleapis.com/v1beta/openai", key_env: GEMINI_API_KEY}
        - {id: groq,     type: openai-compat,  base_url: "https://api.groq.com/openai/v1", key_env: GROQ_API_KEY}
        - {id: cerebras, type: openai-compat,  base_url: "https://api.cerebras.ai/v1", key_env: CEREBRAS_API_KEY}
        - {id: sambanova,type: openai-compat,  base_url: "https://api.sambanova.ai/v1", key_env: SAMBANOVA_API_KEY}
        - {id: openrouter,type: openai-compat, base_url: "https://openrouter.ai/api/v1", key_env: OPENROUTER_API_KEY}
    - name: official-paid          # 可选，默认关闭
      providers: [...]
    - name: relay                  # 兜底：你提供的 130 个第三方 key
      providers_file_env: RELAY_KEYS_JSON   # 内容来自 GitHub Secret，绝不入库
      policy: {allow_personal_data: false, max_calls_per_run: 20}
```

**关键区分（对应任务书要求"区分原生 API / OpenAI 兼容 / 需独立适配器"）**：

| 供应商 | 接口类型 | 实现方式 |
|---|---|---|
| Gemini | **OpenAI 兼容端点存在**，但原生 REST 更稳 | 双实现：`NativeGeminiClient`（`generateContent`）+ `OpenAICompatClient`。daybrief 实测原生 REST 可用（`groq_brief.py::GeminiProvider`） |
| Groq / Cerebras / SambaNova / OpenRouter / DeepSeek / 通义 / 智谱 / 月之暗面 / 豆包 | **OpenAI 兼容** | 只换 `base_url` + `model`，走同一个 client |
| Cloudflare Workers AI | 自有 REST（非 OpenAI 协议） | 需独立适配器 `CloudflareAIClient` |
| Anthropic | 原生 Messages API | Horizon 已有 `anthropic` 实现，复用 |
| Cohere | 原生 v1/v2 | 独立适配器 |

→ 结论：**不能假定"只换一个 URL"**。统一层用 `LLMClient` 抽象 + `capabilities` 声明（是否支持 `response_format: json_object`、是否支持 system role、最大上下文），运行时按能力裁剪请求。

### 7.2 可靠性设计（直接继承三个已验证的机制）

| 机制 | 来源 | 做法 |
|---|---|---|
| 模型降级链 | dailydawn `llm.py::get_models` | 主模型 + `FALLBACK_MODELS` 逗号分隔，429 就换下一个 |
| 供应商拉黑 | daybrief `Provider.mark_down` | 遇到 `429 + "per day"` 直接拉黑本次运行，**绝不空等** |
| 全局 deadline | daybrief `RUN_DEADLINE` | 全局 monotonic deadline，超时即降级/收尾，防止 Actions 超时被杀 |
| 指数退避 | dailydawn `tenacity` | 5 次尝试，2/4/8/16s 退避封顶 60s；**限流不重试**（重试只会白等配额窗口） |
| 成本熔断 | 新增 | `max_tokens_per_run` / `max_calls_per_run`，超限改用规则摘要并标注 |

### 7.3 哪些任务必须用 LLM，哪些必须用传统算法（成本关键）

| 任务 | 方案 | 依据 |
|---|---|---|
| URL 规范化 | **纯算法** | 确定性规则，LLM 会引入不确定性 |
| L2 文章去重 | **纯算法** | simhash/hash 精确可靠，成本 0 |
| 质量打分 | **纯算法**（长度/来源权重/时效/热度加权） | 可解释、可调、0 成本 |
| 分类打标 | **纯算法优先**（关键词+源类目）→ 不确定时小模型 | registry 已有 category 字段，大部分无需 LLM |
| L3 事件聚类粗筛 | **纯算法**（实体+时间桶） | 把候选从 150 压到 ~30，省 80% 调用 |
| L3 事件聚类精判 | **小模型**（二分类，短 prompt） | 需要语义理解，但任务简单 |
| 摘要生成 | **中模型，批量** | daybrief 实测 8 条/批，28 条只需 ~4 次调用 |
| 深度分析/趋势判断 | **大模型**（唯一必须用大模型的地方） | 需要跨事件推理 |
| 事实校验（防幻觉） | **规则 + 小模型**：断言 URL 必须在原始 source_urls 集合内、日期必须来自 `published_at` | daily-briefing 的"Exactly 3 URLs, copied verbatim"思路 |
| 渲染/排序/分发 | **纯算法** | — |

**默认策略**：`规则 → 小模型 → 大模型` 三级漏斗，每级只把上一级的"不确定"交给下一级。

### 7.4 防幻觉硬约束（写进系统提示词 + 输出后校验）

```
系统约束：
1. 只能使用提供的 items 中的信息；不得补充原文没有的事实
2. 每个事件必须输出 source_ids 与 urls，URL 必须逐字来自输入（程序会校验，不符则整条丢弃）
3. 日期只能使用输入中的 published_at；缺失时写"时间未知"，禁止推断
4. 观点与事实必须分离：facts[] / inferences[] / opinions[] 三个独立字段
5. 无法确证的信息写入 uncertainties[]，禁止写成肯定句
输出后程序校验：
- 所有 url ∈ 输入 url 集合（否则丢弃该条并记录）
- 所有 published_at ∈ 输入（否则置空并标注）
- facts 非空才允许进入深度版
```

---

## 8. 统一目录结构

```
ai-daily/
├─ .github/workflows/
│  ├─ collect.yml           # 分片并行采集（matrix）
│  ├─ analyze.yml           # 去重 + 聚类 + LLM 分析
│  ├─ publish.yml           # 渲染 + 五路分发（幂等）
│  ├─ health.yml            # 每周源健康检查
│  ├─ ci.yml                # 测试 + 覆盖率守卫 + 密钥扫描
│  └─ pages.yml             # Pages 部署
├─ sources/
│  ├─ registry.yaml         # 100 条唯一源（人审提交）
│  ├─ provenance.jsonl      # 完整溯源链
│  └─ overrides.yaml        # 人工修正：禁用/改分类/改间隔（不改 registry 原文）
├─ src/aidaily/
│  ├─ __init__.py
│  ├─ cli.py                # python -m aidaily run|collect|analyze|publish|health
│  ├─ config.py             # 配置加载（YAML + env 覆盖）
│  ├─ models.py             # Pydantic 数据模型（§5.1）
│  ├─ registry/{loader,merger,validator}.py
│  ├─ http/{client,cache,ratelimit}.py
│  ├─ fetchers/{base,rss,jsonfeed,api_html,github,hackernews,reddit,huggingface,
│  │            producthunt,v2ex,googletrends,telegram,google_news,gdelt,
│  │            ossinsight,openbb,twitter,relay_digest}.py
│  ├─ parse/{feed,html,extract}.py
│  ├─ normalize/{url,time,text,lang,simhash}.py
│  ├─ dedup/{l1_source,l2_item,l3_event,entities}.py
│  ├─ quality/{scorer,filters}.py
│  ├─ rank/{classify,priority,quota}.py
│  ├─ llm/{client,providers,router,budget,json_guard}.py
│  ├─ analyze/{summarize,deepen,crosscheck,factcheck}.py
│  ├─ render/{brief,deep,markdown,html,email,feed}.py
│  ├─ publish/{pages,email,telegram,rss,n8n}.py
│  ├─ store/{jsonl,archive,index}.py
│  ├─ health/{checker,report}.py
│  └─ obs/{logging,metrics,notify}.py
├─ site/                    # 前端（Q弹动效）
│  ├─ index.html
│  ├─ assets/{css,js}
│  ├─ src/  (模板/组件)
│  └─ search-index/         # Pagefind 产物
├─ templates/               # Jinja2：日报 md/html/email
├─ data/                    # 见 §5.2（state/ 下 sqlite 不提交）
├─ tests/
│  ├─ fixtures/             # 真实源的响应快照（离线可跑）
│  ├─ unit/
│  ├─ integration/
│  └─ contract/             # 覆盖守卫：源不得丢失
├─ docs/                    # 架构/工作流/路线图/配置规范
├─ scripts/                 # 一次性工具：build_registry / probe_sources / rotate_keys
├─ pyproject.toml
├─ LICENSE  (MIT)
├─ NOTICE   (第三方归属)
└─ THIRD_PARTY_LICENSES.md
```

**前端动效**：`site/` 使用你的 `Doubao.zip`（UI 设计）与 `网页Q弹动效skills.zip` 技能产出的方案；动效实现约束为**纯 CSS + Web Animations API + 少量 IntersectionObserver**，保证 `prefers-reduced-motion` 降级、首屏 < 100 KB、Lighthouse 移动端性能 ≥ 90。响应式断点：`≤480 / 481-768 / 769-1024 / >1024`。

---

## 9. 配置规范（草案）

### 9.1 `config/daily.yaml`（非敏感，入库）
```yaml
timezone: Asia/Shanghai
# 单跑：北京时间 10:00（晚于 juya 09:48 / dailydawn 08:00 / ai-daily-sources 08:02，可拿到全部当日内容）
run:
  at: "10:00"
  window_hours: 26            # 覆盖 24h + 对抗定时延迟
  critical_sources: ["rss:juya", "rss:dailydawn", "rss:hex2077"]  # 当日版必须存在，缺失则等待最多 20 分钟
  critical_wait_minutes: 20
output:
  brief: {enabled: true, max_items: 15, languages: [zh]}     # → 邮件 + Telegram
  deep:  {enabled: true, max_items: 60, languages: [zh], english_on_demand: false}  # → Pages + RSS + n8n + 归档
dedup:
  l2: {simhash_distance: 3, title_similarity: 0.92, publish_window_hours: 72}
  l3: {candidate_limit: 150, entity_overlap_min: 2, time_bucket_hours: 6,
       confidence_threshold: 0.75, cross_day_window_days: 7}
quality: {min_content_chars: 200, source_weights: {lab-official: 1.5, zh-media: 1.2, digest: 1.1, community: 0.9}}
delivery: {email: true, telegram: true, rss: true, n8n: true, pages: true}
storage: {cold: r2, r2_optional: true}      # R2 缺失时自动降级为本地存储
```

### 9.2 GitHub Secrets（**绝不入库**）
```
GEMINI_API_KEY / GROQ_API_KEY / CEREBRAS_API_KEY / SAMBANOVA_API_KEY / OPENROUTER_API_KEY
RELAY_KEYS_JSON          # 130 个中转 key，JSON 字符串，仅兜底用
SMTP_HOST / SMTP_PORT / SMTP_USERNAME / SMTP_PASSWORD / MAIL_TO
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
N8N_WEBHOOK_URL
GITHUB_TOKEN             # 用于提交与 API 限流
R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_ENDPOINT / R2_BUCKET   # 可选冷存
```

### 9.3 环境变量（非敏感，可入库为 Variables）
```
DAILY_TZ=Asia/Shanghai
RUN_KIND=brief|deep
LLM_DAILY_BUDGET_CALLS=400
LLM_DAILY_BUDGET_TOKENS=2000000
```

---

## 10. 成本模型（假设明确标注，非实测）

**已核实的配额事实（2026-10-13 抓取官方文档）**：
- GitHub Actions：**公开仓库 + 标准 hosted runner = 完全免费**（无分钟上限）
- Groq 免费档 `openai/gpt-oss-120b`：RPM 30 / **RPD 1,000** / TPM 8K / **TPD 200K**
- Gemini 免费档：按 RPM/TPM/RPD 三维限制，**RPD 太平洋时间午夜重置**，具体数值按模型不同（页面为动态表格，未取到逐模型精确值，不敢编造）

**三档情景（日均）**：

| 项 | 低 | 中 | 高 |
|---|---|---|---|
| 活跃源数 | 60 | 80 | 100 |
| 抓取条目 | 800 | 2,000 | 5,000 |
| L2 去重后 | 500 | 1,200 | 3,000 |
| L3 候选 | 80 | 150 | 250 |
| LLM 调用次数（速览+深度） | ~60 | ~180 | ~400 |
| 输入 token | 300K | 900K | 2.4M |
| 输出 token | 80K | 240K | 600K |
| Actions 运行时间/天 | ~12 min | ~30 min | ~70 min |
| Actions 成本 | **$0**（公开仓库） | **$0** | **$0** |
| LLM 成本 | **$0**（免费额度内） | $0–2 | $3–8 |
| 存储 | < 1 MB/天 | ~450 KB/天 | ~1.2 MB/天 |
| 数据库 | $0（不用） | $0 | $0 |

**中等情景下的额度校验**（这是真实约束）：
- Groq 单模型 RPD 1,000、TPD 200K → 若 180 次调用平均每次 5K token = 900K token，**超 TPD 200K 四倍以上** → **必须多供应商分摊**，这也印证了"官方免费为主 + 兜底"的架构必要性。
- 缓解手段（按性价比排序）：① 批量调用（8 条/批，daybrief 实测省 4 倍）② 规则优先漏斗 ③ 缓存命中（同一 URL 内容 30 天内不重复分析）④ 深度版只对 top 20 事件做深度分析 ⑤ 输出长度上限 ⑥ 失败不重试（限流场景）。

**免费额度会变**：所有配额与政策以官方文档为准，且可能随时调整；报告中已注明抓取日期。
