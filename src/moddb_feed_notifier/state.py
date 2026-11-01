from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

STATE_FILE_NAME = "state.json"
# Feeds show about 10 items; the extra room keeps deleted items from bringing older, already sent ones back
MAX_SEEN_IDS = 50


@dataclass
class State:
    """Persisted between runs: the IDs of the items already seen in each feed, oldest first."""

    seen: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, state_dir: Path) -> State:
        path = state_dir / STATE_FILE_NAME
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(seen=data.get("seen", {}))

    def mark_seen(self, feed_type: str, ids: list[str]) -> None:
        seen = [i for i in self.seen.get(feed_type, []) if i not in ids] + ids
        self.seen[feed_type] = seen[-MAX_SEEN_IDS:]

    def save(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        path = state_dir / STATE_FILE_NAME
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
