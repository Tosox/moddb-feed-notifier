from __future__ import annotations

import datetime
import json

import pytest
from pydantic import ValidationError

from moddb_feed_notifier import __main__, app, feed, notify
from moddb_feed_notifier.feed import Feed, Item
from moddb_feed_notifier.settings import Settings, TemplateSettings
from moddb_feed_notifier.state import State

DISCORD_URL = "https://discord.com/api/webhooks/123456789/abc-DEF_123"
APPRISE_URL = "json://localhost/"
PAGE = "https://www.moddb.com/mods/stalker-anomaly"

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Addon files RSS feed - S.T.A.L.K.E.R. Anomaly mod for S.T.A.L.K.E.R.: Call of Pripyat - ModDB</title>
    <link>https://www.moddb.com/mods/stalker-anomaly/addons</link>
    <item>
      <title>Newer Addon</title>
      <link>https://www.moddb.com/mods/stalker-anomaly/addons/newer</link>
      <guid isPermaLink="false">downloads2</guid>
      <pubDate>Fri, 02 Jan 2026 15:00:00 +0100</pubDate>
      <media:content url="https://media.moddb.com/newer.png">
        <media:description>Fixes&nbsp;everything &amp; more</media:description>
      </media:content>
    </item>
    <item>
      <title>Older
        Addon</title>
      <link>https://www.moddb.com/mods/stalker-anomaly/addons/older</link>
      <guid isPermaLink="false">downloads1</guid>
      <pubDate>Fri, 02 Jan 2026 10:00:00 GMT</pubDate>
      <description>Old &lt;br /&gt;text</description>
    </item>
  </channel>
</rss>
"""


FEED = Feed(
    title="Addon files RSS feed - Tosox - ModDB",
    section="Addon files",
    page="Tosox",
    url="https://www.moddb.com/members/tosox/addons",
)


def make_item(
    title: str = "Cool Addon", description: str = "Nice!", image: str | None = "https://img/x.png", feed: Feed = FEED
) -> Item:
    return Item(
        id=f"downloads-{title}",
        type="addons",
        feed=feed,
        title=title,
        description=description,
        url="https://www.moddb.com/mods/stalker-anomaly/addons/cool-addon",
        image=image,
        date=datetime.datetime(2026, 1, 2, 3, 4, tzinfo=datetime.UTC),
    )


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # don't pick up a developer's .env
    for name in ("PAGE", "NOTIFY_URL", "TYPES", "MESSAGE_FORMAT", "TEMPLATE_DIR"):
        monkeypatch.delenv(f"MFN_{name}", raising=False)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(page=PAGE, notify_url=DISCORD_URL, state_dir=tmp_path)


# Settings


def test_feed_urls_for_any_page():
    member = Settings(page="https://www.moddb.com/members/tosox/", notify_url=DISCORD_URL)
    site = Settings(page="https://www.moddb.com", notify_url=DISCORD_URL)

    assert member.feed_url("addons") == "https://rss.moddb.com/members/tosox/addons/feed/rss.xml"
    assert site.feed_url("articles") == "https://rss.moddb.com/articles/feed/rss.xml"


def test_types_from_env(monkeypatch):
    monkeypatch.setenv("MFN_PAGE", PAGE)
    monkeypatch.setenv("MFN_NOTIFY_URL", DISCORD_URL)
    monkeypatch.setenv("MFN_TYPES", "Addons, videos;addons mods")

    assert Settings().types == ["addons", "videos", "mods"]


def test_settings_reject_invalid_values():
    with pytest.raises(ValidationError) as exc:
        Settings(page="https://example.com/mods/x", notify_url="not-a-url", types="addons,../x", interval=0)
    assert {err["loc"][0] for err in exc.value.errors()} == {"page", "notify_url", "types", "interval"}


def test_message_format_defaults_to_discord_for_webhooks():
    assert Settings(page=PAGE, notify_url=DISCORD_URL).message_format == "discord"
    assert Settings(page=PAGE, notify_url=APPRISE_URL).message_format == "markdown"
    assert Settings(page=PAGE, notify_url=DISCORD_URL, message_format="HTML").message_format == "html"


def test_discord_format_requires_webhook_url():
    with pytest.raises(ValidationError, match="requires a Discord webhook URL"):
        Settings(page=PAGE, notify_url=APPRISE_URL, message_format="discord")


def test_secrets_are_hidden(settings):
    assert DISCORD_URL not in repr(settings)


# Feed


def test_parse_feed():
    older, newer = feed.parse_feed(RSS, "addons")

    assert older.id == "downloads1"
    assert older.title == "Older Addon"
    assert older.image is None
    assert older.description == "Old \ntext"
    assert newer.id == "downloads2"
    assert newer.title == "Newer Addon"
    assert newer.description == "Fixes\xa0everything & more"
    assert newer.image == "https://media.moddb.com/newer.png"
    assert newer.date == datetime.datetime(2026, 1, 2, 14, 0, tzinfo=datetime.UTC)


def test_parse_channel():
    older, _ = feed.parse_feed(RSS, "addons")

    assert older.feed.section == "Addon files"
    assert older.feed.page == "S.T.A.L.K.E.R. Anomaly mod for S.T.A.L.K.E.R.: Call of Pripyat"
    assert older.feed.url == "https://www.moddb.com/mods/stalker-anomaly/addons"


def test_parse_site_wide_channel():
    xml = RSS.replace("S.T.A.L.K.E.R. Anomaly mod for S.T.A.L.K.E.R.: Call of Pripyat - ", "")
    older, _ = feed.parse_feed(xml, "addons")

    assert (older.feed.section, older.feed.page) == ("Addon files", "ModDB")


def test_unknown_channel_title_is_an_error():
    xml = RSS.replace("Addon files RSS feed - S.T.A.L.K.E.R.", "Something else - S.T.A.L.K.E.R.")
    with pytest.raises(ValueError, match="unexpected feed title"):
        feed.parse_feed(xml, "addons")


def test_missing_guid_is_an_error():
    xml = RSS.replace('<guid isPermaLink="false">downloads1</guid>', "")
    with pytest.raises(ValueError, match="<guid> missing"):
        feed.parse_feed(xml, "addons")


def test_parse_review():
    xml = """<rss version="2.0"><channel>
      <title>Review RSS feed - Tosox - ModDB</title>
      <link>https://www.moddb.com/members/tosox/reviews</link>
      <item>
        <title>True Stalker review by Tosox</title>
        <link>https://www.moddb.com/mods/true-stalker/reviews/901491</link>
        <pubDate>Sun, 07 Jan 2024 13:53:17 +0000</pubDate>
        <guid isPermaLink="false">reviews901491</guid>
        <description>I don&#39;t get it.&lt;br /&gt;Use &amp;lt;b&amp;gt; for bold.</description>
      </item>
    </channel></rss>"""
    (review,) = feed.parse_feed(xml, "reviews")

    assert review.description == "I don't get it.\nUse <b> for bold."
    assert review.image is None
    assert (review.feed.section, review.feed.page) == ("Review", "Tosox")


def test_fetch_items(monkeypatch):
    class Response:
        text = RSS

    monkeypatch.setattr(feed.moddb.utils, "request", lambda req: Response())
    assert [item.id for item in feed.fetch_items("https://rss/feed", "addons")] == ["downloads1", "downloads2"]


# State


def test_state_roundtrip(tmp_path):
    State(seen={"addons": ["a", "b"]}).save(tmp_path)
    assert State.load(tmp_path) == State(seen={"addons": ["a", "b"]})


def test_state_from_older_version_starts_fresh(tmp_path):
    (tmp_path / "state.json").write_text('{"last_checked": {"addons": 1793539413}}', encoding="utf-8")
    assert State.load(tmp_path) == State()


def test_mark_seen_keeps_the_newest_ids():
    state = State()
    state.mark_seen("addons", [str(i) for i in range(60)])
    state.mark_seen("addons", ["10", "new"])

    assert len(state.seen["addons"]) == 50
    assert state.seen["addons"][-2:] == ["10", "new"]
    assert "9" not in state.seen["addons"]


def test_state_missing(tmp_path):
    assert State.load(tmp_path) == State()


# Templates


def test_discord_payload_is_valid_and_escaped():
    item = make_item(title='Say "hi"\\', description="line 1\nline 2")
    message = notify.render(notify.create_environment(None), item, "discord")
    embed = json.loads(message.body)["embeds"][0]

    assert embed["title"] == 'Say "hi"\\'
    assert embed["description"] == "> line 1  \n> line 2"
    assert embed["image"] == {"url": "https://img/x.png"}
    assert embed["timestamp"] == "2026-01-02T03:04:00+00:00"


def test_discord_author_shows_feed():
    embed = json.loads(notify.render(notify.create_environment(None), make_item(), "discord").body)["embeds"][0]
    assert embed["author"] == {"name": "Addon files · Tosox", "url": "https://www.moddb.com/members/tosox/addons"}


def test_discord_payload_without_image_and_truncated():
    message = notify.render(notify.create_environment(None), make_item(title="x" * 300, image=None), "discord")
    embed = json.loads(message.body)["embeds"][0]

    assert "image" not in embed
    assert len(embed["title"]) == 256


def test_html_body_escapes_content():
    item = make_item(description="<script>alert(1)</script>")
    message = notify.render(notify.create_environment(None), item, "html")

    assert "<script>" not in message.body
    assert "&lt;script&gt;" in message.body
    assert '<img src="https://img/x.png"' in message.body


def test_markdown_and_text_bodies():
    env = notify.create_environment(None)
    markdown = notify.render(env, make_item(), "markdown")
    text = notify.render(env, make_item(), "text")

    assert markdown.title == "[Addon files] Cool Addon"
    assert "![Cool Addon](https://img/x.png)" in markdown.body
    assert "**" not in text.body


def test_user_template_overrides_builtin(tmp_path):
    (tmp_path / "title.j2").write_text("Custom: {{ item.title }}", encoding="utf-8")
    message = notify.render(notify.create_environment(tmp_path), make_item(), "markdown")
    assert message.title == "Custom: Cool Addon"


# Sending


class FakeResponse:
    def __init__(self, status_code, data=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._data = data or {}
        self.text = json.dumps(self._data)

    def json(self):
        return self._data


def test_send_discord_retries_on_rate_limit(monkeypatch):
    responses = [FakeResponse(429, {"retry_after": 0.01}), FakeResponse(204)]
    posted = []
    monkeypatch.setattr(notify.requests, "post", lambda url, json, timeout: posted.append(json) or responses.pop(0))
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)

    assert notify.send_discord(DISCORD_URL, {"content": "hi"})
    assert len(posted) == 2


def test_send_discord_reports_errors(monkeypatch):
    monkeypatch.setattr(notify.requests, "post", lambda url, json, timeout: FakeResponse(400, {"message": "bad"}))
    assert not notify.send_discord(DISCORD_URL, {"content": "hi"})


# Check cycle


@pytest.fixture
def fake_feed(monkeypatch):
    sent: list[str] = []
    result = {"items": [make_item("A"), make_item("B")], "fail_on": None, "fetch_fails": False}

    def fetch(url, feed_type):
        if result["fetch_fails"]:
            raise ConnectionError("moddb down")
        return result["items"]

    def send(url, message):
        if result["fail_on"] and message.title.endswith(result["fail_on"]):
            return False
        sent.append(message.title)
        return True

    monkeypatch.setattr(feed, "fetch_items", fetch)
    monkeypatch.setattr(notify, "send", send)
    return result, sent


def check(settings, state):
    app.check(settings, notify.create_environment(None), state, "addons")


def test_first_run_remembers_current_items(settings, fake_feed):
    _, sent = fake_feed
    state = State()
    check(settings, state)

    assert state.seen == {"addons": ["downloads-A", "downloads-B"]}
    assert sent == []


def test_only_unseen_items_are_sent(settings, fake_feed):
    _, sent = fake_feed
    state = State(seen={"addons": ["downloads-A"]})
    check(settings, state)

    assert sent == ["[Addon files] B"]
    assert state.seen == {"addons": ["downloads-A", "downloads-B"]}


def test_late_approved_item_with_old_date_is_sent(settings, fake_feed):
    """An item that appears in the feed only after newer ones (e.g. approved later) must not be missed."""
    result, sent = fake_feed
    state = State()
    check(settings, state)

    late = Item(**{**make_item("Late").__dict__, "date": datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)})
    result["items"] = [late, *result["items"]]
    check(settings, state)

    assert sent == ["[Addon files] Late"]


def test_max_items_keeps_the_newest_and_skips_the_rest(tmp_path, fake_feed):
    result, sent = fake_feed
    result["items"] = [make_item(str(i)) for i in range(5)]
    settings = Settings(page=PAGE, notify_url=DISCORD_URL, state_dir=tmp_path, max_items=2)
    state = State(seen={"addons": []})
    check(settings, state)

    assert sent == ["[Addon files] 3", "[Addon files] 4"]
    assert sorted(state.seen["addons"]) == [f"downloads-{i}" for i in range(5)]


def test_fetch_failure_keeps_state(settings, fake_feed):
    result, _ = fake_feed
    result["fetch_fails"] = True
    state = State()
    check(settings, state)

    assert state.seen == {}  # first run is repeated next time


def test_send_failure_retries_from_failed_item(settings, fake_feed):
    result, sent = fake_feed
    result["fail_on"] = "B"
    state = State(seen={"addons": []})
    check(settings, state)

    assert sent == ["[Addon files] A"]
    assert state.seen == {"addons": ["downloads-A"]}


# CLI


def test_preview_works_without_full_config(capsys, monkeypatch):
    monkeypatch.setenv("MFN_NOTIFY_URL", DISCORD_URL)
    monkeypatch.setattr("sys.argv", ["moddb-feed-notifier", "--preview"])
    __main__.main()

    output = capsys.readouterr().out
    assert "(discord)" in output
    assert '"embeds"' in output


def test_preview_reports_invalid_json(tmp_path, monkeypatch):
    (tmp_path / "discord.json.j2").write_text('{"content": {{ item.title }}}', encoding="utf-8")
    monkeypatch.setenv("MFN_TEMPLATE_DIR", str(tmp_path))
    monkeypatch.setenv("MFN_MESSAGE_FORMAT", "discord")
    monkeypatch.setattr("sys.argv", ["moddb-feed-notifier", "--preview"])

    with pytest.raises(SystemExit, match="does not produce valid JSON"):
        __main__.main()


def test_invalid_config_lists_all_errors(monkeypatch):
    monkeypatch.setenv("MFN_NOTIFY_URL", APPRISE_URL)
    monkeypatch.setenv("MFN_MESSAGE_FORMAT", "discord")
    monkeypatch.setattr("sys.argv", ["moddb-feed-notifier", "--once"])

    with pytest.raises(SystemExit, match=r"MFN_PAGE: Field required"):
        __main__.main()


def test_template_settings_alone():
    assert TemplateSettings().message_format == "markdown"


# HTTP stack


def test_moddb_http_stack_works():
    """Catches incompatible versions of curl_adapter, curl_cffi and urllib3, using a local server only."""
    import http.server
    import threading

    import moddb
    import requests

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.end_headers()
            self.wfile.write(RSS.encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        response = moddb.utils.request(requests.Request("GET", f"http://127.0.0.1:{server.server_port}/"))
        assert len(feed.parse_feed(response.text, "addons")) == 2
    finally:
        server.shutdown()
