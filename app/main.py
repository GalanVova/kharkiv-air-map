from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .sources import TELEGRAM_SOURCES, poll_all_sources

load_dotenv()

POLL_SECONDS = max(10, int(os.getenv("POLL_SECONDS", "20")))
EVENT_TTL_MINUTES = max(5, int(os.getenv("EVENT_TTL_MINUTES", "20")))

EVENTS: dict[str, dict[str, Any]] = {}
SOURCE_STATUS: dict[str, str] = {}
LAST_POLL: datetime | None = None
POLL_LOCK = asyncio.Lock()


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _prune(now: datetime) -> None:
    cutoff = now - timedelta(minutes=EVENT_TTL_MINUTES)
    stale = [key for key, event in EVENTS.items() if _dt(event["published_at"]) < cutoff]
    for key in stale:
        EVENTS.pop(key, None)


def _clear_source(action: dict[str, Any]) -> None:
    source_id = action["source_id"]
    labels = set(action.get("locations") or [])
    clear_time: datetime = action["published_at"]
    for key, event in list(EVENTS.items()):
        if event.get("source_id") != source_id:
            continue
        if _dt(event["published_at"]) > clear_time:
            continue
        if labels and event.get("location") not in labels:
            continue
        EVENTS.pop(key, None)


def _add_event(event: dict[str, Any], now: datetime) -> None:
    published = _dt(event["published_at"])
    if published < now - timedelta(minutes=EVENT_TTL_MINUTES):
        return
    EVENTS[event["id"]] = event


async def refresh() -> None:
    global LAST_POLL, SOURCE_STATUS
    if POLL_LOCK.locked():
        return
    async with POLL_LOCK:
        now = datetime.now(timezone.utc)
        actions, status = await poll_all_sources()

        def action_time(item: dict[str, Any]) -> datetime:
            if item.get("action") == "clear":
                return item["published_at"]
            event = item.get("event") or {}
            return _dt(event.get("published_at", now.isoformat()))

        for action in sorted(actions, key=action_time):
            mode = action.get("action")
            if mode == "clear":
                _clear_source(action)
            elif mode in {"event", "feed_only"} and action.get("event"):
                _add_event(action["event"], now)

        _prune(now)
        SOURCE_STATUS = status
        LAST_POLL = now
        print("SOURCE_STATUS", status, "ACTIVE_EVENTS", len(EVENTS), flush=True)


async def poll_loop() -> None:
    while True:
        try:
            await refresh()
        except Exception as exc:
            print("POLL_ERROR", type(exc).__name__, str(exc), flush=True)
        await asyncio.sleep(POLL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await refresh()
    task = asyncio.create_task(poll_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Kharkiv Air Map", version="1.0.1", lifespan=lifespan)


@app.get("/api/events")
async def events() -> JSONResponse:
    now = datetime.now(timezone.utc)
    _prune(now)
    ordered = sorted(EVENTS.values(), key=lambda x: x["published_at"], reverse=True)
    return JSONResponse({"generated_at": now.isoformat(), "ttl_minutes": EVENT_TTL_MINUTES, "events": ordered},
                        headers={"Cache-Control": "no-store"})


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return {
        "ok": True,
        "last_poll": LAST_POLL.isoformat() if LAST_POLL else None,
        "poll_seconds": POLL_SECONDS,
        "event_ttl_minutes": EVENT_TTL_MINUTES,
        "source_status": SOURCE_STATUS,
        "sources": [{"id": s["id"], "name": s["name"], "url": f"https://t.me/{s['channel']}"} for s in TELEGRAM_SOURCES],
        "alerts_in_ua_enabled": bool(os.getenv("ALERTS_API_TOKEN", "").strip()),
    }


@app.post("/api/refresh")
async def force_refresh() -> dict[str, Any]:
    await refresh()
    return {"ok": True, "last_poll": LAST_POLL.isoformat() if LAST_POLL else None}


static_dir = Path(__file__).resolve().parent.parent / "static"
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
