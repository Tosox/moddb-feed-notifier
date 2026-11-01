# ModDB Feed Notifier

Get notified about new add-ons, articles, files, videos, images and more on [ModDB](https://www.moddb.com): as rich Discord embeds, or by email, Telegram, ntfy and [100+ other services supported by Apprise](https://appriseit.com/services/).

- 📰 Watches any ModDB page: mods, games, members and more
- 🎨 Rich Discord embeds with image, fully customizable
- 🧩 Configured entirely through environment variables
- ✏️ Customizable messages with Jinja2 templates
- 🐳 Ready-to-use Docker image

## 🚀 Quick start (Docker)

Create a `docker-compose.yaml`:

```yaml
services:
  moddb-feed-notifier:
    image: ghcr.io/tosox/moddb-feed-notifier:latest
    container_name: moddb-feed-notifier
    restart: unless-stopped
    environment:
      MFN_PAGE: https://www.moddb.com/mods/stalker-anomaly
      MFN_TYPES: addons,articles
      MFN_NOTIFY_URL: https://discord.com/api/webhooks/123456789/your-webhook-token
    volumes:
      - state:/app/state

volumes:
  state:
```

Then start it:

```bash
docker compose up -d
docker compose logs -f
```

On the first run the notifier only remembers which items are already in the feeds, so you won't get flooded with old ones. From then on, every new item is posted, including items that show up late, e.g. add-ons that were approved by a moderator hours after they were submitted.

## ⚙️ Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `MFN_PAGE` | ✅ | | ModDB page whose feeds are watched, e.g. `https://www.moddb.com/mods/stalker-anomaly` or `https://www.moddb.com/members/tosox`. Use `https://www.moddb.com` for site-wide feeds. |
| `MFN_NOTIFY_URL` | ✅ | | A Discord webhook URL, or any [Apprise URL](https://appriseit.com/services/). |
| `MFN_TYPES` | | `addons` | Feeds to watch, comma-separated, e.g. `addons,articles,downloads,videos,images`. |
| `MFN_INTERVAL` | | `30` | Minutes between checks. |
| `MFN_MAX_ITEMS` | | `10` | Most items sent per feed and check, e.g. after a longer downtime. Older ones are skipped. |
| `MFN_MESSAGE_FORMAT` | | `discord` for Discord webhooks, otherwise `markdown` | `discord`, `markdown`, `html` or `text`, see *Custom messages* below. |
| `MFN_TEMPLATE_DIR` | | | Folder with your own message templates, see below. |
| `MFN_STATE_DIR` | | `./state` (`/app/state` in Docker) | Where the IDs of items already seen in each feed are stored. |
| `MFN_LOG_LEVEL` | | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. Libraries used by the notifier only log warnings and errors. |

Missing or invalid values are listed at startup, so a bad configuration fails right away with a clear message.

Feeds are read from `https://rss.moddb.com/<page>/<type>/feed/rss.xml`. Which types exist depends on the page; a feed that doesn't exist shows up as an error in the log.

One container watches one page and notifies one target. For more, run one container per page or target, each with its own state volume.

### 📬 Notification URLs

| Service | URL |
|---|---|
| Discord (rich embeds) | `https://discord.com/api/webhooks/<id>/<token>` (*Server Settings → Integrations → Webhooks*) |
| Gmail | `mailtos://you:app-password@gmail.com` ([create an app password](https://support.google.com/accounts/answer/185833)) |
| Telegram | `tgram://bot_token/chat_id` |
| ntfy | `ntfy://ntfy.sh/your-topic` |

See the [Apprise documentation](https://appriseit.com/services/) for all other services. Special characters in passwords must be [URL-encoded](https://www.urlencoder.org/), e.g. `@` becomes `%40`.

## ✏️ Custom messages

Messages are rendered from [Jinja2](https://jinja.palletsprojects.com/en/stable/templates/) templates, one message per new item:

| `MFN_MESSAGE_FORMAT` | Template | Use for |
|---|---|---|
| `discord` | `discord.json.j2` | Discord webhooks. The template is the complete [webhook payload](https://discord.com/developers/docs/resources/webhook#execute-webhook), e.g. with embeds. |
| `markdown` | `title.j2` + `body.md.j2` | Most Apprise services. Apprise converts it as needed. |
| `html` | `title.j2` + `body.html.j2` | Styled emails. Use inline styles (`style="..."`), since many mail clients ignore `<style>` blocks. |
| `text` | `title.j2` + `body.txt.j2` | Services without any formatting, e.g. SMS. |

In `body.html.j2` all values are HTML-escaped automatically. In `discord.json.j2`, insert values with `tojson` so quotes and line breaks can't break the JSON:

```jinja
"title": {{ item.title | truncate(256, true, "…", 0) | tojson }},
```

To change them, put your own versions in a folder and point `MFN_TEMPLATE_DIR` to it. Files you don't provide fall back to the [built-in templates](src/moddb_feed_notifier/templates).

```yaml
    environment:
      MFN_TEMPLATE_DIR: /app/templates
    volumes:
      - ./templates:/app/templates:ro
```

Available in all templates:

| Variable | Description |
|---|---|
| `item.title` | Title of the item |
| `item.description` | Short description |
| `item.url` | Link to the item on ModDB |
| `item.image` | Preview image URL, or empty if there is none (`{% if item.image %}`) |
| `item.date` | When it was published, in UTC (`datetime`, e.g. `{{ item.date.strftime("%d.%m.%Y") }}`) |
| `item.type` | Feed type from `MFN_TYPES`, e.g. `addons` |
| `item.feed.section` | Name of the feed's section on ModDB, e.g. `Addon files` |
| `item.feed.page` | Name of the watched page, e.g. `Tosox` |
| `item.feed.url` | Link to the feed's overview page, e.g. `https://www.moddb.com/members/tosox/addons` |
| `item.feed.title` | Full feed title, e.g. `Addon files RSS feed - Tosox - ModDB` |

There is also a `quote` filter that turns text into a Markdown quote: `{{ item.description | quote }}`.

To see how your messages look, render them with sample data. Nothing is fetched or sent:

```bash
docker run --rm -e MFN_MESSAGE_FORMAT=discord -e MFN_TEMPLATE_DIR=/app/templates -v ./templates:/app/templates:ro \
  ghcr.io/tosox/moddb-feed-notifier:latest moddb-feed-notifier --preview
```

Template errors, including invalid JSON in `discord.json.j2`, are reported before anything is sent.

## 🐍 Running without Docker

Requires Python 3.12+.

```bash
git clone https://github.com/Tosox/moddb-feed-notifier.git
cd moddb-feed-notifier
pip install .
cp .env.example .env           # then fill in your values
moddb-feed-notifier            # runs until stopped
moddb-feed-notifier --once     # checks a single time and exits
moddb-feed-notifier --preview  # shows a message rendered with sample data
```

## 🛠️ Development

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format .
```

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.
