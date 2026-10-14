# AIHOT 集成说明

记录**为什么这样接**、**边界在哪**、**改动前必须知道什么**。AIHOT 的数据不是 MIT
许可的，所以这份文件是约束而不是描述。

## 接了什么

| 用途 | 端点 | 方式 |
|---|---|---|
| 信息源（编辑精选） | `https://aihot.news/feed.xml` | RSS，走现有 `RssFetcher` |
| 信息源（全站动态） | `https://aihot.news/feed/all.xml` | 审计阶段已收录（来自 Horizon 的源清单） |
| Tibo 重置监控 | `https://aihot.news/api/v1/codex-resets` | JSON API，`src/aidaily/aihot.py` |

`codex-resets` 提供 45 条事件（2026-06-12 起）、47 条 Tibo 相关动态，每条含中英文
原话与 `x.com` 原文链接。`monitor` 字段是**采集器健康状态**（`status` /
`lastAttemptAt` / `pendingCount`），**不是**页面顶部那四个统计数字——那四个由
`reset_summary()` 从事件流算出，页面明确标注了这一点。

## 使用边界

依据 <https://aihot.news/terms>（v1.1，生效 2026-09-30）与其响应头：

```
x-aihot-policy-version: 1.1
x-aihot-commercial-use: written-authorization-required
x-aihot-contact: wzglyay@virxact.com
cache-control: public, max-age=60, s-maxage=60, stale-while-revalidate=60
```

**允许（免费，甚至不强制署名）**：个人非商业、公益非商业、组织内部使用；
明确允许「必要的缓存和同步」，要求遵循缓存指令、最小轮询间隔、`Retry-After`。

**需要事先书面授权**：对外商业产品、收费服务、客户交付、代理接口、数据转售、
**公开镜像**、白标、**批量公开再分发**，以及把 AIHOT 数据用于对外提供的
模型训练/微调/评测/RAG 产品。

## 因此本项目的做法

**做**：

- 把它当作 81 个源里的**两个**（精选 + 全站），等同阅读器订阅；
- 保留署名与原文/canonical 链接，页面上点得回去（`tibo.html` 有 90 个 x.com 链接）；
- 尊重缓存与限流：ETag / `If-Modified-Since` 复用，本地最小请求间隔 1.1 秒，
  429 时按 `Retry-After` 等待（`MIN_INTERVAL_SECONDS`）；
- 在页面上展示它的策略声明与联系方式（响应头明确要求传递这些信息）；
- 处理撤回：`changes()` 暴露删除项，避免缓存里的条目在来源撤回后继续存活。

**不做**：

- **不调用 `/selected/snapshot`。** 那个接口是为「保留完整本地副本」设计的，
  属于条款里的「批量公开再分发」。本项目只读按主题/时间切分的端点。
- 不伪造 User-Agent 绕过限制（条款第 5 条明令禁止）。JSON API 用文档指定的
  `aihot-api/2.0.0`，Markdown 端点用浏览器 UA 都行，但**不用 UA 规避封锁**。
- 不删改响应里的署名、canonical 或权利信息。
- 不使用 AIHOT 的名称与 Logo 作为本站品牌。

## 两个源为什么要归一个 `dedup_group`

审计源 `rss:aihot-news` 指向 `/feed/all.xml`（最近 7 天公开动态），
增补源 `rss:aihot-news-picks` 指向 `/feed.xml`（编辑精选）。**精选是全站动态的子集**。

实测（2026-10-14 采集）：两个 feed 各 50 条，**URL 交集 2 条**。

不归组的话，这 2 条会以「两个独立来源」的身份进入 L3 事件聚类，直接虚高
`independent_source_count`——而那是本站排序与多源验证最核心的信号。
所以 `sources/overrides.yaml` 里给审计源补了 `dedup_group: aihot`。

## 失败时的行为

`AihotUnavailable` 一律被上层当作「今天没有 AIHOT 数据」：`rerender_site.py` 的
`load_tibo()` 捕获全部异常并让页面回落到显式空状态。**来源挂了不能让日报发不出去**，
但也不能让它悄悄用旧数字冒充当前状态。

## 改动前

1. 先读 <https://aihot.news/terms>，确认它没有变（响应头里的 `X-AIHOT-Policy-Version` 会告诉你）。
2. 如果要把某个端点加进采集，先请求一次确认它存在——`/feed.json` 实测是 **404**，
   写进注册表就会留下一个永远失败的源。
3. 不要为了让数据更全而扩到 `/selected/*`。那是授权问题，不是技术问题。
4. 新增源走 `sources/local.yaml` 并写 `why` 与 `found_in`；直接改
   `sources/registry.yaml` 会在下次重建时被覆盖，且覆盖守卫会报错。
