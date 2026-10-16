# AI 日报 · ai-ribao

每天全自动生成的中文 AI 日报：**采集 → 去重 → 聚类 → 栏目分类 → 大模型分析 → 事实核查 → 多通道分发**，全程跑在 GitHub Actions 上，零服务器、零常驻进程。

在线阅读：**https://siweimidu.github.io/ai-ribao/**

---

## 它是怎么工作的

整条流水线分七步，每一步的产物都落盘，可独立复查：

### 1. 采集（每天 07:00 与 19:00，北京时间）

`python -m aidaily collect` 并发抓取 `sources/registry.yaml` 里的全部信息源 —— RSS、JSON API、网页正文抓取、GitHub Trending，共 117 个源（100 启用；停用的每一个都写明实测原因，**失效的源也保留并标记，不静默删除**）。每个源声明自己的适配器、类别、语言与凭据需求；抓取结果带判定（ok / blocked / not_modified / dead）写入审计日志。

**汇总类信息源会被拆成单条新闻。** 橘鸦（`daily.juya.uk`）每天只发一条 RSS，标题是日期、正文是整页 HTML，装下当天全部新闻（`<h3>标题 ↗ #1</h3>` + 分栏列表）。按 HTML 语义单元逐条拆分后，一期 43 KB 的正文变成 30+ 条独立条目，每条带**橘鸦自己发布的真实外链** —— 否则整期只会被当成一条「日期」新闻，里面的 DeepSeek 宕机、OpenCode 限免这类消息根本不会出现。

每天两个时段各采集一次，**信息去重后合并进当天同一份日报**：早上拿到夜里发生的事，晚上补全白天发生的事。

两个时段是**两次独立发布**，不是一次发布加一次重试：幂等闸门按「日期 + 时段」判断，早间发布过后晚间照常重建（同时段的重试才跳过）。所以一天里晚报会把早报的内容连同新增部分一起重新去重、重新排序。

### 2. 窗口与去重（L2）

只保留采集窗口内的条目（默认 26 小时，覆盖两次采集之间的间隔）；同源重复按标题指纹与 URL 规范化合并；跨天的重复内容按 7 天窗口降权 12%（重复是"还在被讨论"，不是"不存在"）。

跨天匹配用双指纹（标题折叠 + URL 规范化）并保留全部历史日期；**时区一律用配置里的 `Asia/Shanghai`** —— runner 是 UTC，用本机时区算「今天」会把凌晨的运行归到前一天，跨天去重会整段失效。

### 3. 聚类（L3）

把"多家媒体报同一件事"的多条目合并成一个**事件**，并记录独立来源数 —— 它是后面热度计算里权重最高的信号。同一发布者的多个镜像源（例如同一家的日报/周报/月报）预先声明为同一 `dedup_group`，否则"独立来源数"会被流水线自己制造出来。

### 4. 排序：栏目优先，分数其次

这是本项目和"按热度堆一条长列表"的做法最不一样的地方。排序第一主键是**栏目**，第二主键才是分数：

```
要闻 > 开发生态 > 模型发布 > 产品应用 > 技术与洞察 > 行业动态 > 其他
```

栏目由大模型在打分的同时判定（判据写在 `config/profiles/ai-daily/section.md`，改它就能改分类，不用改代码）。分数是四个因子的乘积：

| 因子 | 含义 |
|---|---|
| 热度 | 独立来源数 0.28、量级 0.25、互动 0.13、触达 0.11、增速 0.09、实质 0.07、新鲜 0.07 |
| AI 相关度 | 这条新闻**是关于** AI，还是只**提到** AI（详见下方门槛） |
| 厂商优先级 | DeepSeek 1.45 > Kimi 1.32 > GLM 1.24 > MiniMax/Qwen/豆包/阶跃/元宝 1.15（仅当厂商是**主体**，"用 DeepSeek 做的机器人研究"不加权） |
| 来源与标题 | 来源权重开 0.25 次方（减弱信源出身的影响）；纯日期容器标题降权 |

**相关度是一道硬门槛，不是可以互相抵消的权重。** 相关度低于 **0.70** 的条目在排序前就被剔除，不会进入日报；缺相关度评分同样判不通过（新事件类型不会静默绕过）。实测候选池 153 条里只有 39 条达标 —— 裸「AI」一词得 0.50，含具体术语（LLM、训练、大模型、开源）得 1.0。**宁可当天只有 20 条，也不拿消费电子把版面填满。**

排序在这个基础上是**栏目优先、分数其次**。

### 5. 大模型分析：四栏认知分栏

通过筛选的每条新闻由大模型写成**事实 / 推断 / 观点 / 不确定**四栏 —— 让读者一眼分清"哪些是事实、哪些是推测、哪些话现在还不能信"。

防幻觉是结构性的：**模型只返回条目 id 和分析文本，永远不返回链接**；所有 URL 由程序从自己的采集记录回填，模型编不出它没见过的链接。`不确定` 栏是必填的 —— 空栏和"没有不确定"在页面上长得一样，而后者几乎不成立。

### 6. 事实核查

日报里每一个 URL 都必须能在本项目的采集记录里找到，找不到就拒绝发布（退出码非 0）。模型没有说过"据某处报道"却不给出来处的自由。

### 7. 分发

同一次运行产出五种通道：GitHub Pages、RSS + JSON Feed、QQ 邮件、Telegram、n8n webhook。渠道各自幂等，部分失败可单独补发。

### 8. 阅读端

- **移动端优先**：窄屏单独给内边距（390px 下 16px），正文不与屏幕贴边；网格轨道统一用 `minmax(0, 1fr)`，长标题不会撑破布局。
- **主题**：亮色 / 暗色 / Claude 亮色 / Claude 暗色。首次访问是亮色，选过之后存入 localStorage，**每个页面都读同一个偏好** —— 包括 Tibo 页（它没有主题按钮，但偏好照样生效：读取和应用不依赖本页有没有控件）。
- **动效**：欠阻尼弹簧（刚度 80、阻尼 0.86）做悬停回弹，帧率无关写法（真实 `dt`，上限 1/30），`prefers-reduced-motion` 下全部关闭。
- **日历**：侧栏月历与 Tibo 重置日历共用一套几何 —— 有内容的日期是数字下方一个点，今天全月唯一的实心圆，正在阅读的那一期是描边圆环。格子固定 30px，不会互相覆盖。侧栏可拖宽窄，拖窄时日历在栏内横向滚动而不是压扁。

---

## 它和别的 AI 日报有什么不同

- **排序可解释**：页面上每一条的位置都能拆成栏目、热度、相关度、厂商优先级几个数字，写在归档的 `rank_components` 里
- **筛选标准是数据文件**：评分标准、栏目判据、相关度词表全是 markdown/yaml，改完提交即生效
- **相关度是硬门槛**：低于 0.70 的条目直接不发布，不会靠"今天新闻少"把消费电子抬上来
- **汇总源拆成单条**：别人日报的一期汇总在这里会变成 30+ 条独立新闻，各带原始外链
- **密钥轮换**：支持任意多个 OpenAI 兼容端点，按 baseUrl 识别 22 家厂商并自动选默认模型；一个 key 额度耗尽自动切下一个，429 自动退避重试
- **降权不删除**（针对确实相关的重复内容）：跨天重复、同话题重复都被降权而不是丢弃
- **一切可审计**：每次运行的采集判定、去重合并数、模型调用数与供应商、栏目分布、被门槛剔除的条目都写进归档

## 快速开始

### 1. Fork 并开启 Actions

Fork 本仓库后，在 **Settings → Actions → General → Workflow permissions** 选 **Read and write**（工作流需要提交生成的日报）。

### 2. 提供一个大模型 API（必需）

任意 **OpenAI 兼容**端点都可以，官方或中转均可。在本地准备一个 JSON 文件（**不要提交进仓库**）：

```json
[
  {"baseUrl": "https://api.deepseek.com/v1", "key": "sk-xxx", "label": "DeepSeek 官方"},
  {"baseUrl": "https://open.bigmodel.cn/api/paas/v4", "key": "xxx", "label": "智谱"},
  {"baseUrl": "https://api.moonshot.cn/v1", "key": "sk-xxx", "label": "Kimi", "model": "kimi-k2-0905-preview"}
]
```

- `model` 可省略：程序会按 baseUrl 识别厂商（DeepSeek / 智谱 / Kimi / MiniMax / 通义 / 豆包 / 阶跃 / Groq / OpenRouter 等 22 家）并自动选默认模型
- 识别不出的自定义中转站会自动探测其 `/models` 列表
- 同一 baseUrl 放多把 key 即自动轮换

然后写入仓库 secret（文件重定向可避开命令行长度限制）：

```bash
gh secret set RELAY_KEYS_JSON --repo <你的用户名>/ai-ribao < keys.json
```

**免费额度够用吗？** 单次运行约 120–140 次调用。把多家厂商的免费 key 放进同一个文件即可轮换；只用一把也能跑，只是额度用尽后当天会降级为纯公式排序（不会失败）。

### 3. 可选通道

| Secret | 用途 | 不配置时 |
|---|---|---|
| `TAVILY_API_KEY` | Tavily 搜索源补充覆盖 | 该源跳过，其余正常 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `MAIL_TO` | QQ 邮件推送 | 邮件通道 skipped |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Telegram 推送 | TG 通道 skipped |
| `N8N_WEBHOOK_URL` | n8n 工作流对接 | webhook skipped |

所有通道缺失都只是 skipped，不会让运行失败。

### 4. 让它跑起来

工作流每天自动运行两次：**07:00 与 19:00**（北京时间，另各有两次重试应对 GitHub 整点拥堵）。也可以手动触发：**Actions → daily → Run workflow**，两个开关：

- `force` —— 忽略当天该时段已发布的记录，强制重建
- `skip_collect` —— 复用最近一次采集的条目，只重跑分析（调试排版用）

### 5. 本地运行

```bash
pip install -e ".[fetchers,llm]"
python -m aidaily run --no-deliver      # 完整流水线，只产文件不分发
python -m aidaily gate                  # 查看今天这个时段还需不需要发布
python -m aidaily collect --only rss:daily-juya-uk   # 只采集一个源
```

`run` 会拒绝在当天第一次采集时间（默认 07:00 北京时间）之前生成**当天**的日报 —— 凌晨跑出来的不是早报，是一份只有几小时新闻的文档，却会占据那一天的日期。要强制生成加 `--allow-early`（测试就是这么做的）。

## 排错

| 现象 | 先查什么 |
|---|---|
| 日报里出现与 AI 无关的内容 | `data/digests/<日期>.json` 的 `rank_components.focus` 是否 < 0.70；若是，说明门槛被绕过，检查 `src/aidaily/pipeline.py` 的过滤是否为最新版本 |
| 某条重要新闻没有出现 | 该源是否在采集产物里（`python -m aidaily collect --only <source_id> --show-failures`）；若是汇总源，看正文是否被拆成单条 |
| 首页条数与正文不符 | 归档的 `counts.events` 应等于 `len(top_events)`；不等说明归档是旧版本写的 |
| 主题在某个页面不生效 | 该页是否加载了 `assets/motion.js`；读取偏好与应用偏好不依赖本页有没有主题按钮 |
| 推送失败 | HTTPS 在本网络会被 TLS 干扰，用 SSH（`git@github.com:...`） |
| 模型全部失败、返回英文标题 | 检查 secret 里的密钥是否被截断；`RELAY_KEYS_JSON` 必须能 `json.loads` |

一键核对站点与产物：

```bash
bash scripts/site_guards.sh          # 相对路径、资源一致性、TS 语法残留
python scripts/test_calendars.py     # 两个日历的日期列与点击
python scripts/test_rails.py         # 侧栏拖宽、键盘、滚动
python scripts/verify_sources.py     # 逐个核验信息源可达性
```

## 定制

| 想改什么 | 改哪里 |
|---|---|
| 排序标准（分数档位、降分类型） | `config/profiles/ai-daily/analysis.md` |
| 栏目判据 | `config/profiles/ai-daily/section.md` |
| 收录范围（什么算 AI 新闻） | `config/profiles/ai-daily/match.md` |
| 写作风格与四栏要求 | `config/profiles/ai-daily/enrichment.md` |
| 相关度词表（哪些词算 AI 核心） | `src/aidaily/focus.py` |
| 相关度门槛高低 | `src/aidaily/pipeline.py` 的 `MIN_AI_RELEVANCE` |
| 厂商优先级 | `src/aidaily/vendor_priority.py` |
| 每天几个时段、几点采集 | `config/daily.yaml` 的 `run.slots` **和** `.github/workflows/daily.yml` 的 cron（两处都要改） |
| 信息源增删 | `sources/` 下的 yaml，跑 `python scripts/verify_sources.py` 核验 |

改完全部是提交即生效，下一次运行就按新标准执行。

## 数据与凭据安全

- 所有密钥只经 GitHub Secrets 与环境变量注入，**仓库内不含任何凭据**（CI 里有守卫检查）
- 日报正文、归档、审计日志全部提交进仓库 —— 它们是内容，不是秘密
- 模型永远不输出链接：URL 只能来自本项目自己的采集记录

## 许可

MIT
