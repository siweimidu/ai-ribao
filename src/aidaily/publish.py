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

from .config import AppConfig
from .models import Digest
from .render import render_email_html

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


def write_rss(digest: Digest, out_dir: Path, *, site_url: str) -> DeliveryResult:
    """An RSS 2.0 feed alongside the JSON Feed, for readers that only speak RSS."""
    items = []
    for event in digest.top_events:
        when = event.published_range[0].strftime("%a, %d %b %Y %H:%M:%S +0000") if event.published_range else ""
        links = "".join(
            f'<li><a href="{_xml_escape(u)}">{_xml_escape(u)}</a></li>' for u in event.all_urls
        )
        items.append(
            "<item>"
            f"<title>{_xml_escape(event.title)}</title>"
            f"<link>{_xml_escape(event.all_urls[0] if event.all_urls else site_url)}</link>"
            f"<guid isPermaLink=\"false\">{_xml_escape(digest.date)}-{_xml_escape(event.event_id)}</guid>"
            f"<pubDate>{when}</pubDate>"
            f"<description>{_xml_escape('<ul>' + links + '</ul>')}</description>"
            f"<category>{_xml_escape(','.join(event.source_ids))}</category>"
            "</item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        f"<title>AI 日报</title><link>{_xml_escape(site_url)}</link>"
        "<language>zh-cn</language>"
        f"<lastBuildDate>{digest.generated_at.strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>"
        f"<description>每日 AI 资讯聚合</description>{''.join(items)}</channel></rss>\n"
    )
    target = out_dir / "feed" / "zh.xml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(xml, encoding="utf-8")
    return DeliveryResult("rss", True, f"{target.name}: {len(items)} items")


def write_site(digest: Digest, deep_md: str, out_dir: Path, *, site_url: str) -> DeliveryResult:
    """A minimal static page plus an archive index.

    Deliberately plain: the styled front end is a separate piece of work, and shipping a
    readable page now is better than shipping a broken designed one.
    """
    site = out_dir / "site"
    site.mkdir(parents=True, exist_ok=True)
    body = html_mod.escape(deep_md)
    (site / f"{digest.date}.html").write_text(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>AI 日报 {digest.date}</title></head>"
        f"<body style='max-width:760px;margin:0 auto;padding:20px;font-family:system-ui,sans-serif'>"
        f"<pre style='white-space:pre-wrap;font-family:inherit'>{body}</pre></body></html>",
        encoding="utf-8",
    )

    days = sorted((p.stem for p in site.glob("*.html") if p.stem != "index"), reverse=True)
    links = "".join(f"<li><a href='{d}.html'>{d}</a></li>" for d in days[:180])
    (site / "index.html").write_text(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>AI 日报</title></head>"
        "<body style='max-width:760px;margin:0 auto;padding:20px;font-family:system-ui,sans-serif'>"
        f"<h1>AI 日报</h1><p>共 {len(days)} 期</p><ul>{links}</ul></body></html>",
        encoding="utf-8",
    )
    return DeliveryResult("pages", True, f"{len(days)} 期归档")


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
) -> DeliveryReport:
    """Attempt every enabled channel, independently."""
    done = set((already_done or {}).keys())
    report = DeliveryReport()

    def record(result: DeliveryResult) -> None:
        report.results.append(result)

    # --- local artefacts first: they always succeed and other channels link to them ---
    if cfg.delivery.rss:
        try:
            record(write_rss(digest, out_dir, site_url=site_url))
        except Exception as exc:  # noqa: BLE001
            record(DeliveryResult("rss", False, f"{type(exc).__name__}: {exc}"[:200]))

    if cfg.delivery.pages:
        try:
            record(write_site(digest, deep_md, out_dir, site_url=site_url))
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
