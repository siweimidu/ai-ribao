# 阶段一：六仓库深度审计报告（基于真实代码）

生成时间：2026-10-13（Asia/Shanghai）
审计方法：`git clone --depth 1` 全量克隆到 `_audit/<repo>`，逐文件静态阅读；用 GitHub REST API 取仓库元数据与许可证；用 `git fetch upstream + git diff --stat` 对每个 fork 与其上游父仓库做真实差异比对。
**本文所有结论均标注证据位置（文件:行/键名）。无法验证的内容在 §7 单独列出。**

---

## 0. 结论摘要（最重要的三条）

1. **这六个仓库不是六个独立项目。** 6 个中 4 个是第三方上游的 fork，其中 2 个（Horizon、CloudFlare-AI-Insight-Daily）用户**一行源码都没改**，只改了配置和文档。因此"把六个项目的代码拼起来"这个前提本身需要修正：可复用的**用户自有代码**只有约 6 个文件（详见 §2）。
2. **Horizon 是唯一具备工程完整度的引擎**：209 文件、60+ 测试、10 类采集器、profile 评分体系、跨源去重、多厂商 AI 客户端、MCP server、邮件/Webhook 分发。MIT 许可，9.6k 星上游。建议作为统一平台的**内核**而不是被"合并"的对象。
3. **许可证存在一个真实的法律障碍**：`dailydawn` 与其上游 `TangSY/dailydawn` **均无 LICENSE**（默认保留所有权利），`CloudFlare-AI-Insight-Daily` 是 **GPL-3.0**（copyleft）。直接复制这两者的源码会让新项目要么被迫 GPL-3.0，要么侵权。详见 §4。

---

## 1. 可访问性与仓库元数据（已验证）

| 仓库 | 可访问 | 关系 | 语言 | 许可证 | 上游 | 上游星数 | 最后推送 |
|---|---|---|---|---|---|---|---|
| CloudFlare-AI-Insight-Daily | ✅ | fork | JavaScript | **GPL-3.0** | justlovemaki/CloudFlare-AI-Insight-Daily | 1803 | 2026-10-13 |
| daily-briefing | ✅ | fork | Python | MIT | tballochi/daily-briefing | 7 | 2026-10-13 |
| ai-daily-sources | ✅ | 自有 | HTML/Python | **无** | — | — | 2026-10-13 |
| daybrief | ✅ | 自有 | HTML/Python | **无** | — | — | 2026-10-13 |
| dailydawn | ✅ | fork | Python | **无** | TangSY/dailydawn | 68 | 2026-10-13 |
| Horizon | ✅ | fork | Python | MIT | Thysrael/Horizon | 9649 | 2026-10-13 |

采集过程中的真实故障（如实记录，非推测）：首次 `git clone` 时 `ai-daily-sources`、`daybrief` 报 `schannel: failed to receive handshake / Connection was reset`，重试后成功；`Horizon` 的首次 REST 元数据请求 `fetch failed`，重试后成功。均为本机网络的瞬时故障，非仓库不可访问。

---

## 2. 关键发现：用户自有代码 vs 上游代码（`git diff upstream/main HEAD` 实测）

这是本次审计价值最高的结果。它直接决定"哪些代码可以搬、哪些只能当作数据参考"。

### 2.1 CloudFlare-AI-Insight-Daily（vs justlovemaki）
```
README.md           | 325 ++++++++++++++++++++++++--
daily/2026-10-13.md |  27 +++++
rss/2026-10-13.md   |  24 ++++
3 files changed, 364 insertions(+), 12 deletions(-)
```
**用户改动 = 0 行源码。** 仅 README 与生成产物。
推论（重要）：仓库内 `wrangler.toml` 与上游一致，因此文件里出现的 4 个 Folo `LIST_ID`、`gemini-2.5-flash-preview`、`LOGIN_PASSWORD = "toor"` **都是上游默认值，不是用户生产配置**。用户真实部署的 Worker（`ai-daily.352388732.workers.dev`）的 `[vars]`/secrets 只存在于 Cloudflare 侧，**仓库中不可见**（不确定性条目 U-1）。

### 2.2 daily-briefing（vs tballochi）
```
telegram_sender.py       |  94 ++++++++++++++     ← 用户新增推送通道
scheduler.py             | 102 +++++++++++----
email_sender.py          |  36 ++++----
main.py                  |  13 +++-
config.yaml              |  65 ++++--------       ← 换成中文主题/焦点
email_sender.py/README/…
```
用户贡献：**Telegram 通道、调度与发信的强化、中文化配置**。

### 2.3 dailydawn（vs TangSY）
```
scripts/build_feed.py    | 121 +++++++++      ← 用户新增：RSS/JSON Feed 生成
scripts/build_site.py    | 184 ++++++++++     ← 用户新增：静态站点
scripts/notify_push.py   | 194 +++++++++++    ← 用户新增：Telegram+邮件推送
.github/workflows/deploy-pages.yml | 45 +++  ← 用户新增
scripts/pipeline/llm.py  | 107 ++++---        ← 上游文件被改造（多模型降级链）
README.md / README.en.md | 326/247 +++---
```
用户贡献：**RSS/JSON Feed 输出、GitHub Pages、多端推送**——恰好是本项目最需要的能力。

### 2.4 Horizon（vs Thysrael）
```
data/config.github.json | 349 ++++++++++-----   ← 唯一实质改动
.github/workflows/daily-summary.yml (从 .disabled 启用) | 14 +
docs/* + README*
```
**用户改动 = 0 行 Python 源码。** Horizon 完全靠配置驱动——这是它工程化程度的直接证据。

### 2.5 结论
> 真实可复用的"用户自有资产"清单：`dailydawn/scripts/{build_feed,build_site,notify_push}.py`、`ai-daily-sources/scripts/collect.py`、`daybrief/scripts/{groq_brief,build_site}.py`、`daily-briefing/telegram_sender.py`、以及六份**信息源配置**。

---

## 3. 逐仓库审计

### 3.1 Horizon（内核候选）
- **定位**：AI 驱动的新闻雷达，多源采集 → 评分 → 分析 → 中英双语日报 → 邮件/Webhook/企业微信。
- **入口**：`src/main.py`（CLI: `horizon --hours 24`）；另有 MCP server `src/mcp/server.py`。
- **架构**：`orchestrator.py`(44KB) 并发调度 10 类 scraper。
- **采集类型**（`src/models.py` `SOURCE_REGISTRY`，实测 10 种）：`github`（user_events / repo_releases，走 `api.github.com`）、`hackernews`（Firebase API + 前 5 条评论）、`rss`（feedparser，支持 `${ENV}` 插值）、`reddit`（`old.reddit.com` HTML 优先，JSON/RSS 三级降级，429 读 `Retry-After`）、`telegram`（`t.me/s/{channel}`）、`twitter`（官方 API 或 Playwright + Apify）、`openbb`（金融，可选依赖）、`ossinsight`、`gdelt`、`google_news`。
- **去重**：`orchestrator.py` 内含跨源重复合并（`primary.content += "--- From {source_type} ---"`，即**保留双方内容而非丢弃**），并有 `tests/test_cross_source_duplicates.py` 覆盖。
- **AI 层**：`src/ai/client.py`(24KB) 支持 openai / anthropic / azure / google-genai / minimax / dashscope / doubao / deepseek，含链式降级 `tests/test_chained_client.py`。
- **评分/画像**：`profiles/{ai-creator,finance-news,tech-blog,tech-news}/{profile,match,analysis,enrichment}.json|md` + `docs/scoring.md`，阈值可配（`threshold: 6.5`）。
- **分发**：`src/services/{email,webhook,wechat}.py`。邮件支持 `SUBSCRIBE`/`UNSUBSCRIBE` 关键词订阅管理（`smtp.qq.com:465`）。
- **定时**：`.github/workflows/daily-summary.yml`，`cron: '0 23 * * *'`，注释明确写了"intentionally runs early to offset the observed schedule delay"（**上游已知 GH 定时延迟**）。
- **测试**：`tests/` 60 个文件，含 `test_url_security.py`（SSRF 防护）、`test_balanced_digest.py`、`test_history.py`。
- **优点**：工程完整度最高；MIT；配置驱动；MCP 可被 n8n/AI Agent 调用；有真正的去重与评分。
- **缺陷**：无 RSS **输出**能力（只有 `docs/feed-*.xml` 静态示例，非生成逻辑）；Fork 的 `data/config.github.json` **把用户 QQ 邮箱与 Telegram chat_id 提交进了公开仓库**（PII 泄露）。
- **可复用**：几乎整个引擎；建议整仓作为内核而非"参考"。

### 3.2 dailydawn
- **定位**：独立开发者视角的 AI 趋势日报，中英双语。
- **入口**：`scripts/main.py` → `aggregator.aggregate()` → `pipeline/orchestrator.run_pipeline()`。
- **信息源**：7 个 fetcher（`scripts/fetchers/__init__.py` `ALL_FETCHERS`）：HackerNews(Algolia)、GitHub Trending(BS4 抓取)、Product Hunt(GraphQL，需 token)、Reddit(**12 个 subreddit**)、HuggingFace(models+datasets)、V2EX、Google Trends(**20 个种子关键词**，`pytrends`)。
- **去重**：`aggregator.py::_canonical_url()` 仅去掉 query 做 URL 级去重；跨源同 URL **分数叠加** `score + s.score*0.5`。**无内容/标题去重**。
- **时间治理（亮点）**：`age_bucket` 分档 `today / past_72h / older / today_window / unknown`，手工标注窗口类源（GitHub Trending、Google Trends）避免 LLM 幻觉；代码注释明确写了这个动机。
- **AI 层**：`scripts/pipeline/llm.py`，OpenAI 兼容协议，`LLM_API_KEY/LLM_BASE_URL/LLM_MODEL` + `LLM_FALLBACK_MODELS` 逗号分隔降级链；`tenacity` 指数退避 5 次；**429/RateLimitError 不重试，直接换模型**（设计取舍明确）。
- **流水线**：classifier → question_generator(按语言) → source_digest → experts×5 并行 → editor（`pipeline/orchestrator.py`）。
- **跨日去重**：`meta/recent-taglines.jsonl` 存最近 7 天 tagline，喂给 editor 做"禁止主题重合"硬约束 —— **这是一个很有价值的、其他仓库都没有的机制**。
- **输出**：`zh/YYYY/*.md`、`en/YYYY/*.md`、`feed/{zh,en}.{xml,json}`、`og/` 图、GitHub Pages。
- **测试**：**无测试目录**。
- **缺陷**：无许可证；无内容级去重；Google Trends 用非官方 `pytrends` 接口，注释自认会偶发 429。

### 3.3 ai-daily-sources
- **定位**：把 4 个"别人已经做好的 AI 日报"聚合成一个标准化 JSON + 镜像配图，供 n8n 读取。
- **入口**：`scripts/collect.py`（纯标准库，无需 pip install）。
- **信息源**（`SOURCES` 常量，4 条）：juya(`daily.juya.uk/rss.xml`)、ainewslog(`ainewslog.com/rss.xml`)、hex2077(`hex2077.dev/rss-zh-CN.xml`)、dailydawn(`dailydawn.dev/zh.json`, JSONFeed)。
- **亮点**：
  - **图片镜像**：把外链图下载到 `img/<date>/<sha1>.<ext>` 并改写成 `raw.githubusercontent.com` 地址，避免原站 CDN 挂掉导致日报空白；单图 >2MB 则保留远程；失败不阻塞（`Mirror.rewrite`）。
  - **RSS 全文化**：`fulltext=True` 时若摘要 <600 字则抓 `<article>/<main>` 正文。
  - **保留期治理**：`RETENTION_DAYS=30` 同时裁剪 `img/` 与 `archive/`，防止仓库膨胀。
  - **幂等/并发**：workflow `concurrency: collect-sources`，push 失败 rebase 重试 5 次。
- **去重**：URL 去 `www.`+去斜杠 + 标题去非词字符取前 60 字符，双键去重（`main()` 内 `seen_keys`）。
- **缺陷**：32 字节的 `sources.json` 里 `count: 6` 是**文章数**不是源数，容易被误读；无测试；无许可证。

### 3.4 daybrief
- **定位**：Gemini/Groq 双供应商摘要 + 邮件/Telegram/Pages。
- **入口**：`scripts/groq_brief.py` → `scripts/build_site.py`。
- **信息源**（`config.yaml`，5 条）：juya、ainewslog、dailydawn、Simon Willison Atom、hnrss frontpage。
- **AI 层（设计最"抗死"的一个）**：`Provider` 基类 + `GroqProvider`(OpenAI 兼容) + `GeminiProvider`(**原生 REST**)，`_providers = [Groq, Gemini]`；遇到 `429 + "per day"` 直接 `mark_down()` **拉黑该供应商本次运行**，绝不空等；批量 8 条一调（`BRIEF_BATCH: "8"`），28 条只需 ~4 次调用。
- **超时治理**：`RUN_DEADLINE = BRIEF_DEADLINE_S (1200s)` 全局 deadline，`time.monotonic()` 判定，超时即换供应商/停止。
- **分发**：GitHub Pages（`deploy-pages`）、QQ SMTP 邮件（465/STARTTLS 双分支）、Telegram。
- **缺陷**：无测试；无许可证；provider 硬编码在类里（新增厂商要改代码）。

### 3.5 daily-briefing
- **定位**：**工具调用型 Agent 检索**（不是 RSS 聚合）+ Groq 精选 5 条 + 邮件。
- **信息源**：**无静态源表**。`agent.py` 用 Tavily `search_news`，由 LLM 自主决定查什么（`MAX_SEARCHES = 6`）+ `config.yaml` 的 `focus.priority_query` 强制插入。设计注释写明"final URLs come from actual search results (the LLM never fabricates a link)"。
- **反幻觉取证**：`finalize_selection` 的 schema 要求"Exactly 3 URLs, copied verbatim from the search results"。
- **限流治理**：`_MIN_SEARCH_INTERVAL = 1.2s`、`_SEARCH_ATTEMPTS = 3` 退避（针对 Tavily 免费档）。
- **模型降级**：`config.yaml` `model: openai/gpt-oss-120b` + `model_fallbacks: [gpt-oss-20b, qwen3.8-27b]`；`GROQ_MODEL` 可用 repo variable 覆盖而不改代码。
- **幂等（本项目最完整）**：workflow 在 UTC `11,33,55 0,1,2 * * *` **触发 7 次**，用 bash 判断北京时区 08–11 点 + `data/history.json` 的 once-a-day guard，**第一个跑成的发布，之后的全是 no-op**。这是对 GH cron 不准的工程化应对。
- **测试**：`tests/` 8 个文件，CI 在 py3.11/3.13 矩阵跑 `pytest` + import 冒烟检查。
- **缺陷**：强依赖 Tavily 付费/免费额度；5 条产能；无 RSS 输出。

### 3.6 CloudFlare-AI-Insight-Daily
- **定位**：Cloudflare Worker 上的自助 AI 日报后台（带登录）+ 多平台分发。
- **架构**：`src/index.js` 路由式 Worker（`/getContent` `/genAIContent` `/genAIDailyPage` `/commitToGitHub` `/rss` `/login`…），KV 存数据，`src/auth.js` 自建登录（`LOGIN_USERNAME/LOGIN_PASSWORD`）。
- **信息源**：**不在仓库里**。真实源是 Folo(`api.follow.is`) 的 4 个 list（`NEWS_AGGREGATOR_LIST_ID` / `HGPAPERS_LIST_ID` / `TWITTER_LIST_ID` / `REDDIT_LIST_ID`）+ 第三方 `git-trending.justlikemaki.vip`。`src/dataSources/*.js` 是**扩展模板**（`docs/EXTENDING.md`），其中只有 5 个（news/project/paper/twitter/reddit）注册进 `dataFetchers.js`，其余 6 个（aibase/jiqizhixin/xinzhiyuan/xiaohu/qbit/huggingface-papers）**代码存在但未注册**。
- **AI 层**：`src/chatapi.js` 按 `USE_MODEL_PLATFORM = GEMINI | OPEN` 二选一；prompt 拆成 5 段（`prompt/summarizationPromptStepZero…Three` + `dailyAnalysisPrompt` + `podcastFormattingPrompt`），是**分步摘要**而非一次性。
- **分发**：提交到 GitHub 仓库 → `rss/*.md` 作为 RSS 源；另有播客脚本生成。
- **安全**：`wrangler.toml` 明文写 `GEMINI_API_KEY/OPENAI_API_KEY/GITHUB_TOKEN`，默认口令 `root/toor`；`console.log(env)` 会打印全部环境变量到日志（`src/index.js`）。**这些是上游默认模式，但绝不能在合并项目里沿用。**
- **测试**：无。
- **许可**：GPL-3.0（见 §4）。

---

## 4. 许可证与合规分析（这是本项目的真实风险点）

| 仓库 | 许可证 | 用户自有代码 | 能否把代码并入新项目 |
|---|---|---|---|
| Horizon | MIT | 无源码改动 | ✅ 可以，保留版权与许可声明 |
| daily-briefing | MIT (© 2026 Timoté Ballochi) | telegram_sender.py 等 | ✅ 可以，保留 MIT 声明 |
| CloudFlare-AI-Insight-Daily | **GPL-3.0** | **无源码改动** | ❌ 不要复制其任何源码：GPL-3.0 的传染性会强制整个新项目 GPL-3.0 |
| dailydawn | **无 LICENSE** | build_feed/build_site/notify_push | ⚠️ 上游=保留所有权利；用户新写的独立文件可用，但 `pipeline/llm.py` 等派生文件不应复制 |
| ai-daily-sources | **无 LICENSE（用户自有）** | 全部 | ✅ 用户是版权人，可自行重新许可 |
| daybrief | **无 LICENSE（用户自有）** | 全部 | ✅ 同上 |

**行动建议**：
1. 新项目许可证取 **MIT 或 Apache-2.0**，可安全吸收 MIT 的 Horizon / daily-briefing。
2. 对 CloudFlare 与 dailydawn：**只吸收"信息源清单"这类事实性数据**（URL 列表不受版权保护），不复制其代码；或干脆按功能重新实现。
3. 建 `NOTICE` + `THIRD_PARTY_LICENSES.md`，逐条记录 Horizon(Thysrael)、daily-briefing(Timoté Ballochi)、alan-turing-institute/ai-rss-feeds 等来源。
4. **若你希望新项目将来能闭源或商用，就必须排除 GPL-3.0 代码**——这是二选一的硬约束，需要你确认。

---

## 5. 信息源总账（实测统计，非估算）

产物：`audit/sources_ledger.json`（107 条原始记录）、`sources/registry.yaml`（定型注册表）、`data/state/health.jsonl`（真实探测结果）、`docs/HEALTH_REPORT.md`（可读报告）。

### 5.1 计数口径（三层，逐层收窄，避免虚假精确）

| 层级 | 数量 | 说明 |
|---|---|---|
| 原始源配置记录 | **107** | 每个 repo×文件×配置键记一条，可逐条追溯 |
| 唯一 URL 记录 | **100** | URL 规范化去重后的不同地址 |
| **端点级唯一源** | **80** | 其中 20 条是**同一 Google Trends 端点的不同查询参数**（pytrends 的 20 个种子关键词），已合并为一个源的 `params.keywords` |
| 溯源记录（保留数） | **107** | 合并后仍为 107 —— **零丢失**，`tests/contract/test_source_coverage.py` 会持续断言这一点 |

> 口径修正说明：先前按"URL 级"报过 100 条，细化到端点级后为 **80**。这不是源变少了，而是把"一个端点的 20 个查询参数"从"20 个源"里剔除——把它们算成 20 个源会虚高完整性。20 个关键词仍完整保留在该源的 `params.keywords` 中，每条都有独立溯源。

此外两点口径必须记住：daily-briefing 的 Tavily 是**运行时动态检索**，1 条记录代表无限查询空间；CloudFlare 的 4 个 Folo list **内部真实包含多少 feed 在仓库中不可见**（需 cookie 才能枚举，属未验证项 U-2）。

### 5.2 各仓库贡献（按唯一源计）

Horizon 45 / dailydawn 19 / CloudFlare-AI-Insight-Daily 11 / daybrief 5 / ai-daily-sources 4 / daily-briefing 1

### 5.3 真实存活探测结果（2026-10-13 联网实测，控制组 HTTP 200 正常）

| 判定 | 数量 | 含义 |
|---|---|---|
| ✅ healthy | **48** | HTTP 2xx 且解析出 ≥1 条 |
| ⛔ blocked | **13** | 401/403/429：源存在但拒绝自动访问 |
| ❌ dead | **1** | DNS/TLS 失败 |
| ⏸ disabled | **10** | 注册表中保留但未接入（Horizon 预设/示例 + CloudFlare 未注册适配器） |
| 🔑 needs_credential | **7** | 需 token/cookie，未探测 |
| ❔ unverified | **1** | 由代码库驱动（Google Trends / pytrends），该 URL 不可直接抓取 |
| **合计** | **80** | |

**两条可直接落地的结论**：
1. **Reddit 的 JSON 端点 12 个全部 403 Blocked**，而同批数据里 **`old.reddit.com` 的 3 个 HTML 源全部健康** → 以独立证据验证了 Horizon 用 `old.reddit.com` HTML 而非 JSON 的设计选择。新项目的 Reddit 采集器应直接采用 HTML 方案，不要用 `reddit.com/r/*/top.json`。
2. **`git-trending.justlikemaki.vip`**（CloudFlare 仓库唯一的 GitHub Trending 数据源）TLS 握手中断，且它是**个人维护的第三方 API** → 建议改为直连 `github.com/trending` 抓取或 GitHub 官方 API。

**新鲜度**：34 个带时间戳的健康源中 **21 个在 3 天内有新内容**；5 个超过 7 天无更新（多为 Horizon 预设/示例源，本就不在启用列表内，属预期）。
> 探测过程中修正了两处**我自己的**测量误差，如实记录：① 最初把 20 个 Google Trends 关键词当成 20 个独立源探测，得到 21 个假"429 失效"；② 最初用 `entries[0]` 判定"最新"，但 `ainewslog` 是旧→新排序的 feed（其源码注释明确写过这一点），会误报"8 个月前"。两处都已修正后重测。

**跨仓库共享源（4 条）**：`daily.juya.uk/rss.xml`（3 仓库）、`simonwillison.net/atom/everything/`（3 处）、`ainewslog.com/rss.xml`（2）、`dailydawn.dev/zh.json`（2）。
> 共享率仅 4/80 说明**六个仓库的源高度互补**，"完整性继承"的收益主要来自合并而非去重。

**未验证/高风险源（保留配置但必须标记）**：`wechat2rss.xlab.app` 与 `decemberpei.cyou/rssbox/*` 是第三方微信公众号转 RSS 服务，本次探测**健康**但属非官方服务，随时可能失效；`api.follow.is`（需账号 cookie，非公开 API）；`api.tavily.com`（付费检索）。

---

## 6. 跨仓库冲突与重复分析

| 冲突类型 | 具体表现 | 处理建议 |
|---|---|---|
| **功能重叠** | 5 个仓库都在做"抓取→LLM 摘要→分发" | 只保留 Horizon 的编排，其余降级为"适配器/源清单" |
| **AI 层互不兼容** | Horizon: 多厂商抽象客户端；dailydawn: OpenAI 兼容 + 降级链；daybrief: 硬编码双 Provider；daily-briefing: Groq SDK；CloudFlare: GEMINI/OPEN 二选一 | 统一到 Horizon 的 client + dailydawn 的 `LLM_FALLBACK_MODELS` 思路 |
| **去重语义冲突** | dailydawn 是"URL 去重 + 分数叠加"；ai-daily-sources 是"URL+标题前 60 字"；Horizon 是"跨源合并正文" | 三层去重必须重新设计（见后续阶段），不能直接复用任一个 |
| **输出格式冲突** | dailydawn: md+RSS+json+og图；daybrief: md+html+json+site/rss.xml；ai-daily-sources: sources.json；daily-briefing: history.json+preview.html；Horizon: AI 摘要+邮件 | 定义统一 `DailyDigest` schema，各输出器从它渲染 |
| **依赖冲突** | Horizon(py≥3.11, uv+hatchling) / dailydawn(httpx+praw+pytrends+Pillow) / daily-briefing(groq+tavily+APScheduler) / daybrief(仅 pyyaml，stdlib) / CloudFlare(JS, Workers runtime) | 分组成 `core`/`scrape-*`/`notify-*` extras，避免全装 |
| **运行时冲突** | CloudFlare 是 V8 Worker（无文件系统、无 Python）；其余是 Python | Worker 只保留为**可选分发端**，不进主流水线 |
| **状态存储冲突** | ai-daily-sources: `archive/*.json`；daily-briefing: `data/history.json`；dailydawn: `meta/recent-taglines.jsonl`；Horizon: `src/storage/manager.py`(文件) | 统一 state 层，见架构阶段 |

---

## 7. 无法验证的内容（诚实披露，不编造）

- **U-1**：CloudFlare Worker **生产环境**的真实 `[vars]`（Folo list 内容、cookie、模型）。仓库内 `wrangler.toml` == 上游默认值，无法据此判断线上实际配置。
- **U-2**：Folo 4 个 list 内部到底包含哪些 feed —— 需要 FOLO_COOKIE 调用 API 才能枚举；仓库中不可见。
- **U-3**：六个仓库的 GitHub Actions **历史运行结果**（成功率、耗时、实际触发延迟）未审计。可用的只有 workflow 定义本身。
- **U-4**：所有信息源**当前是否可访问**未做联网验证（本次只做静态审计）。因此"失效源"数量目前未知。
- **U-5**：各仓库**测试是否真的通过**未运行（本机有 Python 3.11，但 Horizon 用 uv、CloudFlare 是 JS，未搭建运行环境）。仅确认存在测试文件与 CI 定义。
- **U-6**：dailydawn 上游 `TangSY/dailydawn` 与用户 fork 的默认分支是否已分叉很远 —— 比对基于 `--depth 1` 的 main 分支快照。
- **U-7**：`freellmapi-keys.json` 中约 130 个第三方中转站的**可用性与合法性**未验证；其中多个为来源不明的"免费 API 中转"，存在数据外泄与违反上游 ToS 的风险。

---

## 8. 安全审计发现（需要立即处理）

1. **凭据已在对话中明文暴露**：Cloudflare API Token、R2 Access Key/Secret、QQ 邮箱授权码，以及 `freellmapi-keys.json` 中约 130 个 API Key。建议**轮换**已暴露的 Cloudflare Token、R2 密钥、QQ 授权码。它们也会被写入本次会话记录。
2. **绝不能沿用上游的密钥提交模式**：`wrangler.toml` 明文 API Key + `LOGIN_PASSWORD="toor"` + `console.log(env)` 全量打印环境变量。
3. **公开仓库中的 PII**：`Horizon/data/config.github.json` 提交了 `2166***@qq.com` 与 Telegram `chat_id`。新项目必须把这些移入 Secrets/Variables。
4. **私密内容经不可信中转传输**：若把日报内容发给来源不明的免费中转站，等同于把内容公开给第三方。建议分级：**可信层**（官方 API：Google/Groq/Cerebras/SambaNova/OpenRouter 等）用于正式日报；**实验层**仅用于无敏感信息的测试。
5. **Cookie 型源（Folo）**：`FOLO_COOKIE` 是账号级凭证，泄露即账号失守；shallow 检查未发现它被提交，但必须明确其存放策略。

---

## 9. 阶段一验收结论

- [x] 六仓库全部访问并完成静态审计（含 Horizon）
- [x] 六个仓库的功能清单、信息源清单、可复用模块清单
- [x] 跨仓库信息源总账（107 原始 / 100 唯一 / 4 共享 / 11 未启用 / 13 需凭证）
- [x] 技术冲突、依赖冲突、功能重叠、许可证风险
- [ ] 信息源**存活验证**（需联网批量探测，建议阶段二做）
- [ ] 四套架构方案与取舍（待需求澄清后进行，避免方案建立在错误假设上）
