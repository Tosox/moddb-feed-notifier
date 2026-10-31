from __future__ import annotations

import datetime
import email.utils
import html
import logging
import re
from dataclasses import dataclass
from xml.etree import ElementTree

import moddb
import requests

log = logging.getLogger(__name__)

NAMESPACES = {"media": "http://search.yahoo.com/mrss/"}
XML_ENTITIES = {"amp", "lt", "gt", "apos", "quot"}
# e.g. "Addon files RSS feed - Tosox - ModDB"
CHANNEL_TITLE_RE = re.compile(r"^(?P<section>.+?) RSS feed - (?P<page>.+) - ModDB$")


@dataclass(frozen=True)
class Feed:
    title: str
    section: str
    page: str
    url: str


@dataclass(frozen=True)
class Item:
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


def parse_date(value: str) -> datetime.datetime:
    """Parse an RSS (RFC 2822) date into UTC; dates without a time zone are assumed to be UTC."""
    date = email.utils.parsedate_to_datetime(value)
    if date.tzinfo is None:
        return date.replace(tzinfo=datetime.UTC)
    return date.astimezone(datetime.UTC)


def html_to_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def parse_channel(channel: ElementTree.Element | None, feed_type: str) -> Feed:
    if channel is None:
        channel = ElementTree.Element("channel")
    title = " ".join((channel.findtext("title") or "").split())
    url = (channel.findtext("link") or "").strip()
    match = CHANNEL_TITLE_RE.match(title)
    if match:
        return Feed(title=title, section=match["section"], page=match["page"], url=url)
    return Feed(title=title, section=feed_type.capitalize(), page=title, url=url)


def parse_feed(xml: str, feed_type: str) -> list[Item]:
    """Parse a ModDB RSS feed, oldest item first.

    Items with media (add-ons, articles, ...) carry a plain-text media:description and the full-size image in
    media:content; others (e.g. reviews) only have an HTML <description>.
    """
    root = ElementTree.fromstring(fix_broken_entities(xml))
    feed = parse_channel(root.find("channel"), feed_type)
    items = []
    for node in root.iter("item"):
        media_description = node.findtext("media:content/media:description", namespaces=NAMESPACES)
        if media_description is not None:
            description = html.unescape(media_description)
        else:
            description = html_to_text(node.findtext("description") or "")
        image_node = node.find("media:content", NAMESPACES)
        if image_node is None:
            image_node = node.find("enclosure")
        items.append(
            Item(
                type=feed_type,
                feed=feed,
                title=" ".join((node.findtext("title") or "").split()),
                description=description.strip(),
                url=(node.findtext("link") or "").strip(),
                image=image_node.get("url") if image_node is not None else None,
                date=parse_date(node.findtext("pubDate") or ""),
            )
        )
    items.sort(key=lambda item: item.date)
    return items


def fetch_new_items(feed_url: str, feed_type: str, since: int) -> list[Item]:
    """Return all items published after `since` (Unix timestamp), oldest first.

    Raises on any network or parsing error so the caller does not advance its state.
    """
    response = moddb.utils.request(requests.Request("GET", feed_url))
    return [item for item in parse_feed(response.text, feed_type) if item.date.timestamp() > since]
