from __future__ import annotations

import datetime
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import apprise
import requests
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .feed import Feed, Item
from .settings import MessageFormat

log = logging.getLogger(__name__)

BUILTIN_TEMPLATE_DIR = Path(__file__).parent / "templates"
BODY_TEMPLATES: dict[MessageFormat, str] = {
    "markdown": "body.md.j2",
    "html": "body.html.j2",
    "text": "body.txt.j2",
    "discord": "discord.json.j2",
}
DISCORD_MAX_RETRIES = 3


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    format: MessageFormat


def create_environment(template_dir: Path | None) -> Environment:
    """User templates take precedence; missing files fall back to the built-in ones."""
    search_path = [template_dir, BUILTIN_TEMPLATE_DIR] if template_dir else [BUILTIN_TEMPLATE_DIR]
    env = Environment(
        loader=FileSystemLoader(search_path),
        undefined=StrictUndefined,
        # Feed content is user content: escape it in HTML templates, but never in the plain-text title
        autoescape=select_autoescape(enabled_extensions=("html.j2",), default_for_string=False),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )
    # Two trailing spaces are a Markdown hard line break, so multi-line text keeps its lines in HTML
    env.filters["quote"] = lambda text: "  \n".join(f"> {line}" for line in text.splitlines() or [""])
    return env


def render(env: Environment, item: Item, message_format: MessageFormat) -> Message:
    context = {"item": item}
    title = " ".join(env.get_template("title.j2").render(context).split())
    body = env.get_template(BODY_TEMPLATES[message_format]).render(context).strip()
    if message_format == "discord":
        payload = json.loads(body)  # fail early on templates that don't produce valid JSON
        body = json.dumps(payload, ensure_ascii=False)
    return Message(title=title, body=body, format=message_format)


def send(notify_url: str, message: Message) -> bool:
    if message.format == "discord":
        return send_discord(notify_url, json.loads(message.body))
    apobj = apprise.Apprise()
    apobj.add(notify_url)
    return bool(apobj.notify(title=message.title, body=message.body, body_format=apprise.NotifyFormat(message.format)))


def send_discord(webhook_url: str, payload: dict) -> bool:
    for _ in range(DISCORD_MAX_RETRIES):
        try:
            response = requests.post(webhook_url, json=payload, timeout=30)
        except requests.RequestException as exc:
            log.error("Discord webhook request failed: %s", exc)
            return False
        if response.status_code == 429:
            retry_after = float(response.json()["retry_after"])
            log.debug("Discord rate limit hit, retrying in %.1fs", retry_after)
            time.sleep(retry_after)
            continue
        if response.ok:
            return True
        log.error("Discord webhook error %d: %s", response.status_code, response.text)
        return False
    log.error("Discord webhook still rate limited after %d attempts", DISCORD_MAX_RETRIES)
    return False


SAMPLE_ITEM = Item(
    id="downloads123456",
    type="addons",
    feed=Feed(
        title="Addon files RSS feed - S.T.A.L.K.E.R. Anomaly mod for S.T.A.L.K.E.R.: Call of Pripyat - ModDB",
        section="Addon files",
        page="S.T.A.L.K.E.R. Anomaly mod for S.T.A.L.K.E.R.: Call of Pripyat",
        url="https://www.moddb.com/mods/stalker-anomaly/addons",
    ),
    title='Better Textures "HD" v2.1',
    description="A complete overhaul of all weapon and environment textures.\nNow with 4K support!",
    url="https://www.moddb.com/mods/stalker-anomaly/addons/better-textures",
    image="https://media.moddb.com/images/mods/1/30/29353/sample.png",
    date=datetime.datetime(2026, 1, 2, 14, 5, tzinfo=datetime.UTC),
)


def preview(env: Environment, message_format: MessageFormat) -> str:
    """Render the templates with a sample feed item."""
    message = render(env, SAMPLE_ITEM, message_format)
    body = (
        json.dumps(json.loads(message.body), indent=2, ensure_ascii=False)
        if message_format == "discord"
        else message.body
    )
    return f"---- sample item ({message_format}) ----\nTitle: {message.title}\n\n{body}"
