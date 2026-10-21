import io, json, re, sys
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pathlib import Path
from aidaily.samestory import same_message

juya = [
    "DeepSeek 开源内部推理框架 DeepInfer",
    "ChatGPT 推出锁定聊天，可用 PIN 保护",
    "Codex 改进计划第 15 天，Tibo 送上用量重置",
    "OpenAI 修复约 4 万账户额度错配问题并补偿",
    "OpenAI API 新增 12 小时提示词缓存",
    "Google 开源原生 PyTorch 软件栈 TorchTPU",
    "腾讯元宝搜索对外开放，支持三种接入方式",
    "ElevenLabs 发布两款 Eleven Realtime 实时语音模型",
    "Mistral AI 发布 Voxtral 3 语音模型系列及语音 Agent SDK",
    "OpenAI 为 ChatGPT 引入多人共管的定期任务",
    "Google 为 Gemini 推出小企业主新工具",
    "Google 向安卓车载推出 Gemini 个性化功能",
    "千问 App 推出陪逛功能，共享屏幕语音问商品",
    "马斯克：X 调整时间线推荐的两类模型",
    "Anthropic 研究设计蝎毒结合蛋白，17 个通过结合测试",
    "OpenAI 收购药物开发平台 Orchestra Bio",
    "OpenAI Preparedness 团队前负责人宣布重返 OpenAI",
    "据路透社：OpenAI 洽谈约 300 亿美元融资",
    "Anthropic 上市文件草案披露云容量困境",
    "Google：Argon 用量约为前代同期 3 倍",
]

root = Path(r"D:\Code\AI日报")
d = json.loads((root / "data" / "digests" / "2026-10-21.json").read_text(encoding="utf-8"))
ins = d.get("insights") or {}
mine = [((ins.get(e["event_id"]) or {}).get("title") or e["title"]) for e in d["digest"]["top_events"]]

missing = []
for t in juya:
    if not any(same_message(t, m) for m in mine):
        missing.append(t)

print("  juya 20 条 vs 我的 54 条")
print("  我没有的: %d 条" % len(missing))
for t in missing:
    print("    %s" % t[:66])