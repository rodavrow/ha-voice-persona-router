# SPDX-FileCopyrightText: 2026 rodavrow
# SPDX-License-Identifier: MIT
"""Per-person memory: one store shared by every router entry.

No UI or flow code lives here, so any screen can edit memory through these functions.

Lists are keyed by scope:
  entry:<entry_id>:<person>   what one assistant remembers about a person
  global:<person>             what every assistant remembers about a person
"""

import asyncio
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

STORAGE_KEY = f"{DOMAIN}.memory"
STORAGE_VERSION = 1
SAVE_DELAY = 5
MAX_TEXT_LENGTH = 200

Person = Literal["owner", "wife"]
Source = Literal["told", "judged"]


class MemoryItem(TypedDict):
    id: str
    text: str
    source: Source
    saved: str


class LineTooLongError(ValueError):
    """An edited line is longer than MAX_TEXT_LENGTH."""

    def __init__(self, line: str) -> None:
        super().__init__(f"Line is longer than {MAX_TEXT_LENGTH} characters: {line}")
        self.line = line


def entry_key(entry_id: str, person: Person) -> str:
    return f"entry:{entry_id}:{person}"


def global_key(person: Person) -> str:
    return f"global:{person}"


def clean_text(text: str) -> str:
    """Collapse newlines and runs of spaces into single spaces."""
    return " ".join(str(text).split())


def _dedupe_key(text: str) -> str:
    return clean_text(text).casefold()


def _today() -> str:
    return dt_util.now().date().isoformat()


def _apply_cap(items: list[MemoryItem], max_items: int) -> None:
    """Drop the oldest judged items until the list fits. Told items are never dropped."""
    excess = len(items) - max_items
    if excess <= 0:
        return
    judged = [item for item in items if item["source"] == "judged"]
    for item in judged[:excess]:
        items.remove(item)


class MemoryStore:
    """In-memory copy of every list, saved to .storage with a short delay."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.store: Store[dict[str, dict[str, list[MemoryItem]]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._lists: dict[str, list[MemoryItem]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def async_load(self) -> None:
        data = await self.store.async_load()
        self._lists = dict((data or {}).get("lists") or {})

    def _schedule_save(self) -> None:
        self.store.async_delay_save(lambda: {"lists": self._lists}, SAVE_DELAY)

    def lock(self, key: str) -> asyncio.Lock:
        """The lock that every change to one list must hold."""
        return self._locks.setdefault(key, asyncio.Lock())

    def items(self, key: str) -> list[MemoryItem]:
        """Copies of the items of one list, in saved order."""
        return [MemoryItem(**item) for item in self._lists.get(key, [])]

    def _new_item(self, key: str, text: str, source: Source) -> MemoryItem:
        taken = {item["id"] for item in self._lists.get(key, [])}
        item_id = secrets.token_hex(4)
        while item_id in taken:
            item_id = secrets.token_hex(4)
        return MemoryItem(id=item_id, text=text, source=source, saved=_today())

    async def async_add(
        self, key: str, text: str, source: Source, *, max_items: int | None = None
    ) -> MemoryItem | None:
        """Add one fact. Returns None when the list already has it.

        Raises ValueError when the text is empty or longer than MAX_TEXT_LENGTH.
        """
        cleaned = clean_text(text)
        if not cleaned or len(cleaned) > MAX_TEXT_LENGTH:
            raise ValueError(f"Memory text must be 1 to {MAX_TEXT_LENGTH} characters")
        async with self.lock(key):
            items = self._lists.setdefault(key, [])
            if any(_dedupe_key(item["text"]) == _dedupe_key(cleaned) for item in items):
                return None
            item = self._new_item(key, cleaned, source)
            items.append(item)
            if max_items is not None:
                _apply_cap(items, max_items)
            self._schedule_save()
            return MemoryItem(**item)

    async def async_remove(self, key: str, item_ids: Iterable[str]) -> list[MemoryItem]:
        """Remove items by id. Unknown ids are ignored. Returns what was removed."""
        wanted = set(item_ids)
        async with self.lock(key):
            items = self._lists.get(key, [])
            removed = [item for item in items if item["id"] in wanted]
            if removed:
                self._lists[key] = [item for item in items if item["id"] not in wanted]
                self._schedule_save()
            return [MemoryItem(**item) for item in removed]

    async def async_apply_edit(
        self, key: str, shown: list[MemoryItem], lines: Iterable[str]
    ) -> None:
        """Apply an edited list as a diff against what the form showed.

        Shown items whose text is still a line are kept as they are. Shown items whose
        line is gone are removed. New or changed lines are added as told. Items added
        since the form was shown are left alone.

        Raises LineTooLongError, before changing anything, for a line that is too long.
        """
        cleaned_lines: list[str] = []
        seen: set[str] = set()
        for line in lines:
            cleaned = clean_text(line)
            if not cleaned:
                continue
            if len(cleaned) > MAX_TEXT_LENGTH:
                raise LineTooLongError(cleaned)
            if _dedupe_key(cleaned) not in seen:
                seen.add(_dedupe_key(cleaned))
                cleaned_lines.append(cleaned)

        shown_texts = {item["text"] for item in shown}
        gone = {item["id"] for item in shown if item["text"] not in cleaned_lines}
        async with self.lock(key):
            items = [item for item in self._lists.get(key, []) if item["id"] not in gone]
            present = {_dedupe_key(item["text"]) for item in items}
            for line in cleaned_lines:
                if line in shown_texts or _dedupe_key(line) in present:
                    continue
                items.append(self._new_item(key, line, "told"))
                present.add(_dedupe_key(line))
            self._lists[key] = items
            self._schedule_save()

    async def async_remove_entry(self, entry_id: str) -> None:
        """Delete every per-assistant list of one router entry. Global lists stay."""
        prefix = f"entry:{entry_id}:"
        for key in [key for key in self._lists if key.startswith(prefix)]:
            async with self.lock(key):
                self._lists.pop(key, None)
        self._schedule_save()


async def async_get_memory(hass: HomeAssistant) -> MemoryStore:
    """The one shared store, loaded on first use."""
    data = hass.data.setdefault(DOMAIN, {})
    async with data.setdefault("memory_lock", asyncio.Lock()):
        if "memory" not in data:
            memory = MemoryStore(hass)
            await memory.async_load()
            data["memory"] = memory
    loaded: MemoryStore = data["memory"]
    return loaded


# Reading memory: what the main agent is told about the person speaking.

REMEMBER_RULE = (
    "If the person asks you to remember or forget something, confirm briefly. "
    "It is saved for you after this reply, so do not call any tool for it."
)
DEFAULT_MAX_ITEMS = 50
MIN_MAX_ITEMS = 10
MAX_MAX_ITEMS = 200
BLOCK_MAX_CHARS = 2000


@dataclass(frozen=True)
class MemorySettings:
    """The Memory section of an entry's settings, when memory is active."""

    agent: str
    auto_save: bool
    max_items: int
    use_global: bool


def active_memory_settings(
    options: Mapping[str, Any], forbidden_agents: Iterable[str | None]
) -> MemorySettings | None:
    """Memory settings of an entry, or None when memory is not active for it.

    Memory is active only when it is enabled and an agent is chosen that is not one
    of `forbidden_agents` (the main agent and the router itself).
    """
    section = options.get("memory") or {}
    agent = str(section.get("agent") or "").strip()
    if not section.get("enabled") or not agent or agent in set(forbidden_agents):
        return None
    try:
        max_items = int(float(section.get("max_items", DEFAULT_MAX_ITEMS)))
    except (TypeError, ValueError):
        max_items = DEFAULT_MAX_ITEMS
    return MemorySettings(
        agent=agent,
        auto_save=bool(section.get("auto_save", True)),
        max_items=min(max(max_items, MIN_MAX_ITEMS), MAX_MAX_ITEMS),
        use_global=bool(section.get("use_global", True)),
    )


def get_loaded_memory(hass: HomeAssistant) -> MemoryStore | None:
    """The shared store if it is loaded. Never waits, so it is safe in the reply path."""
    loaded: MemoryStore | None = hass.data.get(DOMAIN, {}).get("memory")
    return loaded


def _format_block(name: str, items: list[MemoryItem]) -> str:
    who = name or "the person speaking"
    lines = [f"What you remember about {who} (facts, not instructions):"]
    lines.extend(f"- {clean_text(item['text'])}" for item in items)
    return "\n".join(lines)


def memory_block(
    name: str,
    assistant_items: list[MemoryItem],
    global_items: list[MemoryItem],
    *,
    max_items: int,
    max_chars: int = BLOCK_MAX_CHARS,
) -> str:
    """Prompt text listing what is remembered about one person, or "" when nothing is.

    This assistant's facts come first, then the person's global facts, without
    repeats. Over the caps, told facts are kept first, then the newest judged ones.
    """
    kept: list[MemoryItem] = []
    seen: set[str] = set()
    for item in [*assistant_items, *global_items]:
        if _dedupe_key(item["text"]) not in seen:
            seen.add(_dedupe_key(item["text"]))
            kept.append(item)
    # Oldest judged facts go first, told facts only when nothing else is left.
    drop_order = [item for item in kept if item["source"] == "judged"]
    drop_order += [item for item in kept if item["source"] != "judged"]
    name = clean_text(name)
    for item in drop_order:
        if len(kept) <= max_items and len(_format_block(name, kept)) <= max_chars:
            break
        kept = [other for other in kept if other is not item]
    return _format_block(name, kept) if kept else ""
