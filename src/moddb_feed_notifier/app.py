from __future__ import annotations

import logging
import threading

from jinja2 import Environment

from . import feed, notify
from .settings import Settings
from .state import State

log = logging.getLogger(__name__)


def check(settings: Settings, env: Environment, state: State, feed_type: str) -> None:
    try:
        items = feed.fetch_items(settings.feed_url(feed_type), feed_type)
    except Exception as exc:
        log.error("%s: failed to fetch feed, retrying next run: %s", feed_type, exc)
        return

    if feed_type not in state.seen:
        log.info("%s: first run, remembering %d current item(s) without sending them", feed_type, len(items))
        state.mark_seen(feed_type, [item.id for item in items])
        return

    new = [item for item in items if item.id not in state.seen[feed_type]]
    if len(new) > settings.max_items:
        log.warning("%s: %d new items, only sending the newest %d", feed_type, len(new), settings.max_items)
        state.mark_seen(feed_type, [item.id for item in new[: -settings.max_items]])
        new = new[-settings.max_items :]
    log.info("%s: %d new item(s)", feed_type, len(new))

    notify_url = settings.notify_url.get_secret_value()
    for item in new:
        if not notify.send(notify_url, notify.render(env, item, settings.message_format)):
            # Not marked as seen, so it is retried together with everything after it
            log.error("%s: failed to send '%s', retrying next run", feed_type, item.title)
            return
        state.mark_seen(feed_type, [item.id])
        log.debug("%s: sent '%s'", feed_type, item.title)


def run_once(settings: Settings, env: Environment) -> None:
    state = State.load(settings.state_dir)
    for feed_type in settings.types:
        check(settings, env, state, feed_type)
    state.save(settings.state_dir)


def run_forever(settings: Settings, env: Environment, stop: threading.Event) -> None:
    while not stop.is_set():
        run_once(settings, env)
        log.info("Next check in %d minute(s)", settings.interval)
        stop.wait(settings.interval * 60)
