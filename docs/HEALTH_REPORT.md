# 信息源健康报告（真实探测结果）

探测时间：2026-10-17T14:14:00.631976+00:00　耗时 13.0s　并发 10
控制组 `https://example.com`：**正常**

> 本报告由 `scripts/probe_sources.py` 真实联网探测生成。每条判定都带 HTTP 状态、解析到的条目数或真实异常，无一条是估算。

## 总览

| 判定 | 数量 | 含义 |
|---|---|---|
| healthy | 76 | HTTP 2xx 且解析出 ≥1 条 |
| degraded | 3 | HTTP 2xx 但解析 0 条 / 响应异常 |
| blocked | 15 | 401/403/429：源存在但拒绝自动访问 |
| dead | 2 | DNS/TLS 失败、4xx/5xx 或无法解析 |
| needs_credential | 7 | 需 token/cookie，未探测 |
| disabled | 20 | 存在于注册表但未启用（示例/未注册适配器） |
| unverified | 1 | 有意未探测 |
| **合计** | **124** | |

## ⛔ 被拒绝自动访问（源存在，需换抓取方式或补凭证）

| 源 | 域名 | 类型 | HTTP | 详情 |
|---|---|---|---|---|
| r/artificial | old.reddit.com | scrape | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| r/LocalLLaMA | old.reddit.com | scrape | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| r/MachineLearning | old.reddit.com | scrape | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| reddit r/devops | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| reddit r/indiehackers | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| reddit r/LocalLLaMA | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| reddit r/MachineLearning | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| reddit r/opensource | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| reddit r/programming | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| reddit r/rust | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| reddit r/SaaS | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| reddit r/selfhosted | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| reddit r/SideProject | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| reddit r/startups | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |
| reddit r/webdev | reddit.com | api | 403 | HTTP 403 Blocked — 源存在但拒绝自动访问：需要凭证或改用别的入口（Reddit 的 HTML 入口同样已被登录墙拦截） |

## ❌ 失效（配置保留，需要修复）

| 源 | 域名 | 类型 | HTTP | 详情 |
|---|---|---|---|---|
| ai.hubtoday | ai.hubtoday.app | rss | - | URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unabl |
| git-trending.justlikemaki.vip (GitHub Trendi | git-trending.justlikemaki.vip | api | - | URLError: <urlopen error [Errno -2] Name or service not known> |

## ⚠️ 降级

| 源 | 域名 | 类型 | HTTP | 详情 |
|---|---|---|---|---|
| ai-ribao Releases | github.com | atom | 200 | parsed OK but 0 entries (bozo=False)  |
| Horizon Releases | github.com | atom | 200 | parsed OK but 0 entries (bozo=False)  |
| podrss AI 播报 | podrss.1874.run | rss | 200 | parsed OK but 0 entries (bozo=False)  |

## ✅ 健康源

| 源 | 域名 | 类型 | 条目数 | 最新发布时间 |
|---|---|---|---|---|
| AIHOT 行业分类 | aihot.news | rss | 26 | 2026-10-16T08:23:54Z |
| AIHOT 模型分类 | aihot.news | rss | 27 | 2026-10-16T22:22:42Z |
| AIHOT 观点分类 | aihot.news | rss | 5 | 2026-10-16T14:00:39Z |
| AIHOT 论文分类 | aihot.news | rss | 13 | 2026-10-16T00:00:00Z |
| AIHOT 产品分类 | aihot.news | rss | 36 | 2026-10-17T10:29:00Z |
| AIHOT 教程分类 | aihot.news | rss | 19 | 2026-10-17T10:19:04Z |
| AIHOT 全站 | aihot.news | rss | 50 | 2026-10-17T13:26:55Z |
| AIHOT 日报 | aihot.news | rss | 30 | 2026-10-17T00:00:28Z |
| AIHOT 全文 | aihot.news | rss | 50 | 2026-10-17T10:29:00Z |
| AIHOT 月报 | aihot.news | rss | 5 | 2026-10-01T11:48:32Z |
| AIHOT 编辑精选 | aihot.news | rss | 50 | 2026-10-17T10:29:00Z |
| AIHOT 周报 | aihot.news | rss | 12 | 2026-10-12T02:00:33Z |
| AI Daily (ainewslog) | ainewslog.com | rss | 484 | 2026-10-16T00:00:00Z |
| BAIR Blog | bair.berkeley.edu | rss | 10 | 2026-07-29T09:00:00Z |
| 宝玉的分享 | baoyu.io | rss | 50 | 2026-09-19T00:00:00Z |
| daily.ai225 | daily.ai225.com | rss | 30 | 2026-10-17T00:52:39Z |
| AI日报 juya | daily.juya.uk | rss | 10 | 2026-10-17T01:50:30Z |
| DailyDawn 中文 | dailydawn.dev | jsonfeed | 30 | 2026-10-17T00:00:00+00:00 |
| DailyDawn RSS | dailydawn.dev | rss | 30 | 2026-10-17T00:00:00Z |
| AI前线 | decemberpei.cyou | rss | 4 | - |
| 量子位 | decemberpei.cyou | rss | 8 | - |
| PaperWeekly | decemberpei.cyou | rss | 2 | - |
| AI前线 | decemberpei.cyou | rss | 4 | - |
| 机器之心 | decemberpei.cyou | rss | 7 | - |
| 计算机视觉life | decemberpei.cyou | rss | 1 | - |
| 集智俱乐部 | decemberpei.cyou | rss | 3 | - |
| 量子位 | decemberpei.cyou | rss | 8 | - |
| PaperWeekly | decemberpei.cyou | rss | 2 | - |
| DeepTech深科技 | decemberpei.cyou | rss | 3 | - |
| 新智元 | decemberpei.cyou | rss | 9 | - |
| 夕小瑶科技说 | decemberpei.cyou | rss | 1 | - |
| Google DeepMind | deepmind.google | rss | 100 | 2026-10-15T16:08:03Z |
| ai-ribao Commits | github.com | atom | 20 | 2026-10-17T06:54:19Z |
| Horizon Commits | github.com | atom | 20 | 2026-10-13T11:34:50Z |
| GitHub Trending | github.com | scrape | 0 | - |
| Hacker News Top Stories (Firebase API) | hacker-news.firebaseio.com | api | 500 | - |
| hex2077 AI 日刊 | hex2077.dev | rss | 36 | 2026-10-11T04:50:59Z |
| 何夕2077 AI 深度信号 | hex2077.dev | rss | 36 | 2026-10-11T04:50:59Z |
| HackerNews (Algolia) | hn.algolia.com | api | 20 | - |
| Hacker News Front Page | hnrss.org | rss | 20 | 2026-10-17T08:37:46Z |
| HuggingFace Datasets | huggingface.co | api | 10 | - |
| HuggingFace Models | huggingface.co | api | 20 | - |
| Hugging Face Blog | huggingface.co | rss | 880 | 2026-10-16T01:44:47Z |
| CloudFlare AI 资讯日报 | justlovemaki.github.io | rss | 7 | 2026-10-17T04:20:13Z |
| 范叶亮的博客 | leovan.me | rss | 67 | 2026-06-20T00:00:00Z |
| AIBase 快讯 | mcpapi.aibase.cn | api | 1 | - |
| AIBase 日报 | mcpapi.aibase.cn | api | 1 | - |
| Google News 查询: AI OR LLM OR 大模型 when:1d | news.google.com | api | 100 | 2026-10-17T13:56:40Z |
| MIT News AI | news.mit.edu | rss | 50 | 2026-10-16T16:00:00Z |
| OpenAI News | openai.com | rss | 1299 | 2026-10-16T19:00:00Z |
| AI RSS Feeds News | raw.githubusercontent.com | rss | 11 | 2026-10-15T00:00:00Z |
| Ai2 News | raw.githubusercontent.com | rss | 9 | 2026-10-31T00:00:00Z |
| Anthropic News | raw.githubusercontent.com | rss | 280 | 2026-10-15T17:20:00Z |
| Anthropic Research | raw.githubusercontent.com | rss | 182 | 2026-10-16T17:29:00Z |
| Claude News | raw.githubusercontent.com | rss | 11 | 2026-10-16T00:00:00Z |
| Cohere Blog | raw.githubusercontent.com | rss | 15 | 2026-10-15T00:00:00Z |
| Mistral News | raw.githubusercontent.com | rss | 90 | 2026-10-15T00:00:00Z |
| TLDR AI | raw.githubusercontent.com | rss | 20 | 2026-10-16T00:00:00Z |
| HF Daily Papers | raw.githubusercontent.com | rss | 84 | 2026-10-15T07:47:04Z |
| The Rundown AI | rss.beehiiv.com | rss | 20 | 2026-10-16T09:00:00Z |
| 宝玉的分享（短） | s.baoyu.io | rss | 50 | 2026-09-19T00:00:00Z |
| Simon Willison | simonwillison.net | rss | 30 | 2026-10-16T22:06:37Z |
| Telegram @zaihuapd | t.me | scrape | 0 | - |
| The Verge AI | theverge.com | rss | 10 | 2026-10-17T13:00:00Z |
| unclejoeyao AI 早报 | unclejoeyao666.github.io | rss | 50 | 2026-10-09T00:00:00Z |
| V2EX 热门主题 | v2ex.com | api | 9 | - |
| Yi's blog | wangyi.ai | rss | 20 | 2026-02-16T20:00:00Z |
| DeepSeek 官方 | wechat2rss.bestblogs.dev | rss | 10 | 2026-10-17T08:11:00Z |
| 腾讯混元官方 | wechat2rss.bestblogs.dev | rss | 10 | 2026-10-16T09:15:00Z |
| 机器之心 | wechat2rss.bestblogs.dev | rss | 10 | 2026-10-17T04:41:00Z |
| 智谱官方 | wechat2rss.bestblogs.dev | rss | 10 | 2026-09-18T04:37:00Z |
| 我爱计算机视觉 | wechat2rss.xlab.app | rss | 16 | 2026-10-16T15:38:00Z |
| 机器之心 | wechat2rss.xlab.app | rss | 20 | 2026-10-17T04:41:00Z |
| 新智元 | wechat2rss.xlab.app | rss | 20 | 2026-10-17T04:22:00Z |
| 机器之心 | wechat2rss.xlab.app | rss | 20 | 2026-10-17T04:41:00Z |
| 新智元 | wechat2rss.xlab.app | rss | 20 | 2026-10-17T04:22:00Z |

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
