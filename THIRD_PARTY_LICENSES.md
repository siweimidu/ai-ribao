# 第三方依赖许可证

本项目以 MIT 发布。运行时依赖全部为宽松许可（MIT / BSD / Apache-2.0），
**不包含任何 copyleft 依赖**——这是刻意的，因为 GPL 系依赖会与本项目的 MIT 许可冲突。

| 依赖 | 用途 | 许可证 |
|---|---|---|
| httpx | HTTP 客户端 | BSD-3-Clause |
| feedparser | RSS / Atom 解析 | BSD-2-Clause |
| pydantic | 数据模型与校验 | MIT |
| PyYAML | 配置与注册表读写 | MIT |
| tenacity | 退避重试（预留） | Apache-2.0 |
| beautifulsoup4 | HTML 解析（`fetchers` 可选） | MIT |
| lxml | BeautifulSoup 的解析后端（`fetchers` 可选） | BSD-3-Clause |
| trafilatura | 正文抽取（`fetchers` 可选，尚未接入） | Apache-2.0 |
| openai | 兼容客户端（`llm` 可选，实际走 httpx，仅备用） | Apache-2.0 |
| pytest / pytest-cov | 测试（`dev` 可选） | MIT |

## 检查方法

```bash
pip install -e ".[fetchers,llm,dev]"
pip install pip-licenses
pip-licenses --format=markdown --with-urls
```

**新增依赖前的检查清单**：

1. 许可证是否为 MIT / BSD / Apache-2.0 / ISC？（GPL、AGPL、SSPL 一律拒绝）
2. 是否可离线运行？（CI 不联网跑测试，依赖必须可安装）
3. 是否引入了对常驻进程或系统级组件的强依赖？（本项目的目标之一是零服务器）

## 数据源不是依赖

`sources/registry.yaml` 中的 80 个信息源是**数据**，不是代码依赖。它们各自的
服务条款、robots 策略与内容许可由各自站点决定，本项目只做抓取与回链，不复制全文入库
（正文全文仅保留 30 天滚动窗口用于当次分析）。使用前请自行确认各源的服务条款。
