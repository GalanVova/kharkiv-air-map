from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .parser import parse_message

TELEGRAM_SOURCES = [
    {"id": "radar_kharkov", "name": "RADAR KH", "channel": "radar_kharkov", "weight": 3, "location_first": True},
    {"id": "tlknewsua", "name": "TLK News", "channel": "tlknewsua", "weight": 3, "location_first": True},
    {"id": "monitor1654", "name": "monitor 1654 | Харків", "channel": "monitor1654", "weight": 3, "location_first": True},
    {"id": "radar_harkiv", "name": "Харків Alerts", "channel": "radar_harkiv", "weight": 2, "location_first": True},
    {"id": "kpszsu", "name": "Повітряні Сили ЗС України", "channel": "kpszsu", "weight": 4, "location_first": False},
    {"id": "war_monitor", "name": "monitor", "channel": "war_monitor", "weight": 2, "location_first": True},
    {"id": "kharkivlife", "name": "Харьков life | Харків", "channel": "kharkivlife", "weight": 1, "location_first": False},
]

USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0 kharkiv-air-map/1.1")


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    value = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def fetch_telegram_source(client: httpx.AsyncClient, source: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    url = f"https://t.me/s/{source['channel']}"
    response = await client.get(url, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results: list[dict[str, Any]] = []
    wrappers = soup.select(".tgme_widget_message_wrap")[-40:]

    for wrapper in wrappers:
        msg = wrapper.select_one(".tgme_widget_message")
        text_el = wrapper.select_one(".tgme_widget_message_text")
        time_el = wrapper.select_one("time")
        if not msg or not text_el:
            continue
        post = msg.get("data-post", "")
        post_id = post.rsplit("/", 1)[-1] if post else "unknown"
        text = text_el.get_text(" ", strip=True)
        published_at = _parse_dt(time_el.get("datetime") if time_el else None)
        post_url = f"https://t.me/{source['channel']}/{post_id}"
        results.append(parse_message(
            source_id=source["id"], source_name=source["name"], post_id=post_id,
            text=text, published_at=published_at, url=post_url, weight=source["weight"],
            location_first=source.get("location_first", False),
        ))
    return results, len(wrappers)


async def fetch_alerts_in_ua(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    token = os.getenv("ALERTS_API_TOKEN", "").strip()
    if not token:
        return []
    response = await client.get("https://api.alerts.in.ua/v1/alerts/active.json",
        headers={"Authorization": f"Bearer {token}"}, timeout=12)
    response.raise_for_status()
    payload = response.json()
    alerts = payload.get("alerts", payload if isinstance(payload, list) else [])
    out: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for idx, alert in enumerate(alerts):
        region = str(alert.get("location_title") or alert.get("location") or "")
        if "харків" not in region.lower() and "харьков" not in region.lower():
            continue
        alert_type = str(alert.get("alert_type") or alert.get("type") or "Повітряна тривога")
        started = alert.get("started_at") or alert.get("created_at")
        published = _parse_dt(started) if started else now
        out.append({"action": "event", "event": {
            "id": f"alerts-in-ua-{alert.get('id', idx)}", "kind": "Офіційна тривога",
            "source_id": "alerts_in_ua", "source_name": "alerts.in.ua",
            "post_id": str(alert.get("id", idx)), "text": f"{alert_type}: {region}",
            "published_at": published.isoformat(), "url": "https://alerts.in.ua/", "weight": 5,
            "mapped": True, "location": "Харків / область", "lat": 49.9935, "lon": 36.2304,
            "direction_to": None, "direction_from": None, "coarse": True,
        }})
    return out


async def poll_all_sources() -> tuple[list[dict[str, Any]], dict[str, str]]:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "uk,ru;q=0.9,en;q=0.6"}
    actions: list[dict[str, Any]] = []
    status: dict[str, str] = {}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        for source in TELEGRAM_SOURCES:
            try:
                parsed, count = await fetch_telegram_source(client, source)
                actions.extend(parsed)
                mapped = sum(1 for x in parsed if x.get("action") == "event")
                status[source["id"]] = f"ok posts={count} mapped={mapped}"
            except Exception as exc:
                status[source["id"]] = f"error: {type(exc).__name__}"
        try:
            official = await fetch_alerts_in_ua(client)
            actions.extend(official)
            status["alerts_in_ua"] = "ok" if os.getenv("ALERTS_API_TOKEN") else "disabled:no-token"
        except Exception as exc:
            status["alerts_in_ua"] = f"error: {type(exc).__name__}"
    return actions, status
