# SPDX-FileCopyrightText: 2026 rodavrow
# SPDX-License-Identifier: MIT
"""Helpers for tests that run a request through the router with fake agents behind it."""

import asyncio
import copy
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

from custom_components.voice_persona_router.const import DOMAIN

MAIN_AGENT = "conversation.main_agent"
MEMORY_AGENT = "conversation.memory_writer"
REFUSAL_AGENT = "conversation.refusal_writer"

BASE_OPTIONS: dict[str, Any] = {
    "agents": {"agent": MAIN_AGENT},
    # Built-in commands off, so every request reaches the fake main agent.
    "local": {"enabled": False, "leave_questions": True},
    "memory": {
        "enabled": True,
        "agent": MEMORY_AGENT,
        "auto_save": True,
        "max_items": 50,
        "use_global": True,
    },
    "owner": {"name": "Alex", "persona": "The person speaking is Alex."},
    "partner": {"name": "Sam", "persona": "The person speaking is Sam."},
    "strangers": {"mode": "fixed", "fixed_replies": "The answer is no."},
    "near_miss": {"enabled": False, "min_score": 0.5},
    "advanced": {"rule": "Names are labels.", "wait_seconds": 0, "no_helper_role": "owner"},
}


def options_with(**sections: dict[str, Any]) -> dict[str, Any]:
    """BASE_OPTIONS with some keys of some sections replaced."""
    options = copy.deepcopy(BASE_OPTIONS)
    for name, changes in sections.items():
        options[name] = {**options.get(name, {}), **changes}
    return options


async def add_router(
    hass: HomeAssistant, options: dict[str, Any] | None = None, title: str = "Kitchen assistant"
) -> MockConfigEntry:
    assert await async_setup_component(hass, "homeassistant", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title,
        data={"name": title, "agent": MAIN_AGENT},
        options=copy.deepcopy(BASE_OPTIONS if options is None else options),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def router_entity_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("conversation", DOMAIN, entry.entry_id)
    assert entity_id is not None
    return entity_id


def _result(text: str, *, error: bool = False) -> conversation.ConversationResult:
    response = intent.IntentResponse(language="en")
    if error:
        response.async_set_error(intent.IntentResponseErrorCode.UNKNOWN, text)
    else:
        response.async_set_speech(text)
    return conversation.ConversationResult(response=response, conversation_id="fake")


@dataclass
class FakeAgents:
    """Stands in for conversation.async_converse: a main agent and a memory agent."""

    main_reply: str = "Noted."
    main_error: bool = False
    memory_reply: str = '{"add": [], "remove": []}'
    # When set, the memory agent waits for it before answering.
    memory_gate: asyncio.Event | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def converse(self, hass, text, conversation_id, context, **kwargs):
        call = {"text": text, "conversation_id": conversation_id, **kwargs}
        self.calls.append(call)
        if kwargs.get("agent_id") == MEMORY_AGENT:
            if self.memory_gate is not None:
                await self.memory_gate.wait()
            return _result(self.memory_reply)
        return _result(self.main_reply, error=self.main_error)

    def calls_to(self, agent_id: str) -> list[dict[str, Any]]:
        return [call for call in self.calls if call.get("agent_id") == agent_id]

    @property
    def main_prompt(self) -> str:
        (call,) = self.calls_to(MAIN_AGENT)
        return call.get("extra_system_prompt") or ""

    def patched(self):
        return patch.object(conversation, "async_converse", self.converse)


async def ask(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    text: str,
    *,
    device_id: str | None = None,
) -> conversation.ConversationResult:
    """Send one request straight to the router entity, as a voice assistant would."""
    entity_id = router_entity_id(hass, entry)
    entity = hass.data[conversation.DATA_COMPONENT].get_entity(entity_id)
    assert entity is not None
    return await entity.async_process(
        conversation.ConversationInput(
            text=text,
            context=Context(),
            conversation_id=None,
            device_id=device_id,
            satellite_id=None,
            language="en",
            agent_id=entity_id,
        )
    )
