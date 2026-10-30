"""Shared data contracts and config loading."""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

SECTIONS = ["Europe / Russia", "Middle East", "Indo-Pacific", "North America", "Other Regions"]


@dataclass
class Item:
    id: str
    source_id: str
    source: str
    origin: str  # original reporter; syndicated copies share an origin
    url: str
    title: str
    published: str  # ISO 8601 UTC
    summary: str
    region: str
    category: str
    ingested: str
    reliability: float = 0.7
    official: bool = False
    event_time: str | None = None  # only set when a feed states it explicitly
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_yaml(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def log_event(event: str, **kw: Any) -> None:
    """Structured (JSON-lines) operational log on stderr."""
    print(json.dumps({"event": event, **kw}, default=str, sort_keys=True), file=sys.stderr)


logging.getLogger().setLevel(logging.WARNING)
