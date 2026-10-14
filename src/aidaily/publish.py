"""Delivery: five independent channels, none of which may break the others.

Each channel is attempted in isolation and reports its own outcome. A failed Telegram
push must not stop the email, and a failed email must not stop the RSS feed being
written -- the run's job is to publish what it can and say plainly what it could not.

`already_done` carries the channels a previous partial run completed, so a retry sends
only what is missing. Re-sending an email is worse than not sending it: the reader has no
way to tell a duplicate from a correction.
"""

from __future__ import annotations

import asyncio
import html as html_mod
import json
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.header import Header
from email.mime.text import MIMEText
from pathlib import Path
from typing import Mapping

import httpx

from .analyze import EventInsight
from .config import AppConfig
from .models import Digest, Event
from .render import build_item_html, feed_summary, render_email_html
from .render import _domain

CHANNELS = ("rss", "pages", "email", "telegram", "n8n")


@dataclass
class DeliveryResult:
    channel: str
    ok: bool
    detail: str = ""
    skipped: bool = False


@dataclass
class DeliveryReport:
    results: list[DeliveryResult] = field(default_factory=list)

    @property
    def channels(self) -> dict[str, str]:
        # `skipped` is tested FIRST. A skipped channel carries ok=True (it is not a
        # failure), so checking `ok` first recorded "未配置凭证，已跳过" as "ok" in the
        # ledger -- and a later run with credentials would then believe the mail had
        # already gone out and never send it.
        return {
            r.channel: ("skipped" if r.skipped else "ok" if r.ok else "failed")
            for r in self.results
        }

    @property
    def all_ok(self) -> bool:
        return all(r.ok or r.skipped for r in self.results)

    def summary(self) -> dict[str, object]:
        return {
            "all_ok": self.all_ok,
            "channels": self.channels,
            "failures": [{"channel": r.channel, "detail": r.detail} for r in self.results if not r.ok and not r.skipped],
        }


def _xml_escape(text: str) -> str:
    return html_mod.escape(text or "", quote=True)


def write_rss(
    digest: Digest,
    out_dir: Path,
    *,
    site_url: str,
    insights: dict[str, EventInsight] | None = None,
) -> DeliveryResult:
    """An RSS 2.0 feed alongside the JSON Feed, for readers that only speak RSS.

    The first version carried a `<description>` holding nothing but a list of URLs, so a
    consumer got a headline and some links -- while the JSON feed carried the facts,
    inferences and evidence level for the same items. This is the format n8n reaches for
    first, so the two are now built from one shared body and differ only in envelope.

    What was added and why each matters to a machine consumer:

    * `content:encoded` -- the full item body. The RSS spec's `<description>` is limited to
      500 characters of escaped HTML in practice, and readers that truncate it lose the
      facts entirely.
    * `atom:link rel="self"` -- lets a poller detect a moved or redirected feed instead of
      silently reading a stale cache.
    * `ttl` and `generator` -- the feed changes once a day; telling an aggregator that
      avoids needless polling, which the upstream sources' terms ask for.
    * `<source>` per item -- the originating feed's name and URL, which is how attribution
      survives aggregation.
    * `dc:date` for the machine-readable timestamp, because `pubDate` is RFC-822 and
      notoriously ambiguous about time zones.
    """
    insights = insights or {}
    items = []
    for event in digest.top_events:
        insight = insights.get(event.event_id)
        title = (insight.title if insight and insight.title else event.title) or event.title
        when = (
            event.published_range[0].strftime("%a, %d %b %Y %H:%M:%S +0000")
            if event.published_range else ""
        )
        iso = (
            event.published_range[0].astimezone(timezone.utc).isoformat()
            if event.published_range else digest.generated_at.astimezone(timezone.utc).isoformat()
        )
        body = _feed_item_html(event, insight, site_url)
        summary = _feed_summary(event, insight)
        first_url = event.all_urls[0] if event.all_urls else site_url

        # One `<category>` per source rather than a comma-joined blob: RSS says a category
        # element is a single category, and consumers filter on them.
        categories = "".join(
            f"<category>{_xml_escape(s)}</category>" for s in sorted(set(event.source_ids))
        )
        items.append(
            "<item>"
            f"<title>{_xml_escape(title)}</title>"
            f"<link>{_xml_escape(first_url)}</link>"
            f'<guid isPermaLink="false">{_xml_escape(digest.date)}-{_xml_escape(event.event_id)}</guid>'
            f"<pubDate>{when}</pubDate>"
            f"<dc:date>{_xml_escape(iso)}</dc:date>"
            f"<description>{_xml_escape(summary)}</description>"
            f'<content:encoded><![CDATA[{body}]]></content:encoded>'
            f"{categories}"
            f'<source url="{_xml_escape(first_url)}">{_xml_escape(_domain(first_url))}</source>'
            "</item>"
        )

    self_url = f"{site_url.rstrip('/')}/feed/zh.xml"
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" '
        'xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<channel>"
        "<title>AI 日报</title>"
        f"<link>{_xml_escape(site_url)}</link>"
        "<language>zh-cn</language>"
        f'<atom:link href="{_xml_escape(self_url)}" rel="self" type="application/rss+xml"/>'
        f"<lastBuildDate>{digest.generated_at.astimezone(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>"
        "<description>每日 AI 资讯聚合，去重、交叉验证，区分事实与推断</description>"
        # The digest is published once a day; 720 minutes tells aggregators not to poll more
        # often than that, which is what the upstream sources' terms ask of consumers.
        "<ttl>720</ttl>"
        "<generator>ai-ribao</generator>"
        f"{''.join(items)}</channel></rss>\n"
    )
    # Written into `site/` because that is the directory Pages deploys. It used to go to
    # `digests/feed/`, which meant the feed was built correctly and never published: the
    # pages linked `feed/zh.xml` and the URL 404'd. RSS is the n8n hand-off, so a feed
    # that exists but is not served is the same as no feed.
    target = out_dir / "site" / "feed" / "zh.xml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(xml, encoding="utf-8")
    return DeliveryResult("rss", True, f"{target.name}: {len(items)} items")


def _feed_item_html(event: Event, insight: EventInsight | None, site_url: str) -> str:
    """RSS and JSON Feed must carry the same body; `render.build_item_html` builds it.

    Re-exported through this module so the RSS writer has one obvious source of truth. The
    two formats previously diverged -- the JSON feed had the facts and the RSS had a list of
    URLs -- and keeping a second copy here is how that happened.
    """
    return build_item_html(event, insight, site_url)


def _feed_summary(event: Event, insight: EventInsight | None) -> str:
    return feed_summary(event, insight)

def write_site(
    digest: Digest,
    deep_md: str,
    out_dir: Path,
    *,
    site_url: str,
    insights: dict[str, object] | None = None,
    items_by_id: dict[str, object] | None = None,
    tibo: dict | None = None,
    sources: list[dict] | None = None,
) -> DeliveryResult:
    """Render the designed site (see aidaily/site.py), keeping the markdown alongside.

    The markdown is also written into `site/` because the sidebar links both editions as
    downloads and the deploy uploads only `site/`. Writing it to the parent directory left
    the download buttons pointing at 404s — the same failure class as the feeds, caught
    this time by the link guard instead of by a reader.
    """
    from .site import write_site as render_site

    assets = Path(__file__).resolve().parents[2] / "site" / "assets"
    manifest = render_site(
        digest,
        insights or {},
        items_by_id or {},
        out_dir,
        site_url=site_url,
        assets_dir=assets,
        tibo=tibo,
        sources=sources,
    )

    site = out_dir / "site"
    (site / f"{digest.date}.md").write_text(deep_md, encoding="utf-8")
    brief = out_dir / f"{digest.date}.brief.md"
    if brief.exists():
        (site / brief.name).write_bytes(brief.read_bytes())

    return DeliveryResult(
        "pages",
        True,
        f"{manifest['pages']} 期归档 · 当日 {manifest['bytes'] // 1024} KB · "
        f"{len(manifest['assets'])} 个资源",
    )


def _send_email_sync(env: Mapping[str, str], subject: str, html_body: str, text_body: str) -> str:
    host = env["SMTP_HOST"]
    port = int(env.get("SMTP_PORT") or 465)
    user = env.get("SMTP_USERNAME") or env.get("MAIL_FROM_EMAIL") or ""
    password = env["SMTP_PASSWORD"]
    recipients = [r.strip() for r in (env.get("MAIL_TO") or "").split(",") if r.strip()]
    sender = env.get("MAIL_FROM_EMAIL") or user
    if not recipients:
        raise RuntimeError("MAIL_TO is empty")

    message = MIMEText(text_body, "plain", "utf-8")
    message["Subject"] = Header(subject, "utf-8")
    message["From"] = sender
    message["To"] = ", ".join(recipients)

    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(user, password)
            smtp.sendmail(sender, recipients, message.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(user, password)
            smtp.sendmail(sender, recipients, message.as_string())
    return f"sent to {len(recipients)} recipient(s)"


async def deliver_all(
    digest: Digest,
    brief_md: str,
    deep_md: str,
    cfg: AppConfig,
    env: Mapping[str, str],
    out_dir: Path,
    *,
    site_url: str,
    already_done: Mapping[str, str] | None = None,
    insights: dict[str, object] | None = None,
    items_by_id: dict[str, object] | None = None,
    tibo: dict | None = None,
    sources: list[dict] | None = None,
) -> DeliveryReport:
    """Attempt every enabled channel, independently."""
    done = set((already_done or {}).keys())
    report = DeliveryReport()

    def record(result: DeliveryResult) -> None:
        report.results.append(result)

    # --- local artefacts first: they always succeed and other channels link to them ---
    if cfg.delivery.rss:
        try:
            record(write_rss(digest, out_dir, site_url=site_url, insights=insights))
        except Exception as exc:  # noqa: BLE001
            record(DeliveryResult("rss", False, f"{type(exc).__name__}: {exc}"[:200]))

    if cfg.delivery.pages:
        try:
            record(
                write_site(
                    digest, deep_md, out_dir, site_url=site_url,
                    insights=insights, items_by_id=items_by_id, tibo=tibo, sources=sources,
                )
            )
        except Exception as exc:  # noqa: BLE001
            record(DeliveryResult("pages", False, f"{type(exc).__name__}: {exc}"[:200]))

    async with httpx.AsyncClient(timeout=30) as http:
        # --- email -----------------------------------------------------------------
        # A channel that is enabled in config but has no credentials is a *deployment
        # state*, not a runtime failure: a fresh clone would otherwise never go green.
        # It is reported as skipped and surfaced in the run summary instead of silently
        # pretending the mail went out.
        if not cfg.delivery.email:
            record(DeliveryResult("email", True, "disabled in config", skipped=True))
        elif "email" in done:
            record(DeliveryResult("email", True, "already sent in a previous attempt", skipped=True))
        elif not (env.get("SMTP_HOST") and env.get("SMTP_PASSWORD") and env.get("MAIL_TO")):
            record(DeliveryResult("email", True, "未配置 SMTP 凭证，已跳过", skipped=True))
        else:
            try:
                subject = f"AI 日报 {digest.date}"
                html_body = render_email_html(brief_md, subject)
                detail = await asyncio.to_thread(_send_email_sync, env, subject, html_body, brief_md)
                record(DeliveryResult("email", True, detail))
            except Exception as exc:  # noqa: BLE001
                record(DeliveryResult("email", False, f"{type(exc).__name__}: {exc}"[:200]))

        # --- telegram --------------------------------------------------------------
        if not cfg.delivery.telegram:
            record(DeliveryResult("telegram", True, "disabled in config", skipped=True))
        elif "telegram" in done:
            record(DeliveryResult("telegram", True, "already sent", skipped=True))
        elif not (env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID")):
            record(DeliveryResult("telegram", True, "未配置 Telegram 凭证，已跳过", skipped=True))
        else:
            try:
                record(await _send_telegram(http, env, brief_md))
            except Exception as exc:  # noqa: BLE001
                record(DeliveryResult("telegram", False, f"{type(exc).__name__}: {exc}"[:200]))

        # --- n8n -------------------------------------------------------------------
        if not cfg.delivery.n8n:
            record(DeliveryResult("n8n", True, "disabled in config", skipped=True))
        elif "n8n" in done:
            record(DeliveryResult("n8n", True, "already sent", skipped=True))
        elif not env.get("N8N_WEBHOOK_URL"):
            record(DeliveryResult("n8n", True, "未配置 N8N_WEBHOOK_URL，已跳过", skipped=True))
        else:
            try:
                record(await _send_n8n(http, env, digest, brief_md, site_url))
            except Exception as exc:  # noqa: BLE001
                record(DeliveryResult("n8n", False, f"{type(exc).__name__}: {exc}"[:200]))

    return report


async def _send_telegram(http: httpx.AsyncClient, env: Mapping[str, str], brief_md: str) -> DeliveryResult:
    """Telegram caps a message at 4096 characters; long digests are split on blank lines."""
    token = env["TELEGRAM_BOT_TOKEN"]
    chat_id = env["TELEGRAM_CHAT_ID"]
    chunks: list[str] = []
    current = ""
    for block in brief_md.split("\n\n"):
        if len(current) + len(block) + 2 > 3800:
            chunks.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current:
        chunks.append(current)

    sent = 0
    for chunk in chunks:
        resp = await http.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
        )
        if resp.status_code != 200:
            return DeliveryResult("telegram", False, f"HTTP {resp.status_code}: {resp.text[:120]}")
        sent += 1
    return DeliveryResult("telegram", True, f"{sent} message(s)")


async def _send_n8n(
    http: httpx.AsyncClient, env: Mapping[str, str], digest: Digest, brief_md: str, site_url: str
) -> DeliveryResult:
    """Structured payload for automation, with the markdown alongside for humans."""
    payload = {
        "date": digest.date,
        "generated_at": digest.generated_at.isoformat(),
        "site_url": site_url,
        "headline": digest.headline,
        "counts": digest.counts,
        "warnings": digest.warnings,
        "events": [
            {
                "event_id": e.event_id,
                "title": e.title,
                "urls": e.all_urls,
                "source_ids": e.source_ids,
                "independent_sources": e.independent_source_count,
                "evidence_level": e.evidence_level,
                "published_at": e.published_range[0].isoformat() if e.published_range else None,
            }
            for e in digest.top_events
        ],
        "brief_markdown": brief_md,
    }
    resp = await http.post(
        env["N8N_WEBHOOK_URL"],
        content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code >= 400:
        return DeliveryResult("n8n", False, f"HTTP {resp.status_code}: {resp.text[:120]}")
    return DeliveryResult("n8n", True, f"HTTP {resp.status_code}")


def delivery_ledger_line(report: DeliveryReport) -> dict[str, object]:
    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "channels": report.channels,
        "failures": report.summary()["failures"],
    }
