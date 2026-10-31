from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading

from jinja2 import TemplateError, TemplateSyntaxError
from pydantic import ValidationError

from .app import run_forever, run_once
from .notify import create_environment, preview
from .settings import Settings, TemplateSettings

log = logging.getLogger("moddb_feed_notifier")


def load_settings[T: TemplateSettings](cls: type[T]) -> T:
    try:
        return cls()
    except ValidationError as exc:
        lines = []
        for err in exc.errors():
            message = err["msg"].removeprefix("Value error, ")
            field = "_".join(map(str, err["loc"])).upper()
            lines.append(f"  MFN_{field}: {message}" if field else f"  {message}")
        sys.exit("Invalid configuration:\n" + "\n".join(lines))


def print_preview() -> None:
    settings = load_settings(TemplateSettings)
    try:
        output = preview(create_environment(settings.template_dir), settings.message_format)
    except TemplateSyntaxError as exc:
        sys.exit(f"Template error in {exc.filename}, line {exc.lineno}: {exc.message}")
    except TemplateError as exc:
        sys.exit(f"Template error: {exc.message}")
    except json.JSONDecodeError as exc:
        sys.exit(f"Template error: discord.json.j2 does not produce valid JSON: {exc}")
    # Feed content and templates may contain any Unicode, even when stdout is a pipe on Windows
    sys.stdout.reconfigure(encoding="utf-8")
    print(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Get notified about new items in ModDB feeds.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="check once and exit instead of running forever")
    mode.add_argument("--preview", action="store_true", help="print a message rendered with sample data and exit")
    args = parser.parse_args()

    if args.preview:
        print_preview()
        return

    settings = load_settings(Settings)
    # Third-party libraries (moddb, apprise, ...) only report warnings; MFN_LOG_LEVEL applies to our own logs
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    log.setLevel(settings.log_level)
    env = create_environment(settings.template_dir)

    schedule = "once" if args.once else f"every {settings.interval} minute(s)"
    log.info(
        "Checking %s on %s %s, sending as %s",
        ", ".join(settings.types),
        settings.page_url,
        schedule,
        settings.message_format,
    )

    if args.once:
        run_once(settings, env)
        return

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run_forever(settings, env, stop)
    log.info("Stopped")


if __name__ == "__main__":
    main()
