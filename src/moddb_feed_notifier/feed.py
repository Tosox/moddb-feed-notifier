from __future__ import annotations

import datetime
import email.utils
import html
import re
from dataclasses import dataclass
from xml.etree import ElementTree

import moddb
import requests

NAMESPACES = {"media": "http://search.yahoo.com/mrss/"}
XML_ENTITIES = {"amp", "lt", "gt", "apos", "quot"}
# "Addon files RSS feed - Tosox - ModDB", or "Addon files RSS feed - ModDB" for site-wide feeds
CHANNEL_TITLE_RE = re.compile(r"^(?P<section>.+?) RSS feed - (?:(?P<page>.+) - )?ModDB$")


@dataclass(frozen=True)
class Feed:
    title: str
    section: str
    page: str
    url: str


@dataclass(frozen=True)
class Item:
    id: str
    type: str
    feed: Feed
    title: str
    description: str
    url: str
    image: str | None
    date: datetime.datetime


def fix_broken_entities(xml: str) -> str:
    """ModDB feeds contain HTML entities like &nbsp; that are invalid in XML; escape them."""
    return re.sub(
        r"&([a-zA-Z][a-zA-Z0-9]*);",
        lambda m: m.group(0) if m.group(1) in XML_ENTITIES else f"&amp;{m.group(1)};",
        xml,
    )


def required_text(node: ElementTree.Element, path: str) -> str:
    value = node.findtext(path, namespaces=NAMESPACES)
    if value is None:
        raise ValueError(f"<{path}> missing in feed <{node.tag}>")
    return value.strip()


def html_to_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def parse_channel(channel: ElementTree.Element) -> Feed:
    title = " ".join(required_text(channel, "title").split())
    match = CHANNEL_TITLE_RE.match(title)
    if not match:
        raise ValueError(f"unexpected feed title {title!r}")
    return Feed(
        title=title, section=match["section"], page=match["page"] or "ModDB", url=required_text(channel, "link")
    )


def parse_feed(xml: str, feed_type: str) -> list[Item]:
    """Parse a ModDB RSS feed, oldest item first.

    Items with media (add-ons, articles, ...) carry a plain-text media:description and the full-size image in
    media:content; others (e.g. reviews) only have an HTML <description> and no image.
    """
    root = ElementTree.fromstring(fix_broken_entities(xml))
    channel = root.find("channel")
    if channel is None:
        raise ValueError("<channel> missing in feed")
    feed = parse_channel(channel)
    items = []
    for node in channel.iter("item"):
        media = node.find("media:content", NAMESPACES)
        if media is not None:
            description = html.unescape(required_text(media, "media:description"))
        else:
            description = html_to_text(required_text(node, "description"))
        items.append(
            Item(
                id=required_text(node, "guid"),
                type=feed_type,
                feed=feed,
                title=" ".join(required_text(node, "title").split()),
                description=description.strip(),
                url=required_text(node, "link"),
                image=media.get("url") if media is not None else None,
                date=email.utils.parsedate_to_datetime(required_text(node, "pubDate")).astimezone(datetime.UTC),
            )
        )
    items.sort(key=lambda item: item.date)
    return items


def fetch_items(feed_url: str, feed_type: str) -> list[Item]:
    """Return all items currently in the feed, oldest first.

    Raises on any network or parsing error so the caller does not change its state.
    """
    response = moddb.utils.request(requests.Request("GET", feed_url))
    return parse_feed(response.text, feed_type)
