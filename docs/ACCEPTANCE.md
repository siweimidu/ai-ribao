# 验收规范与测试对照表

日期：2026-10-14
测试规模：**249 个测试，约 8 秒跑完，默认不联网**

---

## 一、任务书 §十二.I 的十一项验收要求 → 实际测试

| # | 要求 | 实现位置 | 状态 |
|---|---|---|---|
| T1 | 六仓库信息源覆盖率 | `tests/contract/test_source_coverage.py` | ✅ 8 个用例 |
| T2 | 重复信息源检测 | `tests/unit/test_normalize_url.py` | ✅ 46 个用例 |
| T3 | 文章重复识别 | `tests/unit/test_dedup_l2.py` | ✅ 13 个用例 |
| T4 | 大模型 API 兼容性 | `tests/unit/test_llm_router.py`（离线）+ `tests/integration/test_network.py`（联网）+ `scripts/probe_llm_channels.py`（157 渠道实测） | ✅ |
| T5 | Secrets 泄露检查 | `.github/workflows/ci.yml` guards job + `tests/` 中的 `redact` 用例 | ✅ |
| T6 | PII 检查 | 同上（正则匹配 qq/gmail/163/outlook 邮箱） | ✅ |
| T7 | GitHub Actions 定时执行 | `docs/RUN_LOG.md`（人工记录）+ 四触发点 + 幂等闸门 | 🟡 待首次真实运行 |
| T8 | 失败重试 | `tests/unit/test_http.py`（22 个用例）+ `test_llm_router.py` | ✅ |
| T9 | 幂等性 | `tests/unit/test_state_publish.py` + `tests/integration/test_end_to_end.py` | ✅ |
| T10 | 日报质量 | `tests/unit/test_output.py` + `tests/integration/test_end_to_end.py` | ✅ |
| T11 | 来源链接有效性 | `scripts/probe_sources.py`（真实探测）+ `test_network.py`（联网验收） | ✅ 已实测 |

---

## 二、防幻觉的具体断言（对应任务书"必须区分事实、来源原文、模型推断和观点"）

| 断言 | 测试 | 机制 |
|---|---|---|
| 模型不能输出 URL | `test_output.py::test_insight_rejects_urls_in_prose` | 模型只返回 item id；链接由程序回填 |
| 正文出现链接则该行丢弃 | `analyze.py::analyze_event` | 生成时过滤，不是事后检查 |
| 输入里没有的链接 | `test_output.py::test_fabricated_url_is_caught` | `check_digest` 逐条比对 |
| 输入里没有的日期 | `test_output.py::test_fabricated_date_is_caught` | 同上 |
| 未来日期 | `test_output.py::test_future_date_is_caught` | 参照 `digest.generated_at`，不用墙上时钟 |
| 事实/推断/观点/不确定分离 | `test_output.py::test_insight_requires_all_three_buckets` | 四个独立字段，缺一即违规 |
| 虚假的多源声明 | `test_output.py::test_false_multi_source_is_caught` | 按 `independent_source_count` 判定 |
| 多源声明的反例 | `test_output.py::test_understated_multi_source_is_caught` | — |

**发布闸门**：`check_digest` 不通过时 `run` 返回退出码 2，**不发布**。

---

## 三、信息源完整性（项目的硬承诺）

| 保证 | 机制 | 测试 |
|---|---|---|
| 107 条审计溯源一条不丢 | 注册表 `found_in` + 多重集比较 | `test_every_audited_source_location_survives` |
| 守卫**真的会失败** | 删掉 daily-briefing 的唯一源即触发 | `test_guard_actually_fails_when_a_source_is_removed` |
| 禁用 ≠ 删除 | 禁用必须写 reason，源仍留在注册表 | `test_disabling_without_a_reason_is_rejected` |
| 溯源不可改写 | `url`/`found_in`/`source_id` 是证据 | `test_immutable_fields_cannot_be_overridden` |
| 注册表可复现 | 重建必须产出相同 source_id | CI `Registry is reproducible` 步骤 |
| 失效源保留 | 20 个未接入 + 7 个需凭证全部在册 | `test_no_source_was_silently_enabled_or_deleted` |

---

## 四、三层去重的分离（任务书 §三.2 要求"不能使用同一种去重规则"）

| 层 | 判定对象 | 规则 | 误判的代价 | 测试 |
|---|---|---|---|---|
| L1 源级 | 注册表条目 | URL 规范化 + 参数级合并 | 虚高完整性 | `test_registry_shape_is_stable` |
| L2 文章级 | 抓取条目 | 精确键 → simhash+标题 → 同域同标题（**有时间窗**） | **不可逆地删掉一条新闻** | `test_dedup_l2.py` 13 例 |
| L3 事件级 | L2 分组 | 实体重叠 + 时间桶 + **LLM 判定** | 制造虚假关联 | `test_l3.py` |

**L2 必须保守的实证**：窗口内最相似的真实标题对只到 `sim 0.68–0.72`，其中一对是
「员工借助AI辅助办公遭辞退，法院：合理使用不违规」与「……法院判公司违法」——
**标题相似度 0.696，结论相反**。若 L2 按标题合并，两条对立判决会被揉成一条假新闻。

---

## 五、真实运行记录（可复核的数字）

| 项目 | 数字 | 来源 |
|---|---|---|
| 六仓库源配置记录 | 107 | `audit/sources_ledger.json` |
| 端点级唯一源 | 80 | `sources/registry.yaml` |
| 首次探测健康源 | 39 healthy / 13 blocked / 1 dead / 20 disabled / 7 needs_credential | `docs/HEALTH_REPORT.md` |
| 首次全量采集 | 34 源全部成功，3882 条，17 秒 | `data/state/collect.jsonl` |
| 时间窗后 | 237 条（older 3556 / 窗口外 70 / 无日期 13 / 未来日期 4 / 无链接 11） | `data/state/dedup_report.json` |
| L2 合并 | 8 条，3.4%，全部跨源，**人工核对 8/8 正确** | 同上 |
| LLM 渠道实测 | 157 渠道，**0 token**，123+3 可用 | `docs/LLM_CHANNELS.md` |
| 首次真实 LLM 端到端 | 10 次调用 / 7,771 token，两供应商均生效 | `data/digests/*.json` |
| 日报事实校验 | 0 违规 | 同上 |

---

## 六、尚未验收的项目（诚实标注）

| 项目 | 为什么还没验收 | 计划 |
|---|---|---|
| T7 Actions 真实定时 | 需要把仓库推到 GitHub 并等待真实触发 | 阶段 10，记录到 `docs/RUN_LOG.md` |
| Pages 前端动效 | 当前是朴素 `<pre>` 页面 | 独立任务，用 UI/动效 skill |
| 跨日增量索引 | 未实现 | 阶段 10 之后 |
| 邮件/Telegram/n8n 真实送达 | 本地无凭证，走的是"跳过 + 警告"路径 | 配置 Secrets 后由 T7 顺带验证 |
| 9 个需凭证的源（Reddit 15 个中 12 个 + Folo 4 个等） | 需要 OAuth/cookie | 用户提供凭证后启用 |

---

## 七、如何运行

```bash
# 全部离线测试（CI 默认）
pytest -q

# 指定某一类
pytest -q tests/contract          # 信息源完整性守卫
pytest -q tests/integration       # 端到端链路

# 联网验收（会访问真实站点，需显式开启）
AIDAILY_NETWORK_TESTS=1 pytest -m network -v

# 真实源健康探测（写 docs/HEALTH_REPORT.md）
python scripts/probe_sources.py

# 真实 LLM 渠道探测（0 token）
python scripts/probe_llm_channels.py --keys <keys.json>

# 本地完整链路
python scripts/run_local.py <keys.json> run --from-items data/raw/items.jsonl
```
