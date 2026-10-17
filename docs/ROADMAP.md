# 分阶段实施计划 · 测试验收规范 · 风险清单

日期：2026-10-13
前置文档：`audit/AUDIT_REPORT.md`、`audit/DECISIONS.md`、`docs/ARCHITECTURE.md`、`docs/WORKFLOWS.md`

---

## 一、分阶段实施计划（含验收条件）

### 阶段 1 · 仓库审计 ✅ 已完成
**验收**：六仓库全部克隆并逐文件审计；每个结论有文件级证据；无法验证项显式列出。
**产物**：`audit/AUDIT_REPORT.md`、`audit/sources_ledger.json`

### 阶段 2 · 信息源总账 ✅ 已完成
**产出**：`sources/registry.yaml`（80 个端点级唯一源 + 107 条溯源）、`scripts/build_registry.py`、`scripts/probe_sources.py`、`data/state/health.jsonl`、`docs/HEALTH_REPORT.md`

**验收结果（全部为实测数字）**：
- [x] 每条源都有 `source_id` / `url` / `normalized_url` / `domain` / `source_type` / `found_in`（含原始仓库+文件+配置键）
- [x] 真实存活数字：**healthy 48 / blocked 13 / dead 1 / disabled 10 / needs_credential 7 / unverified 1 = 80**
- [x] 计数口径可审计：107 原始记录 → 100 唯一 URL → **80 端点级源**（20 条为 Google Trends 同一端点的查询参数），**溯源记录仍为 107，零丢失**
- [x] 探测脚本可重复运行（`python scripts/probe_sources.py`），每次结果追加到 `health.jsonl` 形成健康历史
- [x] 控制组校验：`example.com` 探测失败时会自报"本地网络/代理问题，结论不可靠"，避免把网络抖动误报成源失效
- [ ] **待补**：`tests/contract/test_source_coverage.py` —— 把"107 条溯源不得丢失"变成 CI 强制断言（目前只是注册表事实，还没有守卫测试）

**阶段结论（可直接用于实现）**：
1. Reddit 的 12 个 JSON 端点全部 403，而 `old.reddit.com` 的 3 个 HTML 源全部健康 → 采集器直接用 HTML 方案
2. `git-trending.justlikemaki.vip` TLS 中断且为个人维护 → 改用 `github.com/trending` 直连或 GitHub 官方 API
3. 真正"死的"只有一个源。所谓"100 个源要维护"的实际可运行基数是 **48 个健康 + 13 个待改抓取方式**


### 阶段 3 · 统一数据模型与配置 ✅ 已完成
**产出**：`src/aidaily/{models,normalize,dedup,registry,config}.py`、`config/daily.yaml`、`sources/overrides.yaml`、`tests/`（**93 个测试全绿，2.3 秒，不联网**）

**验收结果**：
- [x] schema 校验能拒绝畸形配置并给出可读错误（`extra="forbid"` 全局生效，拼错的配置项会失败而不是被忽略）
- [x] `sources/overrides.yaml` 可覆盖 `enabled/priority/polling_interval/adapter/...` 而**不动** `registry.yaml`
- [x] 三条 overrides 硬规则：**溯源字段不可改**（`url`/`found_in`/`source_id` 是证据）、**引用不存在的 ID 报错**、**禁用必须写 reason**
- [x] 密钥与配置彻底分离：`config.py` 只从环境变量读密钥，`redact()` 可把密钥值从任意日志文本里抹掉
- [x] URL 规范化边界用例 46 个（`lwn.net` 两种 feed 不得归一、`raw.githubusercontent.com` 路径大小写保留、`follow.is` 的 `listId` 保持区分、Google News 查询参数保留、幂等性）

**开发过程中被测试抓出的 6 个真实缺陷（全部已修）**：
1. 溯源守卫用 `set` 比较 —— `repo:file#key` **不唯一**（23 条 Horizon RSS 共用 `sources.rss[]`），会误判通过 → 改 `Counter` 多重集
2. 标题品牌后缀阈值 14 会误伤"品牌在前"的标题 → 降到 8
3. `_merge_content` 的 `seen` 按整篇正文建立 → **共享段落被重复拼接** → 改为按段落
4. `同域名 + 同标题` 缺时间窗 → 会把"AI 早报"这类每日专栏合并成一条、**删掉整月内容** → 加 72h 窗口
5. `source_id` 用序号消歧（`reddit-com-top-2`…`-12`）→ **依赖排序、重建即漂移**，会让所有 overrides 失效 → 改为路径双段 + 内容哈希消歧
6. overrides 守卫**抓出了我自己拼错的两个 source_id**，以及台账里"presets 记成 enabled: true"的自相矛盾 → 已修正

**仍未做（诚实标注）**：
- L3 语义事件聚类（`EntityExtractor` / `cluster`）只有设计，没有实现 —— 它依赖 LLM 层，排在阶段 6 之后
- `quality`（质量打分）与 `rank`（分类配额）模块未写
- 采集器、CLI、发布通道全部未写（阶段 4 起）

### 阶段 4 · 采集器迁移 ✅ 已完成（首轮，覆盖 34 个源）
**产出**：`src/aidaily/http.py`、`fetchers/{base,rss,reddit,jsonapi,github_trending}.py`、`ingest.py`、`collect.py`、`__main__.py`

**首次真实全量采集结果（2026-10-14 实测）**：
```
sources_attempted 34    sources_ok 34    by_verdict {ok: 34}
items 3840              items_with_date 3818 (99.4%)    duration 31.0s
```
**34 个源零失败。** 未接入的 46 个源全部有明确原因（20 个未启用 / 14 个需凭证 / 2 个需专用适配器 / 10 个其它）。

**验收结果**：
- [x] 单源失败不影响其他源（`safe_fetch` 是唯一入口，结构上无法抛出）
- [x] 每个跳过的源都带原因（"静默不采集"与"采集到 0 条"必须可区分）
- [x] 离线单测 135 个，2.6 秒，**不联网**（`tests/unit/test_fetchers_offline.py` + `test_ingest.py`）
- [x] HTTP 层：不重试 4xx、429 读 `Retry-After`、同主机限速、条件请求、体积上限
- [x] 日期缺失保持缺失（`published_at=None` → `age_bucket=unknown`），绝不用抓取时间冒充

**本轮最有价值的发现：我的探测脚本给出过假阳性**
`old.reddit.com` 会 302 跳到 `/login/?reason=lor2`，返回一个 **330KB 的登录页 + HTTP 200**。我的探测只检查"状态码 200 且体积 > 2000 字节"，于是把 3 个 Reddit 源判成了**健康**。修正后健康数从 48 降到 39。
**结论：Reddit 目前完全无法匿名采集**（JSON 403 + HTML 登录墙），15 个源已标为 `needs_credential: REDDIT_CLIENT_ID` —— 配置完整保留，补上 OAuth 凭证即可启用。
教训：**HTTP 200 不是"源可用"的证据**，必须做内容结构校验。

**本轮被测试抓出的 4 个真实缺陷（已修）**：
1. `resolve_adapter` 对"人工明确指定的适配器"**静默回退**到通用解析器 → Google Trends 的 HTML 被当成 JSON 解析，报"HTTP 200、0 条"，看起来采集了其实什么都没采到
2. HuggingFace 的 `modelId` 在缺 `id` 字段时被拼成 `.../models/None`（`_URL_KEYS` 回退逻辑错误）
3. V2EX 的 `created` 字段不在日期键列表里 → **该源所有日期全部丢失**
4. `normalize_raw` 的语言优先级漏了 `spec.language`，任何忘记回填语言的采集器都会让源语言被重新推断

**仍未实现（诚实标注）**：
- `HtmlFetcher`（t.me 频道页）、`HackerNewsFirebaseFetcher`（需 N 次额外请求）、`PyTrendsFetcher`（pytrends 内部接口）—— 各自的源在运行报告中**明确列出原因**，不是静默零条
- 图片镜像与正文全文抓取（ai-daily-sources 的能力）尚未移植
- `quality` / `rank` / L3 聚类 / LLM 层 / 渲染 / 分发 全部未写

**要做**：把六仓库的采集能力移植为统一适配器
| 来源 | 迁移目标 | 说明 |
|---|---|---|
| Horizon `src/scrapers/*.py`（10 类）| `fetchers/` | MIT，可直接改造，保留版权头 |
| dailydawn `scripts/fetchers/*.py`（7 个）| `fetchers/` | **无 LICENSE → 只借鉴接口设计，代码重写** |
| ai-daily-sources `collect.py`（图片镜像 + 全文抓取）| `parse/` + `store/` | **你自有，可直接用** |
| daybrief（双 Provider + deadline）| `llm/` | **你自有，可直接用** |

**验收**：
- [ ] 每个适配器有离线 fixture 测试（用真实响应快照，CI 不联网）
- [ ] 单源失败不影响同分片其他源（有意注入失败验证）
- [ ] 100 源中 ≥ 70 条能在一次运行中返回数据（真实数字，来自阶段 2 探测）

### 阶段 5 · 去重与增量处理 ✅ L2 已完成（真实数据验证）
**产出**：`src/aidaily/select.py`（时间窗）、`src/aidaily/pipeline.py`（去重阶段 + 报告）、`scripts/diagnose_dedup.py`（独立诊断）、CLI `dedup` 子命令

**真实数据结果（2026-10-14 实测 3840 条原始数据）**：
```
时间窗：items_in 3882 → kept 243   （older 3556 / outside_window 70 / unknown 13）
       窗口内有内容的源：17 / 34
L2 去重：243 → 237 组，合并 6 条，合并率 2.47%，全部为跨源合并，歧义对 0
```
**合并正确性已人工逐条核对：6/6 全部正确，零误合并。** 六组都是同一个 URL 同时出现在
`api:hn-algolia-com-search` 与 `rss:hnrss-org-frontpage`，两个 feed 本就指向同一批 HN 首页内容。

**验收结果**：
- [x] 时间窗**先于**所有其他阶段（OpenAI News 一次返回 1287 条跨越数年，不先开窗会把 2024 年的文章带进今日日报）
- [x] 无日期的条目**不会被当成今天**：窗口源（GitHub Trending）标 `today_window`；普通源的无日期条目被排除但**计数并给出样例**
- [x] 去重报告里的每个数字都可追溯到一次运行（`data/state/dedup_report.json`）
- [x] 独立诊断脚本可复算（`python scripts/diagnose_dedup.py`）

**本轮抓出的 3 个真实缺陷**：

1. **Multi-Index Hashing 缺失（算法级）**。原候选生成只在 top-16 块上探测 `top ^ delta`（delta 0..3），
   即只能容忍该块**低 2 位**的差异。两个 simhash 若在第 63 位相差 1 位，会落进不同桶、**永远不被比较**。
   改用鸽巢原理：切成 `d+1` 个块，索引每块，保证距离 ≤ d 的对一定在至少一块上碰撞。
   已补两个专项测试（含 bit 63 差异）证明修复。
   > 诚实说明：这个 bug 是真的，但**它在当天的数据上并没有造成那 0%** —— 修复后仍是 0%。
   > 真正产生合并的是下面第 2 条的修复。两个 bug 叠在一起互相掩盖了。

2. **HN Algolia 缺少运行时时间过滤**。裸端点按热度排序返回**全站历史高票帖**，实测最新条目是
   7 个月前。dailydawn 的代码正是为此加了 `numericFilters=points>20,created_at_i>{cutoff}`。
   已实现为域特定的运行时参数注入（`created_at_i` 依赖当前时间，不能写进注册表 URL）。
   修复后窗口内条目从 210 升到 243，并第一次产生 6 组合并。

3. **我的操作失误（如实记录）**：用 PowerShell `Get-Content | Set-Content` 做文本替换，
   **把 UTF-8 测试文件的中文全部转成了乱码**并打断了一个字符串字面量。已用 `write` 工具整体重写恢复。
   教训：**绝不用 PowerShell 文本 cmdlet 往返 UTF-8 源码文件。**

**一个重要的架构验证（来自诊断脚本）**：
窗口内最相似的真实标题对只到 `sim 0.68–0.72 / hamming 11–20`，远低于 L2 阈值（0.85 / ≤3）。
这些正是**"不同文章报道同一事件"**——属于 L3，不是 L2。其中一对尤其说明问题：
```
员工借助AI辅助办公遭辞退，法院：合理使用不违规      - 新湖南
员工借助AI辅助办公遭公司辞退，法院判公司违法        - 新京报
```
两条标题相似度 0.696，但**结论相反**。若 L2 按标题相似度合并，就会把两条对立判决揉成一条假新闻。
这是"L2 必须保守、语义合并必须交给 L3 的 LLM 判断"最直接的实证。

**仍未实现**：L3 语义事件聚类（依赖 LLM 层）、增量处理（跨日 seen 索引）、`quality` / `rank`。

**要做**：L1/L2/L3 三层 + 实体词典 + `seen_index.sqlite` 运行期缓存
**验收**：
- [ ] L2 用**构造的**测试集验证：同文镜像合并、改标题同站合并、相似标题跨站**不**合并（三个断言缺一不可）
- [ ] L3 用一天真实数据人工抽检 20 个事件，误合并率 < 10%
- [ ] 7 天跨日合并可复现（构造两天数据验证）
- [ ] 去重前后数字进 `runs.jsonl`，可审计

### 阶段 6 · 统一 LLM 调用层 ✅ 已完成（含真实渠道实测）
**产出**：`src/aidaily/llm/{client,router}.py`、`scripts/probe_llm_channels.py`、`scripts/smoke_llm.py`、`docs/LLM_CHANNELS.md`、`tests/unit/test_llm_router.py`（25 个用例）

**渠道实测（157 个去重渠道，消耗 0 token）**：
```
方法：GET {base}/models —— 列模型不消耗 token，一次请求同时回答"key 是否有效"和"能调什么"
ok            123      ok_no_models 3      unauthorized 9
unreachable     7      bad_payload  5      rate_limited 2
no_models_route 4      error        4
HTTP 请求 157   消耗 token 0
```
官方渠道全部可用：Requesty 784 / OpenRouter 462 / Routeway 290 / 阿里云百炼 176 /
HuggingFace 121 / SiliconFlow 98 / NVIDIA 80 / **Google Gemini 63** / Mistral 46 /
ModelScope 36 / **Groq 11** / 智谱 11 / SeaLion 11 / **Cerebras 2**。
失败：Cohere 429、Cloudflare 405、GitHub Models 返回非 JSON、reka 403、SiliconFlow 另一个 key 401。

**真实端到端冒烟（Groq + `openai/gpt-oss-20b`）**：PASS，延迟 921ms，**消耗 92+96=188 token**。
→ 整轮探测 + 冒烟的总额度消耗约 **220 token**。

**统一层实现的四个可靠性机制**（每个都来自某个被审计项目的真实教训）：
| 机制 | 来源 | 行为 |
|---|---|---|
| 降级链 | dailydawn | 主模型失败换下一个，不让单个模型拖垮整条流水线 |
| 供应商拉黑 | daybrief `mark_down` | `429 + per day` 直接拉黑本次运行，**绝不空等** |
| 参数降级 | 新增 | 供应商拒绝 `response_format` 时**去掉该参数重试**，而不是放弃它 |
| 预算熔断 | 新增 | 超调用/超 token 抛 `BudgetExceeded`，调用方降级为规则摘要 |
| 中转层硬上限 | 新增 | relay 层每次运行最多 20 次调用 |

**冒烟测试抓出的 2 个真实集成 bug（离线 MockTransport 抓不到）**：

1. **JSON 校验失败的误分类**。Groq 对 `response_format: json_object` 生成失败返回
   `400 Failed to validate JSON. Please adjust your prompt.` —— 这句话里**既没有**
   `response_format` 也**没有** `json_object`。我的 400 分类器因此把**健康的供应商**
   当成故障丢弃了。现在按"参数组合不被接受"处理：去掉 JSON 模式重试一次。

2. **推理模型会返回空 content**。`openai/gpt-oss-20b` 是推理模型，`max_tokens=16` 时
   **全部预算被推理 token 吃掉**，`content` 是空字符串。如果把它当成功返回，日报会
   **静默产出空摘要**。现在空回复（含纯空白）视为 `ProviderError`，路由会换下一个供应商；
   `finish_reason` 也记入响应以便诊断。这一条直接决定了配置里的 `max_tokens` 下限。

**仍未实现**：L3 语义事件聚类（现在有了 LLM 层，可以实现）、`quality` / `rank`、渲染与分发。

**要做**：`llm/client.py` 三 tier + 能力声明 + 预算熔断 + JSON 守卫
**验收**：
- [ ] 至少 5 家供应商（Gemini/Groq/Cerebras/SambaNova/OpenRouter）冒烟通过（真实调用，需你的 key）
- [ ] 降级链可复现：注入 429 → 自动切换且记录
- [ ] `mark_down` 生效：`429 + per day` 不重试
- [ ] 预算熔断：超限后改用规则兜底，流水线不失败
- [ ] 成本统计写入 `llm_usage.jsonl`

### 阶段 7 · 日报生成 ✅ 已完成（真实 LLM 端到端验证）
**产出**：`src/aidaily/{l3,analyze,render,factcheck}.py`、CLI `run` 子命令、`scripts/run_local.py`、`tests/unit/{test_l3,test_output}.py`

**首次真实端到端结果（2026-10-14，Groq + Gemini）**：
```
采集/重放  3882 条 → 窗口 237 → L2 后 229 个事件（合并 8，3.4%，多源 7）
事实校验   0 违规
模型       10 次调用 / 7,771 token（prompt 5209 + completion 2562）
           供应商 groq 3 次、gemini 7 次  ← 降级链实际生效
摘要质量   6/6 由模型生成，事实/推断/不确定三栏分离
```

**防幻觉的结构性设计**：
- **模型永远不输出 URL**。它只返回 item id；链接由程序从自己的记录回填。编造链接在结构上不可能发生。
- **模型正文里出现链接就丢弃该行**（`analyze.py`），入库时也会把来源摘要里的裸链接剥掉（`strip_text_urls`）——否则那些链接会绕过"每个链接都可验证"的保证。
- **事实/推断/观点/不确定是四个独立字段**，不是一段 summary。合并成一段就无法区分"报道的事实"和"模型的猜测"。
- **事实校验是发布闸门**：URL 必须逐字来自输入、日期必须来自 `published_at`、多源声明必须有 ≥2 个独立来源。

**本轮抓出的 7 个真实缺陷（全部已修）**：

1. **L3 拿到的是原始 items 而不是 L2 分组** → 把 L2 刚合并的重复项又拆开了。改为以 `ArticleUnit` 为操作单元。
2. **"多源"把同一来源算了两遍**。`hn-algolia` 与 `hnrss` 承载同一批 HN 内容，却被计为 2 个独立来源——**制造了虚假的可信度**。新增 `dedup_group` 概念与 `independent_source_count`，排序与标注都改用它。
3. **`check_digest` 用墙上时钟判断"未来日期"** → 校验不确定、重放历史数据会得出不同结论。改用 `digest.generated_at`。
4. **`strip_html` 里的 NFKC 把中文全角标点转成半角**（`：`→`:`）。NFKC 属于指纹计算，用在展示文本上会让中文排版悄悄变样。已分离。
5. **`render_deep` 只读 `sections`**，若为空就渲染出**空日报**——输出阶段的静默全损。改为以 `top_events` 为准。
6. **`complete_json` 的修复重试会因调用方已传 `temperature` 而重复传参崩溃**。
7. **`AsyncClient` 跨多次 `asyncio.run()` 导致事件循环已关闭**；且 **L3 判定是串行的**——60 个候选簇把首次真实运行拖到 10 分钟以上被迫中止。现在并发判定（信号量 4）。

**另一个真实发现**：`gemini-2.5-flash-lite` 已对新用户返回 `404 no longer available`，而 `gemini-flash-lite-latest` 别名仍有效——**这解释了 daybrief 为何用 `-latest`**。同时 `ProviderError` 原本不记录，导致 Gemini 每次调用都失败却在输出里**完全不可见**；现在 `provider_failures` 会记录最后一次错误。

**仍未实现**：增量处理（跨日 seen 索引）、GitHub Actions 工作流、Pages 前端、五路分发。

**要做**：速览版 + 深度版渲染；事实校验；来源覆盖率展示
**验收**：
- [ ] 速览版 ≤ 15 条、深度版 ≥ 30 条且含趋势段落
- [ ] **防幻觉校验通过**：所有 URL 逐字来自输入；所有日期来自 `published_at`；`facts/inferences/opinions` 三字段分离
- [ ] 每个事件显示全部来源链接（完整性硬要求）
- [ ] 数据不全时 `warnings` 非空且在页面上可见

### 阶段 8 · GitHub Actions 自动化 ✅ 已完成
**产出**：`.github/workflows/{ci,daily}.yml`、`src/aidaily/{state,publish}.py`、CLI `gate` 子命令、关键源等待闸门、五路分发

**`daily.yml` 的四个 job（单工作流 + 制品检查点，而不是三个用 `workflow_run` 串联的工作流）**：
```
gate     （5 分钟）  ← 最便宜的一步放最前：无事可做的触发只花几秒、0 次 API 调用
collect  （25 分钟） ← 34 个源实测 17-45 秒，因此不分片：分片要加机制，150 个源以后才值得
publish  （40 分钟） ← 从制品读取，重试不重新抓取，同一天的日报只来自一个数据快照
deploy   （Pages）
```
四个触发点：`09:53 / 10:07 / 10:23 / 10:41`（**用 `timezone: Asia/Shanghai`，不手算 UTC**）。
官方文档明确 schedule 事件会延迟、**排队任务可能被丢弃**、整点是高峰——所以四个互为兜底，幂等闸门让第一个成功的生效。

**幂等闸门（`state.py`）**：
- 退出码 **10 = 今天已发布**，与 1（出错）严格区分——"无事可做"永远不该被当成故障
- 账本 `data/state/runs.jsonl` 追加式；**损坏的行会被跳过**，不会让某一天永久无法发布
- 部分发布记 `partial` 并保留已完成通道，重试**只补失败的通道**——重复发一封邮件比不发更糟，读者分不清是重复还是更正

**关键源等待闸门（`collect.py::wait_for_critical`）**：juya 实测 09:48 发布、运行在 10:00，**12 分钟余量不是排期而是巧合**。缺当日版的关键源会每 2 分钟重抓一次（只重抓缺失的那几个，不重跑全量），最多等 20 分钟；超时则继续发布，并在日报里**写明哪个源退回了 T-1 版本**——迟到的源永远不阻塞发布。

**五路分发（`publish.py`）**：RSS / Pages / 邮件 / Telegram / n8n，各自独立 try/except，互不牵连。邮件与 Telegram 支持长文分块（Telegram 4096 字符上限）。

**本轮抓出的 2 个真实缺陷**：

1. **"未配置凭证而跳过"被记成了 `ok`**。`channels` 属性先判断 `ok` 再判断 `skipped`，而跳过的结果 `ok=True`。后果：补上 SMTP 凭证后重跑，状态层会认为邮件已发过而**永远不再发**。
   同时修正了语义：**"配置里启用但凭证没提供"是部署状态（跳过 + 大声提示），不是运行时故障**——否则一个新克隆的仓库永远无法跑绿。

2. **我引用的 action 版本全部过时**。`checkout@v4` / `setup-python@v5` / `upload-artifact@v4` / `download-artifact@v4` 都是从被审计仓库沿用的（它们自己就过时）。查 GitHub Releases API 核实当前版本后统一升级：
   `checkout@v7`、`setup-python@v7`、`upload-artifact@v7`、`download-artifact@v8`、`upload-pages-artifact@v5`、`deploy-pages@v5`。
   **上传与下载必须同代升级**——跨大版本的 artifact 格式不保证兼容。

**CI 的三道守卫**（`ci.yml`，py3.11 + py3.12 矩阵）：
- 源溯源守卫：107 条审计溯源一条不能丢
- **注册表可复现性**：重新生成必须产出完全相同的 source_id（否则 overrides 与 critical_sources 会静默失效）
- 密钥扫描 + PII 扫描（正则匹配 `sk-`/`ghp_`/`cfat_`/`AKIA` 等，以及 qq/gmail 邮箱）——被审计仓库里就有把个人邮箱和 Telegram chat_id 提交进公开仓库的先例

**仍未实现**：Pages 前端动效（当前是朴素的 `<pre>` 页面）、跨日增量索引。

**要做**：6 个 workflow（见 WORKFLOWS.md）
**验收**：
- [ ] 连续 7 天定时触发，统计实际触发时间与延迟分布（**真实数据**）
- [ ] 人为制造 push 冲突，验证 rebase 重试生效
- [ ] 强杀中途运行，验证下次触发能通过幂等闸门补跑
- [ ] 完整性闸门拦截一次（故意让 60% 源失败）

### 阶段 9 · 集成测试 ✅ 已完成
**产出**：`tests/unit/test_http.py`（22 例）、`tests/integration/test_end_to_end.py`（11 例）、`tests/integration/test_network.py`（联网，默认自跳过）、`docs/ACCEPTANCE.md`（十一项验收要求的逐条对照表）

**规模**：**249 个离线测试，约 8 秒，默认不联网**；另有 3 个联网验收测试，需 `AIDAILY_NETWORK_TESTS=1` 显式开启。

**联网验收实测（真实运行）**：**37/37 个已启用源全部可达，零失败。**

**补上的真实缺口**：`http.py` 有 171 行承载着重试、限流、条件请求逻辑，此前**一个测试都没有**。新增 22 例覆盖：
- **不该重试的**：400/403/404/410 只请求一次（重试 403 只会烦扰对方并浪费运行预算）
- **该重试的**：503 → 退避后成功；连接错误 → 重试 2 次后判 `dead`
- **429 读 `Retry-After`**，但**上限 30 秒**——服务器可以要求等一小时，运行等不起
- 条件请求：ETag/Last-Modified 被存储与回放；304 归为 `not_modified`
- 同主机限速、响应体上限、403 → `blocked` 而非 `dead`（两者需要不同的修法）

**端到端集成测试覆盖的行为**：
- 同一事件被 3 个 feed 报道 → **1 个多源事件且 3 个链接全在**（不是 3 条）
- 未来日期条目（Ai2 feed 的已知问题）与无链接条目被丢弃，**且丢弃计数进入发布记录**而不只是控制台
- `--no-llm` 时日报**明确声明自己是规则降级版**，不装作正常
- 采集为空 → 退出码 1，**不发出空日报**

**本轮抓出的 3 个真实缺陷**：

1. **日报日期用了运行机器的本地时区**。`build_digest` 用 `now.astimezone()`，而 GitHub Actions 跑在 UTC——北京时间凌晨生成的日报会被标成**前一天**。文件名、账本键、RSS guid 全部由它派生。已改为使用配置里的 `Asia/Shanghai`。
2. **`--out-dir` 指向项目外时 CLI 崩溃**。`Path.relative_to` 会对项目外路径抛异常，而这发生在**日报已经生成之后**——CI 里把产物写到 artifact 目录正是这种用法。
3. **被丢弃条目的原因没有进入发布记录**。只出现在控制台日志里，而日志没人留。现在 `digest.counts` 带 `dropped_future_dated` / `dropped_no_url` / `dropped_older` 等计数——一份静默丢弃 3500 条输入的日报，应该自己说得出这件事。

**仍未验收（诚实标注，见 `docs/ACCEPTANCE.md` 第六节）**：Actions 真实定时执行（T7，需推到 GitHub 后观察）、Pages 前端动效、跨日增量索引、邮件/Telegram/n8n 的真实送达（本地无凭证，走的是"跳过 + 警告"路径）。

**验收**：见下节"十项测试规范"全绿

### 阶段 10 · 正式运行与持续维护 ✅ 已完成
**产出**：公开仓库 https://github.com/siweimidu/ai-ribao 、Pages 站点 https://siweimidu.github.io/ai-ribao/ 、`docs/RUNBOOK.md`、`docs/RUN_LOG.md`

**首次真实运行（2026-10-14，手动触发全链路验证）**：
```
gate     13s      force 生效
collect  21m3s    其中 20 分钟是等待闸门超时 —— 本次发现并修复
publish  12m23s   231 个事件 / 39 次模型调用 / 29,920 token / 事实校验 0 违规
deploy   19s      Pages 上线
总耗时 34 分钟，四个 job 全部成功
```
| 验证项 | 结果 |
|---|---|
| Pages 首页 | HTTP 200 |
| 单日页面 | HTTP 200，12,216 字节 |
| RSS | HTTP 200，**60 个 item** |
| 摘要来源 | 40 个事件中 34 个由模型生成 |

**本次运行发现并修复的真实缺陷**：关键源等待闸门在非调度时段空等 20 分钟。
juya 09:48 才发布，凌晨 2 点触发时它的当日版**根本不存在**。已加调度窗口判定
（`run.at - 30min` 到 `run.at + 3h`，覆盖四个触发点），窗口外立即返回缺失清单不再等待。
**同时确认闸门超时行为符合设计**：四个关键源被逐个点名，没有静默替换成昨天的内容。

**GitHub 侧还暴露了两个本地测不出的 CI 缺陷**（都已修复并验证绿灯）：
1. **密钥守卫静默失效**——模式里用了 POSIX ERE 不支持的前瞻断言与非捕获组，
   `git grep` 报语法错误退出 2，而 `if git grep` 把非零退出当成"未找到"，
   守卫**永远打印 clean、什么都没检查**。已改为 `(^|[^A-Za-z0-9])` 表达边界，
   并捕获退出码而非用 `if` 分支。
2. **PII 守卫命中了测试文件自身**——夹具里写了真实邮箱与 AWS 示例 key。

教训写进了 `scripts/ci_guards.sh`：**守卫必须在真实 shell 下验证**，
不能只用 Python 的 `re` 编译一遍就算数——两种引擎的方言不同。

**首次运行暴露的质量问题（不是缺陷，但已登记待办）**：
排序只用「独立来源数 + 时间」，当天独立来源数全为 0 时退化为**纯按时间排**——
高频源（HN）占满头部，低频高价值的实验室博客永远进不去；而 HN 条目本身没有正文，
模型只能产出「Title: xxx」「Points: 153」这种没有信息量的事实。
下一轮应接入 `quality.source_weights`（配置里已有但未接代码）并限制单一源占比。

**要做**：启用定时；建立周报机制（死源、成本、覆盖率）
**验收**：
- [ ] 连续 14 天无人值守运行，发布成功率 ≥ 95%
- [ ] 每周成本报告与真实 token 消耗一致
- [ ] 源数量只增不减（除非人工在 `overrides.yaml` 显式禁用并留原因）

---

## 二、测试与验收规范（对应任务书 §十二.I 的十项要求）

| # | 测试 | 实现位置 | 断言语义 | 何时跑 |
|---|---|---|---|---|
| T1 | **六仓库信息源覆盖率** | `tests/contract/test_source_coverage.py` | 对每条 `(repo, file, config_key)` 三元组，registry 中必须有源指向它；**缺一即红** | 每次 CI |
| T2 | **重复源检测** | `tests/unit/test_normalize_url.py` | 规范化幂等；已知同义 URL 归一到同一 key；已知异义 URL（`lwn` 两种 feed）**不得**归一 | 每次 CI |
| T3 | **文章重复识别** | `tests/unit/test_dedup_l2.py` | 三组固定样本：镜像合并✅、同站改标题合并✅、跨站相似标题不合并✅ | 每次 CI |
| T4 | **LLM API 兼容性** | `tests/integration/test_llm_providers.py` | 逐个供应商发最小请求；不支持 `json_object` 时自动降级；失败不阻断其他供应商 | 手动/每日 1 次（耗额度） |
| T5 | **Secrets 泄露检查** | `ci.yml` + `.secrets.baseline` | `detect-secrets` + 正则扫 `sk-/ghp_/cfat_/AKIA`；命中即失败 | 每次 CI |
| T6 | **PII 检查** | `tests/contract/test_no_pii.py` | 仓库内不得出现邮箱、Telegram chat_id、真实姓名 | 每次 CI |
| T7 | **Actions 定时执行** | `docs/run-log.md`（人工记录） | 记录 14 天实际触发时间，统计延迟与漏触发 | 运行期 |
| T8 | **失败重试** | `tests/integration/test_retry.py` | 注入 429/500/超时，验证退避与降级；验证限流不重试 | 每次 CI（mock） |
| T9 | **幂等性** | `tests/integration/test_idempotency.py` | 同一 digest 跑 publish 两次，第二次必须 no-op；分通道重跑只补失败通道 | 每次 CI |
| T10 | **日报质量** | `tests/integration/test_digest_quality.py` | URL 全在输入集合内；日期无未来值；三字段分离；每条事件 ≥1 来源；多源事件占比报告 | 每次 CI（用固定 digest fixture） |
| T11 | **来源链接有效性** | `scripts/probe_sources.py` | 抽样校验日报内链接 HTTP 200 | 每周 |

**"日报质量"的关键补充断言**（防幻觉）：
```python
def test_no_fabricated_urls(digest, raw_items):
    allowed = {i.url for i in raw_items} | {i.canonical_url for i in raw_items}
    for ev in digest.all_events():
        for u in ev.all_urls:
            assert u in allowed, f"日报出现输入中不存在的链接: {u}"

def test_no_future_dates(digest):
    for ev in digest.all_events():
        assert ev.published_at is None or ev.published_at <= digest.generated_at
```

---

## 三、风险清单（含缓解措施与触发信号）

### 技术风险
| 风险 | 概率 | 影响 | 缓解 | 触发信号 |
|---|---|---|---|---|
| GitHub 定时任务被丢弃 | 中 | 当天无日报 | 6 个触发点 + 幂等 + 手动补跑 | runs.jsonl 出现整天空档 |
| Actions 单 job 超时（40 min） | 中 | 分析中断 | 分片 + artifact 检查点 + 全局 deadline | 运行时长逼近阈值 |
| 免费额度耗尽 | **高** | 摘要降级为规则版 | 三层供应商 + 预算熔断 + 批量调用 | `llm_usage.jsonl` 中 429 占比上升 |
| 第三方中转站大规模失效 | 高 | 兜底层消失 | 仅作兜底，主力是官方免费 | 兜底层成功率 < 50% |
| 去重误合并 | 中 | 信息丢失（不可逆） | 保守阈值 + `needs_review` 队列 + 人工抽检 | 抽检误合并率 > 10% |
| 源站改版导致解析失败 | **高** | 该源失效 | 断言解析结果非空 + 健康告警（不静默） | 单源连续 3 天 0 条 |

### 数据风险
| 风险 | 缓解 |
|---|---|
| 第三方微信转 RSS 服务（`wechat2rss.xlab.app`、`decemberpei.cyou`）失效 | 永不删除配置；标记 degraded；多源冗余覆盖同一媒体 |
| 上游日报源（juya/dailydawn）本身挂掉 | 关键源等待闸门 + T-1 回退 + 明确标注"今日该源无当日版" |
| 仓库体积失控 | 月度分片压缩 + 正文 30 天滚动 + OG 图不入库 + 年度归档 |

### 成本风险
| 风险 | 缓解 |
|---|---|
| 免费额度政策变化（官方可能随时调整） | 报告中注明抓取日期；额度用尽自动降级为规则摘要，不中断日报 |
| 深度版双语导致 token 翻倍 | 深度版默认中文，英文按需 |
| 中转站按量计费陷阱 | 兜底层硬限制 `max_calls_per_run: 20` |

### 维护风险
| 风险 | 缓解 |
|---|---|
| 上游 Horizon 更新难以跟进 | 我们是 fork 关系而非依赖，吸收其改进需人工 merge；记录 diff |
| 单人维护 | 全部逻辑无服务器依赖；失败时自愈（幂等 + 重试）；文档与测试即知识库 |
| 许可证污染 | CI 中加入依赖许可证扫描（`pip-licenses`）；GPL 依赖直接失败 |

---

## 四、当前状态与下一步

### 阻塞项：**无。** 第 1、2 轮澄清已覆盖全部架构级决策：

| 决策 | 结果 |
|---|---|
| 架构路线 | B+C 融合（Python 单体内核 + Actions 矩阵分片），文件即数据库 |
| 生成时间 | **北京时间 04:00 / 12:00 / 20:00 三跑**（原 07:00/19:00 两跑） |
| 信息源 | 100 条全继承，失效也保留并标记，禁止静默删除 |
| LLM | 官方免费额度优先 + 第三方中转兜底；深度版默认纯中文 |
| 输出 | 一次采集渲染两份：速览版（邮件+Telegram）+ 深度版（Pages+RSS+n8n） |
| 历史 | 全量保存 + Pagefind 静态搜索 |
| 仓库 | 公开仓库（Actions 免费）；凭据绝不入仓；R2 密钥轮换 |

### 新识别的小风险（已设计缓解，无需你决策）
juya 实测 09:48 发布，10:00 运行只有 **12 分钟余量** → 已加**关键源等待闸门**（最多等 20 分钟，超时则标注"使用 T-1 版本"而非静默漏掉）。

### 确认后立即执行的第一个动作（阶段 2）
1. 生成 `sources/registry.yaml`：把 `audit/sources_ledger.json` 的 100 条唯一源固化为带完整溯源的注册表
2. 写 `scripts/probe_sources.py` 并**真实联网探测** —— 产出"到底有多少源是活的"这个真实数字（`healthy / degraded / dead / needs_credential / unverified`）
3. 生成首份健康报告 `docs/HEALTH_REPORT.md`

**这一步之前谁都不知道失效源有多少，我不会给预估数字。**

