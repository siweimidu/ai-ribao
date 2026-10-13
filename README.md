# AI 日报

把六个 AI 日报相关仓库里有价值的信息源与处理能力，整合成一个**自动运行、可自证完整**的聚合平台。

每天北京时间 **10:00** 自动运行一次：采集 34 个已启用的信息源 → 三层去重 → 大模型分析 →
生成**速览版**（邮件 + Telegram）与**深度版**（GitHub Pages + RSS + n8n），零常驻服务器。

```
3882 条原始条目 → 时间窗 237 条 → L2 去重 229 个事件 → 事实校验 → 五路分发
真实消耗：约 10 次模型调用 / 7,800 token / 每次运行
```

---

## 它和"把六个仓库拼起来"有什么区别

审计发现六个仓库里**四个是第三方上游的 fork**，其中两个用户**一行源码都没改**。
真正的自有资产只有约 6 个文件。因此这个项目不是拼装，而是：

1. **完整继承信息源**：107 条审计记录 → **80 个端点级唯一源**，其中 20 条是同一
   Google Trends 端点的查询参数。溯源一条不丢，CI 有强制守卫。
2. **重新实现处理逻辑**：GPL-3.0 的 CloudFlare 仓库与**无许可证**的 dailydawn 都
   **没有复制任何代码**（见 `NOTICE`），只吸收了 URL 清单这类事实性数据。
3. **三层去重严格分离**：重复的**源**、同一篇文章的**重复抓取**、多篇不同文章报道
   **同一事件**——三个不同的问题，三套不同的规则。

---

## 设计上几个不妥协的地方

**模型永远不输出 URL。** 它只返回条目 id，链接由程序从自己的记录回填。
编造链接在这个设计里**结构上不可能发生**。入库时还会剥掉来源摘要里的裸链接，
否则那些链接会绕过"每个链接都可验证"的保证。

**事实与推断分开。** 每条事件产出四个独立字段：`facts` / `inferences` / `opinions` /
`uncertainties`。合并成一段 summary 就无法区分"报道的事实"和"模型的猜测"。

**丢失信息比留下噪音严重得多。** L2 去重在"不同域名 + 标题相似"时**不合并**，
只记进歧义队列供人工复核。实证：窗口内最相似的一对真实标题相似度 0.696，但
一条说"法院判合理使用不违规"、另一条说"法院判公司违法"——**结论相反**。

**HTTP 200 不是"源可用"的证明。** `old.reddit.com` 会返回 200 加一个 330KB 的登录页。
探测脚本现在做 DOM 结构校验（这个假阳性一开始骗过了我自己）。

**失败必须可见。** 跳过一个源要写原因，丢弃条目要计数并进入发布记录，
模型供应商失败要记录最后一次错误。一份静默丢弃 3500 条输入的日报，
应该自己说得出这件事。

---

## 快速开始

```bash
pip install -e ".[fetchers,llm,dev]"

pytest -q                                   # 249 个离线测试，约 8 秒，不联网

# 本地完整链路（密钥从文件读入内存，不落仓库）
python scripts/run_local.py keys.json run --from-items data/raw/items.jsonl

# 不调用模型，只验证链路
python -m aidaily run --from-items data/raw/items.jsonl --no-llm --no-deliver

# 真实源健康探测（生成 docs/HEALTH_REPORT.md）
python scripts/probe_sources.py

# 模型渠道可用性探测（用 GET /models，消耗 0 token）
python scripts/probe_llm_channels.py --keys keys.json
```

---

## 在 GitHub 上运行

1. 建一个**公开仓库**（公开仓库的标准 runner 完全免费，这是成本模型的前提）。
2. 在 Settings → Secrets 中配置（见 `docs/RUNBOOK.md` 的完整清单）：
   ```
   GEMINI_API_KEY / GROQ_API_KEY          # 至少一个模型供应商
   SMTP_HOST / SMTP_PASSWORD / MAIL_TO    # 邮件
   TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID  # Telegram
   N8N_WEBHOOK_URL                        # n8n
   ```
   一个都不配也能跑：日报会照常生成并发布到 Pages，跳过的通道会在运行摘要里明确列出。
3. 工作流按 `09:53 / 10:07 / 10:23 / 10:41`（北京时间）四个触发点运行，
   第一个成功的发布生效，其余被幂等闸门跳过。

---

## 目录

```
src/aidaily/
  registry.py    信息源注册表 + 溯源完整性守卫（多重集比较，禁用必须写 reason）
  http.py        重试策略（4xx 不重试）/ 限速 / 条件请求 / 响应体上限
  fetchers/      RSS·Atom·JSONFeed / 通用 JSON API / Reddit / GitHub Trending
  ingest.py      RawItem → NormalizedItem（日期缺失就保持缺失，决不用抓取时间冒充）
  normalize.py   URL 规范化 / 标题规范化 / SimHash（CJK 用字符二元组）
  dedup.py       L2 文章级去重（并查集 + 多索引哈希 + 歧义标记）
  select.py      时间窗（未来日期与无链接条目在此显式排除并计数）
  l3.py          L3 语义事件聚类（实体重叠 + 时间桶 + 并行 LLM 判定）
  analyze.py     摘要生成（事实/推断/观点/不确定四栏分离）
  llm/           统一调用层（分层路由 / 降级链 / 供应商拉黑 / 预算熔断）
  factcheck.py   发布闸门（URL 与日期必须来自输入，多源声明必须诚实）
  render.py      速览版 / 深度版 / JSON Feed / 邮件 HTML
  publish.py     五路分发（各自独立，互不牵连）
  state.py       幂等账本（退出码 10 = 今天已发布，与故障严格区分）
```

---

## 文档

| 文件 | 内容 |
|---|---|
| `audit/AUDIT_REPORT.md` | 六仓库深度审计（含 fork 差异实测、许可证分析、安全发现） |
| `docs/ARCHITECTURE.md` | 架构、四方案对比、三层去重算法、数据模型、成本模型 |
| `docs/WORKFLOWS.md` | 工作流设计、官方调度限制、八个关键问题的逐条回答 |
| `docs/ACCEPTANCE.md` | 十一项验收要求 → 实际测试对照表 |
| `docs/ROADMAP.md` | 十阶段实施记录（含每一轮抓出的真实缺陷） |
| `docs/HEALTH_REPORT.md` | 信息源真实存活探测结果 |
| `docs/LLM_CHANNELS.md` | 157 个模型渠道可用性实测（0 token 成本） |
| `docs/RUNBOOK.md` | 运维手册：Secrets 清单、故障处置、成本控制 |

---

## 许可证

MIT。第三方归属见 `NOTICE`。本项目的源码**不包含** GPL-3.0 或无许可证项目的任何代码。

日报中的内容是第三方来源的摘要与链接，请以原始来源为准；生成内容由 AI 辅助整理。
