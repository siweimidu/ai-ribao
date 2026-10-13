# 信息源健康报告（真实探测结果）

探测时间：2026-10-14T00:04:38.674035+08:00　耗时 21.6s　并发 10
控制组 `https://example.com`：**正常**

> 本报告由 `scripts/probe_sources.py` 真实联网探测生成。每条判定都带 HTTP 状态、解析到的条目数或真实异常，无一条是估算。

## 总览

| 判定 | 数量 | 含义 |
|---|---|---|
| healthy | 39 | HTTP 2xx 且解析出 ≥1 条 |
| degraded | 0 | HTTP 2xx 但解析 0 条 / 响应异常 |
| blocked | 12 | 401/403/429：源存在但拒绝自动访问 |
| dead | 1 | DNS/TLS 失败、4xx/5xx 或无法解析 |
| needs_credential | 7 | 需 token/cookie，未探测 |
| disabled | 20 | 存在于注册表但未启用（示例/未注册适配器） |
| unverified | 1 | 有意未探测 |
| **合计** | **80** | |

## ⛔ 被拒绝自动访问（源存在，需换抓取方式或补凭证）

| 源 | 域名 | 类型 | HTTP | 详情 |
|---|---|---|---|---|
| reddit r/devops | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问，需更换抓取方式（如 old.reddit.com HTML）或补凭证 |
| reddit r/indiehackers | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问，需更换抓取方式（如 old.reddit.com HTML）或补凭证 |
| reddit r/LocalLLaMA | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问，需更换抓取方式（如 old.reddit.com HTML）或补凭证 |
| reddit r/MachineLearning | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问，需更换抓取方式（如 old.reddit.com HTML）或补凭证 |
| reddit r/opensource | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问，需更换抓取方式（如 old.reddit.com HTML）或补凭证 |
| reddit r/programming | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问，需更换抓取方式（如 old.reddit.com HTML）或补凭证 |
| reddit r/rust | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问，需更换抓取方式（如 old.reddit.com HTML）或补凭证 |
| reddit r/SaaS | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问，需更换抓取方式（如 old.reddit.com HTML）或补凭证 |
| reddit r/selfhosted | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问，需更换抓取方式（如 old.reddit.com HTML）或补凭证 |
| reddit r/SideProject | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问，需更换抓取方式（如 old.reddit.com HTML）或补凭证 |
| reddit r/startups | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问，需更换抓取方式（如 old.reddit.com HTML）或补凭证 |
| reddit r/webdev | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问，需更换抓取方式（如 old.reddit.com HTML）或补凭证 |

## ❌ 失效（配置保留，需要修复）

| 源 | 域名 | 类型 | HTTP | 详情 |
|---|---|---|---|---|
| git-trending.justlikemaki.vip (GitHub Trendi | git-trending.justlikemaki.vip | api | - | URLError: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of  |

## ✅ 健康源

| 源 | 域名 | 类型 | 条目数 | 最新发布时间 |
|---|---|---|---|---|
| AIHOT 全站 | aihot.news | rss | 50 | 2026-10-13T15:58:09Z |
| AI Daily (ainewslog) | ainewslog.com | rss | 476 | 2026-10-12T00:00:00Z |
| BAIR Blog | bair.berkeley.edu | rss | 10 | 2026-07-29T09:00:00Z |
| AI日报 juya | daily.juya.uk | rss | 10 | 2026-10-13T01:48:17Z |
| DailyDawn 中文 | dailydawn.dev | jsonfeed | 30 | 2026-10-13T00:00:00+00:00 |
| AI前线 | decemberpei.cyou | rss | 2 | - |
| 量子位 | decemberpei.cyou | rss | 8 | - |
| PaperWeekly | decemberpei.cyou | rss | 3 | - |
| Google DeepMind | deepmind.google | rss | 100 | 2026-10-13T16:01:58Z |
| GitHub Trending | github.com | scrape | 0 | - |
| Hacker News Top Stories (Firebase API) | hacker-news.firebaseio.com | api | 500 | - |
| 何夕2077 AI 深度信号 | hex2077.dev | rss | 36 | 2026-10-11T04:50:59Z |
| HackerNews (Algolia) | hn.algolia.com | api | 20 | - |
| Hacker News Front Page | hnrss.org | rss | 20 | 2026-10-13T15:41:00Z |
| HuggingFace Datasets | huggingface.co | api | 10 | - |
| HuggingFace Models | huggingface.co | api | 20 | - |
| Hugging Face Blog | huggingface.co | rss | 876 | 2026-10-09T15:20:29Z |
| Google News 查询: AI OR LLM OR 大模型 when:1d | news.google.com | api | 100 | 2026-10-13T15:27:16Z |
| MIT News AI | news.mit.edu | rss | 50 | 2026-10-13T04:00:00Z |
| r/artificial | old.reddit.com | scrape | 0 | - |
| r/LocalLLaMA | old.reddit.com | scrape | 0 | - |
| r/MachineLearning | old.reddit.com | scrape | 0 | - |
| OpenAI News | openai.com | rss | 1287 | 2026-10-09T07:00:00Z |
| AI RSS Feeds News | raw.githubusercontent.com | rss | 10 | 2026-10-08T12:00:00Z |
| Ai2 News | raw.githubusercontent.com | rss | 9 | 2026-10-31T00:00:00Z |
| Anthropic News | raw.githubusercontent.com | rss | 277 | 2026-10-08T17:00:00Z |
| Anthropic Research | raw.githubusercontent.com | rss | 177 | 2026-10-12T19:30:00Z |
| Claude News | raw.githubusercontent.com | rss | 11 | 2026-10-08T00:00:00Z |
| Cohere Blog | raw.githubusercontent.com | rss | 15 | 2026-10-05T00:00:00Z |
| Mistral News | raw.githubusercontent.com | rss | 89 | 2026-10-06T00:00:00Z |
| TLDR AI | raw.githubusercontent.com | rss | 20 | 2026-10-13T00:00:00Z |
| HF Daily Papers | raw.githubusercontent.com | rss | 10 | 2026-10-09T00:00:00Z |
| The Rundown AI | rss.beehiiv.com | rss | 20 | 2026-10-13T09:00:00Z |
| Simon Willison | simonwillison.net | rss | 30 | 2026-10-13T13:32:00Z |
| Telegram @zaihuapd | t.me | scrape | 0 | - |
| The Verge AI | theverge.com | rss | 10 | 2026-10-13T16:00:00Z |
| V2EX 热门主题 | v2ex.com | api | 7 | - |
| 机器之心 | wechat2rss.xlab.app | rss | 20 | 2026-10-13T04:00:00Z |
| 新智元 | wechat2rss.xlab.app | rss | 20 | 2026-10-12T00:41:00Z |

## 🔑 需要凭证（未探测）

| 源 | 域名 | 所需凭证 |
|---|---|---|
| Folo 列表: Twitter (153028784690326528) | api.follow.is | requires FOLO_COOKIE |
| Folo 列表: 新闻聚合 (158437828119024640) | api.follow.is | requires FOLO_COOKIE |
| Folo 列表: Reddit (167576006499975168) | api.follow.is | requires FOLO_COOKIE |
| Folo 列表: HuggingFace Papers (158437917409783 | api.follow.is | requires FOLO_COOKIE |
| Product Hunt GraphQL | api.producthunt.com | requires PRODUCT_HUNT_TOKEN |
| Tavily 检索（运行时动态查询，无静态源表） | api.tavily.com | requires TAVILY_API_KEY |
| LWN full text | lwn.net | requires REQUIRED_ENV_VAR |

## ⏸ 已禁用 / 未接入（按策略保留，不删除）

| 源 | 域名 | 说明 |
|---|---|---|
| AIBase (通过 Folo 列表) | aibase.com | present in registry but not wired up |
| Quanta Magazine | api.quantamagazine.org | present in registry but not wired up |
| Brendan Gregg | brendangregg.com | present in registry but not wired up |
| CSS-Tricks | css-tricks.com | present in registry but not wired up |
| NVIDIA Developer CUDA blog | developer.nvidia.com | present in registry but not wired up |
| Hackaday | hackaday.com | present in registry but not wired up |
| HuggingFace Papers (通过 Folo 列表) | huggingface.co | present in registry but not wired up |
| 机器之心 (通过 Folo 列表) | jiqizhixin.ai | present in registry but not wired up |
| Krebs on Security | krebsonsecurity.com | present in registry but not wired up |
| LWN.net headlines | lwn.net | present in registry but not wired up |
| GitHub Trending RSS (mshibanami) | mshibanami.github.io | present in registry but not wired up |
| Nature | nature.com | present in registry but not wired up |
| QbitAI 量子位 (通过 Folo 列表) | qbit.ai | present in registry but not wired up |
| Schneier on Security | schneier.com | present in registry but not wired up |
| Sean Goedecke | seangoedecke.com | present in registry but not wired up |
| CNBC combined search | search.cnbc.com | present in registry but not wired up |
| vLLM Blog | vllm.ai | present in registry but not wired up |
| 机器之心(wechat2rss 7131b577) | wechat2rss.xlab.app | present in registry but not wired up |
| 小胡 AI (通过 Folo 列表) | xiaohu.ai | present in registry but not wired up |
| 新智元 (通过 Folo 列表) | xinzhiyuan.ai | present in registry but not wired up |

## ❔ 未探测

| 源 | 域名 | 说明 |
|---|---|---|
| Google Trends (pytrends, 20 个种子关键词) | trends.google.com | 由代码库驱动（非该 URL 直接抓取） |
