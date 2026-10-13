# LLM 渠道可用性实测报告

探测时间：2026-10-13T16:30:41.513662+00:00
总 HTTP 请求：**157**　消耗 token：**0**　未识别端点而跳过：0

> 方法：用 `GET {base}/models` 判断 key 是否可用 —— **列模型不消耗 token**。
> 对话回退仅在 `--deep` 时启用且 `max_tokens=1`。
> 密钥不落盘、不打印；每个渠道用 key 的 SHA-256 前 8 位标识。

## 结论分布

| 判定 | 数量 | 含义 |
|---|---|---|
| ok | 123 | 200 且列出模型 —— **可直接用** |
| ok_no_models | 3 | 200 但模型列表为空 |
| ok_chat | 0 | /models 不可用，但对话可用（--deep） |
| unauthorized | 9 | key 被拒（401/403） |
| no_models_route | 4 | 无 /models 路由，未深测 |
| rate_limited | 2 | 429 |
| error | 4 | 其它 HTTP 错误 |
| unreachable | 7 | DNS/TLS/超时 |
| bad_payload | 5 | 200 但响应不是 JSON |

## ✅ 可用渠道

| 渠道 | 端点 | 模型数 | 延迟 | 示例模型 |
|---|---|---|---|---|
| 99code | https://gpt.api456.me/v1 | 6 | 2046ms | gpt-5.3-codex, gpt-5.4, gpt-5.5 |
| agnes / Agnes国际 | https://apihub.agnes-ai.com/v1 | 9 | 2781ms | agnes-2.5-pro-alpha, agnes-video-2.5-flash, agnes-3.0-flash |
| Agnes中国 | https://api.agnes-ai.cn/v1 | 9 | 1985ms | agnes-2.5-flash, agnes-2.5-pro, agnes-2.5-pro-alpha |
| ainative | https://api.ainative.studio/v1 | 86 | 2953ms | arcee-trinity-large-thinking, claude-3-sonnet, claude-opus-4 |
| aion | https://api.aionlabs.ai/v1 | 6 | 2983ms | aion-labs/aion-2.0, aion-labs/aion-3.0, aion-labs/aion-3.0-mini |
| bazaarlink | https://api.bazaarlink.ai/v1 | 123 | 4171ms | qwen3.8-max, deepseek-v4-flash, glm-5v-turbo |
| Blue | https://api.bluesminds.com/v1 | 37 | 1312ms | nvidia/ising-calibration-1.5-31b, nemotron-3.5-lightning, nvidia/nemot |
| cerebras | https://api.cerebras.ai/v1 | 2 | 2812ms | qwen-3.8-27b, gpt-oss-120b |
| Codex | https://new.sharedchat.cc/codex | 10 | 1250ms | codex-auto-review, gpt-5.4, gpt-5.4-mini |
| CSDN | https://api-ai.gitcode.com/v1 | 8 | 3828ms | deepseek-ai/DeepSeek-V4-Flash, Qwen/Qwen2.5-VL-72B, Qwen/Qwen3-30B-A3B |
| Custom | https://api.apichatgpt.top/v1 | 13 | 1234ms | claude-fable-5, claude-fable-5-1, claude-opus-4-6 |
| Custom | https://freetokenfaucet.com/v1 | 3 | 4171ms | gpt-5.6-sol, gpt-5.6-terra, MiniMax-H3 |
| Custom | https://api456.me/v1 | 29 | 2014ms | 3super测试, claude-opus-4-5, claude-opus-4-6 |
| Custom | https://api.univibe.cc/openai/v1 | 24 | 1515ms | claude-sonnet-5-5, claude-sonnet-5, claude-opus-5-5 |
| Custom | https://helpcoder.cc/v1 | 11 | 1922ms | gpt-5, gpt-5-codex, gpt-5-codex-mini |
| Custom | https://api.longcat.chat/openai/v1 | 2 | 1594ms | LongCat-2.5-Preview, LongCat-2.0 |
| Custom | https://api.ai-router.dev | 15 | 5531ms | gpt-5.4, gpt-5.4-mini, gpt-5.5 |
| Custom | https://api.omaleai.qzz.io/v1 | 139 | 1844ms | DeepSeek-V4-Flash, DeepSeek-V4.1-Flash, MiMo-V2.6-Flash |
| Custom | https://free-llm.cups.moe/v1 | 24 | 1171ms | DeepSeek-Prover-V2, DeepSeek-R1, DeepSeek-V3 |
| Custom | https://api.p0.systems/api/agents/v1 | 6 | 1657ms | mimo-v2.5, cohere-north-mini-code, ling-3.0-flash |
| Custom | https://api.longcat.chat/openai | 2 | 1781ms | LongCat-2.5-Preview, LongCat-2.0 |
| Custom | https://api.sambanova.ai/v1 | 6 | 1093ms | DeepSeek-V3.1, DeepSeek-V3.2, Meta-Llama-3.3-70B-Instruct |
| Custom | https://api.hcnsec.cn/v1 | 21 | 672ms | auto, DeepSeek-V4-Flash, DeepSeek-V4-Pro |
| Custom | https://api.hcnsec.cn/v1 | 21 | 2062ms | auto, DeepSeek-V4-Flash, DeepSeek-V4-Pro |
| Custom | https://api.hcnsec.cn/v1 | 21 | 2046ms | auto, DeepSeek-V4-Flash, DeepSeek-V4-Pro |
| Custom | https://api.hcnsec.cn/v1 | 21 | 3375ms | auto, DeepSeek-V4-Flash, DeepSeek-V4-Pro |
| Custom | https://api.hcnsec.cn/v1 | 21 | 1344ms | auto, DeepSeek-V4-Flash, DeepSeek-V4-Pro |
| Custom | https://api.langlangy.cn/v1 | 14 | 3844ms | gpt-6-astra, gpt-5.6-sol, gpt-5.6-terra |
| Custom | https://zenmux.ai/api/v1 | 207 | 2250ms | inclusionai/llada-image, google/gemini-4-argon, meta/muse-wonder-1.0 |
| Custom | https://open.bigmodel.cn/api/paas/v4 | 11 | 640ms | glm-4.5, glm-4.5-air, glm-4.6 |
| Custom | https://developer.amd.com.cn/radeon/api/v1 | 12 | 1969ms | DeepSeek-V4.1-Flash, DeepSeek-V4-Flash, DeepSeek-V4-Flash-Vision-Exp |
| Custom | https://api.b.ai/v1 | 60 | 1437ms | minimax-m3, minimax-m2.7, glm-5.1 |
| Custom | https://www.hiapi.ai/v1 | 113 | 2327ms | grok-4.6, seedance-2.0-fast, grok-imagine/text-to-video |
| Custom | https://gen.pollinations.ai | 146 | 5467ms | openai/gpt-5.4-nano, inclusionai/ling-3.1-flash, jaredpalmer/kev-4b |
| Custom | https://api.poixe.com/v1 | 177 | 3780ms | grok-3-mini, grok-4.3, grok-3 |
| Custom | https://factory.pub/v1 | 9 | 2422ms | grok-4.6, gpt-image-2, gpt-6-luna |
| Custom | https://aihubmix.com/v1 | 38 | 1750ms | ling-3.0-flash-free, coding-glm-5.2-free, coding-kimi-k3-free |
| Custom | https://api.airforce/v1 | 657 | 1655ms | open-mistral-nemo-2407, mistral-large-2512, rnj-1 |
| Custom | https://oneapi.zaiwenai.com/v1 | 58 | 2483ms | minimax-h3-2k, minimax-h3-768p, minimax-m3.1-flash-preview |
| Custom | https://api.teamorouter.com/v1 | 47 | 687ms | claude-fable-5, claude-fable-5-1, claude-haiku-4-5 |
| Custom | https://api.cerebras.ai/v1 | 2 | 1750ms | qwen-3.8-27b, gpt-oss-120b |
| Custom | https://api.hcnsec.cn/v1 | 21 | 3453ms | auto, DeepSeek-V4-Flash, DeepSeek-V4-Pro |
| Custom | https://note3-prev-api.askdiandian.com/v1 | 1 | 8187ms | dots3-note-prev |
| Custom | https://api.xkiro.com/v1 | 129 | 1108ms | google/gemini-3.6-flash, openai/gpt-6.1-sol, x-ai/grok-4.5 |
| Custom | https://api.orcarouter.ai/v1 | 208 | 2062ms | orcarouter/free, orcarouter/fusion, orcarouter/fusion-flash |
| Custom | https://chuan.sylu.cc/v1 | 2 | 1203ms | claude-fable-5.1, dots-3-note |
| Custom | https://api.ipc.wiki | 4 | 921ms | deepseek-v4-flash-0731, deepseek-v4-flash-vision-exp, deepseek-v4-pro- |
| Custom | https://api.siliconflow.cn/v1 | 98 | 1796ms | zai-org/GLM-5.3-Flash, tencent/Hy4-preview, zai-org/GLM-5.3 |
| Custom | https://open.bigmodel.cn/api/paas/v4 | 11 | 1125ms | glm-4.5, glm-4.5-air, glm-4.6 |
| Custom | https://tokenrhythm.studio/v1 | 25 | 1969ms | glm-5.1, minimax-m2.7, kimi-k2.6 |
| Custom | https://ai.hebox.net/v1 | 47 | 1781ms | Agents-A1, Atria-Dawn-Preview, SAI-Coder |
| Custom | https://ai.hebox.net/v1 | 47 | 3031ms | Agents-A1, Atria-Dawn-Preview, SAI-Coder |
| Custom | https://cli.999554.xyz/v1 | 2 | 1467ms | 模型大抽奖, DeepSeek-Flash[free] |
| Custom | https://api.jucodex.com/v1 | 9 | 1016ms | codex-auto-review, gpt-5.5, gpt-5.6-luna |
| Custom | https://ai.121628.xyz/v1 | 52 | 1702ms | deepseek-v4-flash-free, deepseek-v4-pro-free, deepseek-v4.1-flash-free |
| Custom | https://ai.121628.xyz/v1 | 11 | 1187ms | glm-4-9b-free, glm-5.2-free, glm-z1-9b-free |
| Custom | https://ai.121628.xyz/v1 | 42 | 1421ms | deepseek-v4-flash-free, deepseek-v4-pro-free, deepseek-v4.1-flash-free |
| Custom | https://pq.678691.xyz/v1 | 11 | 2108ms | deepseek-v4-flash, deepseek-v4-flash-0731, GcmodAi |
| Custom | https://free.v36.cm/v1 | 6 | 1672ms | gpt-3.5-turbo, gpt-3.5-turbo-16k, gpt-4o-mini |
| Custom | https://ai.gpt666claude.top/v1 | 8 | 1467ms | agnes-2.0-flash, agnes-image-2.0-flash, minimax-m3 |
| Custom | https://api.hcnsec.cn/v1 | 21 | 2969ms | auto, DeepSeek-V4-Flash, DeepSeek-V4-Pro |
| Custom | https://api.b.ai/v1 | 60 | 828ms | minimax-m3, minimax-m2.7, glm-5.1 |
| Custom | https://mzsjai.com/v1 | 52 | 953ms | qwen/qwen3.5-397b-a17b, doubao/seedream-4.5, doubao/seedance-2.0-fast |
| Custom | https://api.tokenrouter.com/v1 | 2 | 2327ms | z-ai/glm-5.3-free, nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free |
| Custom | https://infistar.cc/v1 | 237 | 5000ms | gpt-6.1-sol, gpt-6-astra, gpt-6-sol |
| Custom | https://api.justwoker.icu/v1 | 1 | 2405ms | claude-opus-4-8 |
| Custom | https://ai.xmiaom.com/v1 | 47 | 2391ms | chatgpt-voice, claude-sonnet-5, claude-sonnet-5.5 |
| Custom | https://kuaipao.ai/v1 | 7 | 1016ms | codex-auto-review, gpt-5.5, gpt-5.6-sol |
| Custom | https://newapi.yiciyuang.com/v1 | 84 | 2546ms | gpt-5-1, gpt-5-5, seedance-2.5-doubao-720p |
| Custom | https://newapi.yiciyuang.com/v1 | 84 | 1015ms | gpt-5-1, gpt-5-5, seedance-2.5-doubao-720p |
| Custom | https://router.flatkey.ai/v1 | 90 | 1687ms | claude-fable-5, claude-fable-5.1, claude-haiku-4-5 |
| Custom | https://inference.dahl.global/v1 | 3 | 2342ms | MiniMaxAI/MiniMax-M2.7, zai-org/GLM-5.3-Flash, deepseek-ai/DeepSeek-V4 |
| Custom | https://api.visionary.beer/v1 | 9 | 2234ms | nano-banana-2.1, gpt-image-2, gpt-image-2.5-flare |
| Custom | https://tu.go2api.cc/v1 | 7 | 1812ms | gpt-image-2.5, gpt-image-2, seedance2.0-pro |
| DoCode | https://docode.cc/v1 | 9 | 1078ms | grok-4.6, gpt-6-sol, gpt-6-astra |
| dxnt | https://www.dxnt.com | 28 | 3905ms | deepseek-v4-pro, gpt-5.6-luna, hy3 |
| Google / google | https://generativelanguage.googleapis.com/v1beta/ope | 63 | 2968ms | models/gemini-2.5-flash, models/gemini-2.5-pro, models/gemini-2.5-flas |
| groq | https://api.groq.com/openai/v1 | 11 | 2344ms | canopylabs/orpheus-arabic-saudi, whisper-large-v3, openai/gpt-oss-safe |
| Groq-翻墙 | https://api.groq.com/openai/v1 | 11 | 3016ms | canopylabs/orpheus-v1-english, meta-llama/llama-prompt-guard-2-86m, op |
| HubWay | https://hubway.cc | 8 | 2233ms | codex-auto-review, gpt-5.5, gpt-5.6-sol |
| huggingface | https://router.huggingface.co/v1 | 121 | 1219ms | Qwen/Qwen3.8-27B, deepseek-ai/DeepSeek-V4.1-Flash, zai-org/GLM-5.3-Fla |
| KIMI | https://api.moonshot.cn/v1 | 4 | 3092ms | kimi-k2.6, kimi-k3, kimi-k2.7-code |
| llm7 | https://api.llm7.io/v1 | 65 | 1344ms | DeepSeek-V4-Flash-0731, DeepSeek-V4.1-Flash, GLM-5.3-Flash |
| MiniMax | https://api.minimaxi.com/v1 | 8 | 3390ms | MiniMax-M3, MiniMax-M2.7, MiniMax-M2.7-highspeed |
| mistral | https://api.mistral.ai/v1 | 46 | 1828ms | codestral-2508, codestral-latest, mistral-code-latest |
| navy | https://api.navy/v1 | 142 | 1547ms | schizogpt, gpt-6-astra, gpt-6-sol |
| nvidia | https://integrate.api.nvidia.com/v1 | 80 | 2046ms | 01-ai/yi-large, adept/fuyu-8b, ai21labs/jamba-1.5-large-instruct |
| ollama | https://ollama.com/v1 | 18 | 780ms | glm-5.3-flash, gpt-oss:120b, mistral-large-3:675b |
| openclawcn | https://api.openclawcn.net/v1 | 2 | 1796ms | gpt-6-luna, Qwen3.8-flash |
| OpenCode / opencode | https://opencode.ai/zen/v1 | 84 | 1046ms | big-pickle, ling-3.1-flash-free, cat-jam-free |
| openrouter | https://openrouter.ai/api/v1 | 462 | 2593ms | google/gemini-4-argon, scaledown/summarize, scaledown/extract |
| pollinations | https://text.pollinations.ai/openai | 1 | 1671ms | openai-fast |
| requesty | https://router.requesty.ai/v1 | 784 | 5078ms | vertex/gemini-4-argon, vertex/gemini-4-argon@eu, meta/muse-spark-1.3 |
| routeway | https://api.routeway.ai/v1 | 290 | 2015ms | gpt-6.1-sol, claude-haiku-5.5, claude-sonnet-5.5 |
| sealion | https://api.sea-lion.ai/v1 | 11 | 3578ms | aisingapore/Llama-SEA-LION-v3-70B-IT, aisingapore/SEA-Guard, aisingapo |
| SoulEcho AI 发电站⚡️ | https://ai.soulecho.cc/v1 | 16 | 969ms | gpt-5.5, gpt-5.4, codex-auto-review |
| zhipu | https://open.bigmodel.cn/api/paas/v4 | 11 | 952ms | glm-4.5, glm-4.5-air, glm-4.6 |
| 七亿 | https://api-ai.7e.ink/v1 | 5 | 2483ms | qwen3.5-4, deepseek-r1-7, glm5-bd |
| 七亿 | https://api-ai.7e.ink/v1 | 5 | 687ms | qwen3.5-4, deepseek-r1-7, glm5-bd |
| 元衡 | https://cn.meta-api.vip/v1 | 13 | 2234ms | claude-fable-5, claude-fable-5-1, claude-haiku-4-5-20251001 |
| 向量引擎 | https://api.vectorengine.ai/v1 | 534 | 2328ms | qwen-coder-turbo-latest, BAAI/bge-reranker-v2-m3, qwen-max-1201 |
| 哈基米API | https://api.gemai.cc/v1 | 306 | 1577ms | [CodeA]gemini-3.1-pro-preview, [CodeB]gemini-3.1-pro-preview, [premium |
| 商汤 | https://token.sensenova.cn/v1 | 7 | 2015ms | deepseek-v4-flash, glm-5.2, sensenova-6.8-flash-lite |
| 基元律动 | https://tokenrhythm.studio/v1 | 25 | 4046ms | glm-5.1, minimax-m2.7, kimi-k2.6 |
| 新疆5 | https://api.hcnsec.cn/v1 | 21 | 3891ms | auto, DeepSeek-V4-Flash, DeepSeek-V4-Pro |
| 新疆6 | https://api.hcnsec.cn/v1 | 21 | 1843ms | auto, DeepSeek-V4-Flash, DeepSeek-V4-Pro |
| 新疆幻城网安-超多余额 | https://api.hcnsec.cn/v1 | 21 | 3171ms | auto, DeepSeek-V4-Flash, DeepSeek-V4-Pro |
| 新疆幻城网安-超多余额2 | https://api.hcnsec.cn/v1 | 21 | 3030ms | auto, DeepSeek-V4-Flash, DeepSeek-V4-Pro |
| 新疆幻城网安-超多余额3 | https://api.hcnsec.cn/v1 | 21 | 2234ms | auto, DeepSeek-V4-Flash, DeepSeek-V4-Pro |
| 新疆幻城网安-超多余额4 | https://api.hcnsec.cn/v1 | 21 | 3733ms | auto, DeepSeek-V4-Flash, DeepSeek-V4-Pro |
| 梭子蟹 API | https://suoxie.codes | 12 | 2016ms | gpt-5.5, codex-auto-review, gpt-image-2 |
| 火山方舟-day-200w | https://ark.cn-beijing.volces.com/api/v3 | 135 | 1062ms | doubao-lite-128k-240428, doubao-pro-128k-240515, doubao-lite-4k-240328 |
| 熊猫 | https://api520.pro/v1 | 130 | 2516ms | gpt-5.5, gpt-5.6-sol, gpt-5.6-terra |
| 玖时 | https://api.jiushi.xin/v1 | 129 | 1452ms | [AG-特惠]claude-opus-4-6, [AG-特惠]claude-opus-4-6-thinking, [AG]gemini-3. |
| 空悲切 | https://xn--vduyey89e.com/v1 | 189 | 1828ms | gpt-5.5, gpt-5.6-sol, gpt-5.6-terra |
| 肖恩AI中转站 | https://api.supxh.xin | 6 | 2015ms | gemini-3-flash, gemini-2.5-pro, gemini-3.1-pro |
| 芙卡卡 | https://api.fuka.win/v1 | 63 | 3469ms | [奇异果]claude-4.6-opus-thinking㉗, [奇异果]claude-5-opus㉗, [孤生竹]claude-4.5-o |
| 蚂蚁百灵 | https://api.ant-ling.com/v1 | 10 | 671ms | AntAngelMed, Ling-2.6-1T, Ling-2.6-flash |
| 蚂蚁百灵 | https://api.ant-ling.com/anthropic/v1 | 10 | 3157ms | AntAngelMed, Ling-2.6-1T, Ling-2.6-flash |
| 阶跃星辰 | https://api.stepfun.com/v1 | 33 | 3000ms | step-tts-mini, step-asr, step-1o-turbo-vision |
| 阿里云百炼100W | https://dashscope.aliyuncs.com/compatible-mode/v1 | 176 | 1125ms | cmaas-qwen3.8-flash, qwen-image-2.1-pro, qwen3.8-omni-flash-realtime |
| 阿里云百炼100W | https://llm-1ngh9ld93l3774o1.cn-beijing.maas.aliyunc | 176 | 984ms | cmaas-qwen3.8-flash, qwen-image-2.1-pro, qwen3.8-omni-flash-realtime |
| 魔塔社区 / modelscope | https://api-inference.modelscope.cn/v1 | 36 | 3562ms | deepseek-ai/DeepSeek-V4-Flash-0731, deepseek-ai/DeepSeek-V4-Pro, deeps |

## 🔑 key 被拒（9）

| 渠道 | 端点 | 状态 | 详情 |
|---|---|---|---|
| Custom | https://vsllm.com/v1 | 403 | HTTP 403: key rejected |
| Custom | https://token.openstarry.com/v1 | 403 | HTTP 403: key rejected |
| Custom | https://api.apikey.fun | 403 | HTTP 403: key rejected |
| Custom | https://ai.kscsnkli.site/v1 | 401 | HTTP 401: key rejected |
| Custom | https://api2.kscsnkli.site/v1 | 401 | HTTP 401: key rejected |
| Custom | https://api.axis.fan/v1 | 403 | HTTP 403: key rejected |
| reka | https://api.reka.ai/v1 | 403 | HTTP 403: key rejected |
| siliconflow | https://api.siliconflow.cn/v1 | 401 | HTTP 401: key rejected |
| 毛利 | https://openkun.xyz/v1 | 403 | HTTP 403: key rejected |

## ❌ 不可达（7）

| 渠道 | 端点 | 状态 | 详情 |
|---|---|---|---|
| AUQA公益AI | https://api.ltzy.top/v1 | - | ConnectTimeout:  |
| Beizhi | https://beizhi.sylu.cc/v1 | - | ReadTimeout:  |
| Custom | https://open.bigmodel.cn/api/paas/v4 | - | ConnectError:  |
| Custom | https://tokendance.space/gateway/v1 | - | ConnectTimeout:  |
| Custom | https://api.bababas.ccwu.cc/v1 | - | ReadTimeout:  |
| Custom | https://toapis.xyz/v1 | - | ConnectError:  |
| nara | https://api.nara.ai/v1 | - | ConnectError:  |

## ❔ 无 /models 路由（4）

| 渠道 | 端点 | 状态 | 详情 |
|---|---|---|---|
| Custom | https://api.v0.dev/v1 | 404 | HTTP 404: /models not exposed |
| Custom | https://docs.yizhinengai.com/v1 | 404 | HTTP 404: /models not exposed |
| Custom | https://czapi.top/v1 | 404 | HTTP 404: /models not exposed |
| QverisAI | https://qveris.ai/api/v1 | 404 | HTTP 404: /models not exposed |

## ⏳ 限流（2）

| 渠道 | 端点 | 状态 | 详情 |
|---|---|---|---|
| cohere | https://api.cohere.com/v1 | 429 | HTTP 429 |
| Custom | https://api.cohere.com/v1 | 429 | HTTP 429 |

## ⚠️ 其它错误（4）

| 渠道 | 端点 | 状态 | 详情 |
|---|---|---|---|
| cloudflare | https://api.cloudflare.com/client/v4/accounts/99d759 | 405 | HTTP 405 Method Not Allowed |
| Custom | https://gorouter.app/v1 | 502 | HTTP 502 Bad Gateway |
| Custom | https://tabitoken.com/v1 | 500 | HTTP 500 Internal Server Error |
| momo | http://api.momo.xhihi.art/v1 | 502 | HTTP 502 Bad Gateway |
