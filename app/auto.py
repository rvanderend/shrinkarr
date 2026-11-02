"""Automatic conversion after an import in Sonarr/Radarr, the webhooks, and the daily summary."""
import asyncio
import logging
import secrets
import smtplib
import socket
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import httpx

from . import arr, config, db, encoders, media
from .i18n import fmt_bytes, tr

log = logging.getLogger("shrinkarr.auto")


# --- webhook token and address ------------------------------------------------

def hook_token() -> str:
    tok = db.get_state("hook_token") or config.env("HOOK_TOKEN")
    if not tok:
        tok = secrets.token_urlsafe(24)
    if db.get_state("hook_token") != tok:
        db.set_state("hook_token", tok)
    return tok


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packet is sent; only picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def hook_base() -> str:
    return db.get_settings()["hook_base_url"] or f"http://{lan_ip()}:{config.PORT}"


def hook_url(app: str) -> str:
    return f"{hook_base()}/api/hook/{app}?token={hook_token()}"


async def install_webhooks() -> dict:
    """Creates (or updates) a Webhook connection named "Shrinkarr" in Sonarr and Radarr."""
    out = {}
    for app in arr.APPS:
        if not arr.configured(app):
            continue
        try:
            existing = [n for n in await arr.api(app, "GET", "/notification") if n.get("name") == "Shrinkarr"]
            fields = [{"name": "url", "value": hook_url(app)}, {"name": "method", "value": 1},
                      {"name": "username", "value": ""}, {"name": "password", "value": ""},
                      {"name": "headers", "value": []}]
            body = {"name": "Shrinkarr", "implementation": "Webhook", "configContract": "WebhookSettings",
                    "onDownload": True, "onUpgrade": True, "tags": [], "fields": fields}
            if existing:
                body = {**existing[0], **body, "id": existing[0]["id"]}
                await arr.api(app, "PUT", f"/notification/{existing[0]['id']}", json=body)
            else:
                await arr.api(app, "POST", "/notification", json=body)
            out[app] = {"ok": True}
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:300]
            out[app] = {"ok": False, "error": f"HTTP {e.response.status_code}: {detail}"}
        except Exception as e:  # noqa: BLE001
            out[app] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return out


# --- judging an imported file ------------------------------------------------------

async def consider(app: str, arr_id: int, *, file_id: int | None = None, path: str | None = None,
                   via: str = "webhook") -> str:
    """Queues a freshly imported file if it matches the rules. Returns the reason."""
    s = db.get_settings()
    if not s["auto_enabled"]:
        return tr("auto_off")
    kind = "movie" if app == "radarr" else "series"
    await arr.LIB.refresh_item(kind, arr_id)
    item = arr.LIB.item(kind, arr_id)
    if not item:
        return tr("auto_no_title")
    f = next((x for x in item["files"] if (file_id and x["fileId"] == file_id) or (path and x["path"] == path)), None)
    if not f:
        return tr("auto_no_file")
    reason = None
    if not (s["auto_movies"] if kind == "movie" else s["auto_series"]):
        reason = tr("auto_kind_off")
    elif item["root"] and item["root"] in s["auto_exclude_roots"]:
        reason = tr("auto_root_off")
    elif not media.needs_work(f, s):
        reason = tr("auto_efficient", codec=f["codecLabel"])
    elif Path(f["path"]).suffix.lower() != ".mkv":
        reason = tr("auto_not_mkv")
    elif s["auto_skip_cutoff"] and f["cutoffNotMet"]:
        reason = tr("auto_cutoff")
    elif db.active_job_for(f["kind"], f["fileId"]):
        reason = tr("auto_queued_already")
    # By file ID: a replaced file with the same name gets a new ID in Sonarr/Radarr.
    elif db.one("SELECT id FROM jobs WHERE kind=? AND file_id=? AND source='auto' AND created>?",
                (f["kind"], f["fileId"], time.time() - 7 * 86400)):
        reason = tr("auto_tried")
    if reason:
        log.info("Auto (%s) skipped: %s – %s", via, f["path"], reason)
        return reason
    preset = s["auto_preset"] if s["auto_preset"] in config.PRESETS else "balanced"
    sample = db.get_sample(f"{kind}:{arr_id}:{preset}")
    enc = await encoders.resolve()
    e = media.estimate(f, f["size"], preset, media.Model(enc["encoder"]), sample)
    title = f"{item['title']} ({item['year']})" if kind == "movie" and item.get("year") else item["title"]
    db.add_job(kind=f["kind"], arr_id=arr_id, file_id=f["fileId"], title=title,
               subtitle=f["label"] if f["kind"] == "episode" else f["quality"], path=f["path"], preset=preset,
               size_before=f["size"], est_size=e["size"], est_seconds=e["seconds"], source="auto",
               not_before=time.time() + float(s["auto_delay_hours"]) * 3600)
    log.info("Auto (%s) queued: %s", via, f["path"])
    return tr("auto_queued")


async def handle_webhook(app: str, payload: dict):
    """Handles a webhook from Sonarr/Radarr ("Download" = import or upgrade)."""
    db.set_state(f"hook_{app}", time.time())
    if payload.get("eventType") != "Download":
        return
    if app == "sonarr":
        arr_id = (payload.get("series") or {}).get("id")
        files = payload.get("episodeFiles") or ([payload["episodeFile"]] if payload.get("episodeFile") else [])
    else:
        arr_id = (payload.get("movie") or {}).get("id")
        files = [payload["movieFile"]] if payload.get("movieFile") else []
    # Sonarr/Radarr just finished importing; give them a moment for the mediaInfo.
    await asyncio.sleep(10)
    for f in files:
        try:
            await consider(app, arr_id, file_id=f.get("id"), via="webhook")
        except Exception:  # noqa: BLE001
            log.exception("Webhook file %s not handled", f)


async def catch_up():
    """Imports the webhook missed (the service was down) are picked up from the history."""
    if not db.get_settings()["auto_enabled"]:
        return
    now = datetime.now(timezone.utc)
    for app in arr.APPS:
        if not arr.configured(app):
            continue
        since = db.get_state(f"history_{app}")
        if not since:  # first time: don't go through the whole history
            db.set_state(f"history_{app}", now.isoformat())
            continue
        try:
            imports = await arr.imports_since(app, since)
        except Exception:  # noqa: BLE001
            log.exception("Loading the history of %s failed", app)
            continue
        for imp in imports:
            try:
                await consider(app, imp["arr_id"], path=imp["path"], via="history")
            except Exception:  # noqa: BLE001
                log.exception("Import %s not handled", imp)
        # Keep some overlap: the webhook and the history can cross each other.
        db.set_state(f"history_{app}", (now - timedelta(minutes=2)).isoformat())


# --- kept originals ------------------------------------------------------------------

def clean_kept(everything: bool = False, job_id: int | None = None) -> int:
    """Deletes kept originals whose time is up (or all of them, or one), and folders that become empty."""
    from .worker import KEEP_DIR
    if job_id is not None:
        jobs = db.q("SELECT id, kept_path FROM jobs WHERE kept_path IS NOT NULL AND id = ?", (job_id,))
    else:
        until = float("inf") if everything else time.time()
        jobs = db.q("SELECT id, kept_path FROM jobs WHERE kept_path IS NOT NULL AND kept_until < ?", (until,))
    for j in jobs:
        p = Path(j["kept_path"])
        try:
            p.unlink(missing_ok=True)
            d = p.parent
            while d.name != KEEP_DIR and d != d.parent and not any(d.iterdir()):
                d.rmdir()
                d = d.parent
            if d.name == KEEP_DIR and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            log.warning("Could not remove the kept original %s", p)
        db.update_job(j["id"], kept_path=None)
    return len(jobs)


# --- notifications -----------------------------------------------------------------

def _send_mail(s: dict, subject: str, body: str):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Shrinkarr <{s['notify_from']}>"
    msg["To"] = s["notify_to"]
    msg.set_content(body)
    port = int(s["smtp_port"] or 25)
    if s["smtp_security"] == "ssl":
        smtp = smtplib.SMTP_SSL(s["smtp_host"], port, timeout=30, context=ssl.create_default_context())
    else:
        smtp = smtplib.SMTP(s["smtp_host"], port, timeout=30)
    with smtp:
        if s["smtp_security"] == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        if s["smtp_user"]:
            smtp.login(s["smtp_user"], s["smtp_password"])
        smtp.send_message(msg)


async def send(subject: str, body: str):
    """Sends a notification as configured."""
    s = db.get_settings()
    link = s["public_url"] or hook_base()
    if s["notify_method"] == "pushover":
        if not (s["pushover_token"] and s["pushover_user"]):
            raise RuntimeError(tr("pushover_missing"))
        data = {"token": s["pushover_token"], "user": s["pushover_user"], "title": subject,
                "message": body[:1000], "priority": int(s["pushover_priority"]),
                "url": link, "url_title": tr("n_open")}
        if s["pushover_device"]:
            data["device"] = s["pushover_device"]
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post("https://api.pushover.net/1/messages.json", data=data)
        if r.status_code != 200:
            try:
                errs = "; ".join(r.json().get("errors", [])) or r.text
            except ValueError:
                errs = r.text
            raise RuntimeError(f"Pushover: {errs}")
    else:
        if not (s["smtp_host"] and s["notify_from"] and s["notify_to"]):
            raise RuntimeError(tr("smtp_missing"))
        await asyncio.to_thread(_send_mail, s, subject, body + "\n" + link)


def summary(since: float) -> tuple[str, str] | None:
    rows = db.q("SELECT title, subtitle, status, message, size_before, size_after FROM jobs "
                "WHERE finished>? AND status IN ('done','failed') ORDER BY finished", (since,))
    if not rows:
        return None
    done = [r for r in rows if r["status"] == "done"]
    failed = [r for r in rows if r["status"] == "failed"]
    saved = sum(r["size_before"] - (r["size_after"] or r["size_before"]) for r in done)
    parts = []
    if done:
        parts.append(tr("n_converted", n=len(done), saved=fmt_bytes(saved)))
    if failed:
        parts.append(tr("n_failed", n=len(failed)))
    subject = "Shrinkarr: " + ", ".join(parts)

    def name(r):
        return f"{r['title']} – {r['subtitle']}" if r["subtitle"] else r["title"]
    lines = [f"✓ {name(r)}: {fmt_bytes(r['size_before'])} → {fmt_bytes(r['size_after'])}" for r in done[:15]]
    if len(done) > 15:
        lines.append(tr("n_more", n=len(done) - 15))
    lines += [f"✗ {name(r)}: {r['message']}" for r in failed[:5]]
    queued = db.one("SELECT COUNT(*) AS n FROM jobs WHERE status='queued'")["n"]
    tot = db.one("SELECT COALESCE(SUM(size_before - size_after), 0) AS s FROM jobs WHERE status='done'")["s"]
    lines += ["", tr("n_footer", n=queued, saved=fmt_bytes(tot))]
    return subject, "\n".join(lines)


async def notify_tick():
    s = db.get_settings()
    last = db.get_state("notified", 0) or time.time() - 86400
    now = datetime.now()
    due = now.strftime("%H:%M") >= s["notify_time"] and datetime.fromtimestamp(last).date() < now.date()
    if not (s["notify_enabled"] and due):
        return
    db.set_state("notified", time.time())
    res = summary(last)
    if res:
        try:
            await send(*res)
            log.info("Daily summary sent: %s", res[0])
        except Exception:  # noqa: BLE001
            log.exception("Sending the daily summary failed")


async def loop():
    """Every minute: check the summary; every quarter of an hour: pick up missed imports."""
    n = 0
    while True:
        try:
            await notify_tick()
            if n % 15 == 0:
                await catch_up()
            if n % 60 == 0:
                await asyncio.to_thread(clean_kept)
        except Exception:  # noqa: BLE001
            log.exception("Error in the auto loop")
        n += 1
        await asyncio.sleep(60)
