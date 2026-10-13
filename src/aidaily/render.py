"""Rendering: brief, deep, machine-readable feed, and email HTML.

Every URL written here comes from `Event.all_urls`, which was assembled from our own
records during clustering. The renderer never asks a model for a link and never invents
one -- that is what makes the fact-check in `factcheck.py` pass by construction rather
than by luck.

Source diversity is stated explicitly and honestly: the digest reports how many sources
were collected, how many failed, and how many events rest on a single source, so a reader
can tell a well-corroborated story from a lone report.
"""

from __future__ import annotations

import html as html_mod
import json
import re
from datetime import datetime, timezone

from .analyze import EventInsight
from .models import Digest, Event, NormalizedItem

CATEGORY_LABELS = {
    "lab-official": "官方发布",
    "lab-blog": "实验室博客",
    "zh-media": "中文媒体",
    "media": "科技媒体",
    "paper": "论文与研究",
    "digest": "行业简报",
    "community": "社区讨论",
    "dev": "开发者动态",
    "model": "模型与数据集",
    "product": "产品发布",
    "search": "检索聚合",
    "trend": "趋势信号",
    "preset": "预设源",
    "example": "示例源",
}

_DEFAULT_LABEL = "其它"


def _label(category: str) -> str:
    return CATEGORY_LABELS.get(category, _DEFAULT_LABEL)


def _when(event: Event) -> str:
    if not event.published_range:
        return "时间未知"
    start = event.published_range[0]
    return start.strftime("%Y-%m-%d %H:%M UTC")


def _links(event: Event, limit: int = 8) -> str:
    rows = [f"[{_domain(url)}]({url})" for url in event.all_urls[:limit]]
    extra = len(event.all_urls) - limit
    if extra > 0:
        rows.append(f"另有 {extra} 个来源")
    return " · ".join(rows)


def _domain(url: str) -> str:
    try:
        host = url.split("//", 1)[1].split("/", 1)[0]
    except IndexError:
        return url[:40]
    return host[4:] if host.startswith("www.") else host


def _bullets(rows: list[str], prefix: str = "- ") -> list[str]:
    return [f"{prefix}{row}" for row in rows]


# --- brief ------------------------------------------------------------------------
def render_brief(
    digest: Digest,
    insights: dict[str, EventInsight],
    by_id: dict[str, NormalizedItem],
    *,
    max_items: int = 15,
) -> str:
    """The 15-item version that goes to email and Telegram."""
    lines = [f"# AI 日报 · {digest.date}", ""]
    if digest.headline:
        lines += [f"**{digest.headline}**", ""]

    for idx, event in enumerate(digest.top_events[:max_items], start=1):
        insight = insights.get(event.event_id)
        title = insight.title if insight and insight.title else event.title
        lines.append(f"{idx}. **{title}**")
        if insight:
            first_fact = (insight.facts or insight.key_points or [""])[0]
            if first_fact:
                lines.append(f"   {first_fact}")
        # The label reflects *independent* sources, not raw source ids: two feeds
        # carrying the same content are one source, and labelling that "多源" would
        # overstate corroboration to the reader.
        marker = "多源" if event.independent_source_count > 1 else "单源"
        lines.append(f"   _{marker} · {_when(event)} · {_links(event, 4)}_")
        lines.append("")

    cov = digest.source_coverage
    lines += [
        "---",
        f"来源覆盖：{cov.active}/{cov.total} 个源有内容，{cov.failed} 个失败，{cov.skipped} 个跳过。",
    ]
    if digest.warnings:
        lines += ["", "**本期说明**"] + _bullets(digest.warnings)
    return "\n".join(lines).strip() + "\n"


# --- deep -------------------------------------------------------------------------
def render_deep(
    digest: Digest,
    insights: dict[str, EventInsight],
    by_id: dict[str, NormalizedItem],
    *,
    max_items: int = 60,
) -> str:
    """The full version for GitHub Pages, RSS and n8n."""
    lines = [f"# AI 日报 · {digest.date}", ""]
    if digest.headline:
        lines += [f"> {digest.headline}", ""]

    cov = digest.source_coverage
    lines += [
        f"*生成于 {digest.generated_at.strftime('%Y-%m-%d %H:%M UTC')}　"
        f"窗口 {digest.window_start.strftime('%m-%d %H:%M')} – {digest.window_end.strftime('%m-%d %H:%M')} UTC*",
        "",
        f"**来源覆盖**：{cov.total} 个源中 {cov.active} 个有内容、{cov.failed} 个失败、"
        f"{cov.skipped} 个跳过（未启用或需凭证）。",
        "",
    ]
    if digest.warnings:
        lines += ["**本期说明**"] + _bullets(digest.warnings) + [""]

    if digest.trend_notes:
        lines += ["## 今日趋势", ""] + _bullets(digest.trend_notes) + [""]

    emitted = 0
    # `top_events` is authoritative; `sections` only says where each event belongs. The
    # first version iterated `sections` alone, so a digest whose sections were missing
    # rendered as an empty document -- a silent, total failure of the output stage.
    section_lookup: dict[str, str] = {}
    for category, rows in digest.sections.items():
        for event in rows:
            section_lookup.setdefault(event.event_id, category)

    grouped: dict[str, list[Event]] = {}
    for event in digest.top_events:
        grouped.setdefault(section_lookup.get(event.event_id, "other"), []).append(event)

    for category, events in grouped.items():
        if not events or emitted >= max_items:
            continue
        lines += [f"## {_label(category)}", ""]
        for event in events:
            if emitted >= max_items:
                break
            emitted += 1
            insight = insights.get(event.event_id)
            title = insight.title if insight and insight.title else event.title
            lines.append(f"### {title}")
            evidence = "多源交叉验证" if event.independent_source_count > 1 else "单一来源"
            lines.append(f"*{_when(event)}　来源 {len(event.source_ids)} 个　{evidence}*")
            lines.append("")

            if insight:
                if insight.facts:
                    lines += ["**事实**"] + _bullets(insight.facts) + [""]
                if insight.inferences:
                    lines += ["**推断**"] + _bullets(insight.inferences) + [""]
                if insight.opinions:
                    lines += ["**观点**"] + _bullets(insight.opinions) + [""]
                if insight.uncertainties:
                    lines += ["**不确定**"] + _bullets(insight.uncertainties) + [""]
                if insight.rule_based:
                    lines.append("> 本条为来源原文摘录（未调用大模型）")
                    lines.append("")

            lines += [f"来源：{_links(event)}", ""]

    lines += ["---", "", f"共 {digest.counts.get('events', 0)} 个事件，"
                        f"其中 {digest.counts.get('multi_source_events', 0)} 个为多源交叉验证。"]
    return "\n".join(lines).strip() + "\n"


# --- machine-readable -------------------------------------------------------------
def render_json_feed(
    digest: Digest,
    insights: dict[str, EventInsight],
    *,
    site_url: str,
    feed_path: str = "feed/zh.json",
) -> str:
    """JSON Feed 1.1, matching the shape dailydawn already feeds to n8n.

    One feed item per event, with every source URL inside `content_html`, so a consumer
    gets the corroboration along with the story.
    """
    items = []
    for event in digest.top_events:
        insight = insights.get(event.event_id)
        title = insight.title if insight and insight.title else event.title
        body: list[str] = []
        if insight:
            if insight.facts:
                body.append("<p><strong>事实</strong></p><ul>"
                            + "".join(f"<li>{html_mod.escape(f)}</li>" for f in insight.facts)
                            + "</ul>")
            if insight.inferences:
                body.append("<p><strong>推断</strong></p><ul>"
                            + "".join(f"<li>{html_mod.escape(f)}</li>" for f in insight.inferences)
                            + "</ul>")
            if insight.uncertainties:
                body.append("<p><strong>不确定</strong></p><ul>"
                            + "".join(f"<li>{html_mod.escape(u)}</li>" for u in insight.uncertainties)
                            + "</ul>")
        body.append("<p><strong>来源</strong></p><ul>"
                    + "".join(f'<li><a href="{html_mod.escape(u)}">{html_mod.escape(_domain(u))}</a></li>'
                              for u in event.all_urls)
                    + "</ul>")
        published = event.published_range[0] if event.published_range else digest.generated_at
        items.append({
            "id": f"{digest.date}-{event.event_id}",
            "url": event.all_urls[0] if event.all_urls else site_url,
            "title": title,
            "content_html": "".join(body),
            "date_published": published.isoformat(),
            "tags": sorted({*event.source_ids}),
            "_ai_daily": {
                "event_id": event.event_id,
                "source_ids": event.source_ids,
                "all_urls": event.all_urls,
                "evidence_level": event.evidence_level,
                "confidence": event.confidence,
            },
        })

    payload = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "AI 日报",
        "home_page_url": site_url,
        "feed_url": f"{site_url.rstrip('/')}/{feed_path}",
        "language": "zh-CN",
        "items": items,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_email_html(markdown_body: str, subject: str) -> str:
    """Minimal inline-styled HTML. Inline styles because mail clients ignore <style>."""
    body = html_mod.escape(markdown_body)
    body = re.sub(r"^# (.+)$", r"<h1>\1</h1>", body, flags=re.M)
    body = re.sub(r"^\*\*(.+)\*\*$", r"<p><strong>\1</strong></p>", body, flags=re.M)
    body = re.sub(r"^(\d+)\. (.+)$", r"<p><strong>\1. \2</strong></p>", body, flags=re.M)
    body = body.replace("\n", "<br>\n")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html_mod.escape(subject)}</title></head>"
        "<body style=\"font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',"
        "'Hiragino Sans GB','Microsoft YaHei',sans-serif;font-size:15px;line-height:1.7;"
        "color:#1f2328;max-width:720px;margin:0 auto;padding:16px\">"
        f"{body}</body></html>"
    )
