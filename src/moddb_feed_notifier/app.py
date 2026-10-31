from __future__ import annotations

import logging
import threading
import time

from jinja2 import Environment

from . import feed, notify
from .settings import Settings
from .state import State

log = logging.getLogger(__name__)


def check(settings: Settings, env: Environment, state: State, feed_type: str) -> None:
    started = int(time.time())
    since = state.last_checked.get(feed_type)
    if since is None:
        log.info("%s: first run, items published from now on will be reported from the next check on", feed_type)
        state.last_checked[feed_type] = started
        return

    try:
        items = feed.fetch_new_items(settings.feed_url(feed_type), feed_type, since)
    except Exception as exc:
        log.error("%s: failed to fetch feed, retrying next run: %s", feed_type, exc)
        return

    if len(items) > settings.max_items:
        log.warning("%s: %d new items, only sending the newest %d", feed_type, len(items), settings.max_items)
        items = items[-settings.max_items :]
    log.info("%s: %d new item(s)", feed_type, len(items))

    notify_url = settings.notify_url.get_secret_value()
    for item in items:
        if not notify.send(notify_url, notify.render(env, item, settings.message_format)):
            log.error("%s: failed to send '%s', retrying next run", feed_type, item.title)
            # Items before this one were sent; continue from here next time
            state.last_checked[feed_type] = max(since, int(item.date.timestamp()) - 1)
            return
        log.debug("%s: sent '%s'", feed_type, item.title)

    state.last_checked[feed_type] = started


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
