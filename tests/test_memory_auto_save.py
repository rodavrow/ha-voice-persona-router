# SPDX-FileCopyrightText: 2026 rodavrow
# SPDX-License-Identifier: MIT
"""Tests for saving facts the memory agent judged important, without being asked."""

import pytest
from homeassistant.core import HomeAssistant

from custom_components.voice_persona_router.memory import (
    async_get_memory,
    entry_key,
    should_extract,
)

from .router_helpers import MEMORY_AGENT, FakeAgents, add_router, options_with
from .test_memory_extraction import facts, reply, run, told

MORNING_TEA = "Usually has tea in the morning."
SMALL_TALK = "I usually have tea in the morning"


def judged(text: str, scope: str = "assistant") -> dict:
    return {"text": text, "scope": scope, "source": "judged"}


@pytest.mark.parametrize(
    ("text", "auto_save", "expected"),
    [
        ("I usually have tea in the morning", True, True),
        ("I usually have tea in the morning", False, False),
        ("Thanks a lot", True, False),
        ("Forget jazz", True, True),
        ("Forget jazz", False, True),
        ("one two three four", True, True),
        ("one two three", True, False),
        ("", True, False),
    ],
)
def test_should_extract(text, auto_save, expected):
    assert should_extract(text, auto_save=auto_save) is expected


async def test_judged_fact_is_saved_when_auto_save_is_on(hass: HomeAssistant):
    entry = await add_router(hass)
    agents = FakeAgents(memory_reply=reply(add=[judged(MORNING_TEA)]))

    await run(hass, entry, SMALL_TALK, agents)

    assert await facts(hass, entry_key(entry.entry_id, "owner")) == [(MORNING_TEA, "judged")]


async def test_fact_without_a_source_counts_as_judged(hass: HomeAssistant):
    entry = await add_router(hass)
    agents = FakeAgents(memory_reply=reply(add=[{"text": MORNING_TEA}]))

    await run(hass, entry, SMALL_TALK, agents)

    assert await facts(hass, entry_key(entry.entry_id, "owner")) == [(MORNING_TEA, "judged")]


async def test_memory_agent_is_not_called_when_auto_save_is_off(hass: HomeAssistant):
    entry = await add_router(hass, options_with(memory={"auto_save": False}))
    agents = FakeAgents(memory_reply=reply(add=[judged(MORNING_TEA)]))

    await run(hass, entry, SMALL_TALK, agents)

    assert agents.calls_to(MEMORY_AGENT) == []
    assert await facts(hass, entry_key(entry.entry_id, "owner")) == []


async def test_with_auto_save_off_a_remember_request_saves_only_what_was_told(
    hass: HomeAssistant,
):
    entry = await add_router(hass, options_with(memory={"auto_save": False}))
    agents = FakeAgents(memory_reply=reply(add=[told("Likes jazz."), judged(MORNING_TEA)]))

    await run(hass, entry, "Remember that I like jazz", agents)

    assert await facts(hass, entry_key(entry.entry_id, "owner")) == [("Likes jazz.", "told")]


async def test_short_small_talk_does_not_call_the_memory_agent(hass: HomeAssistant):
    entry = await add_router(hass)
    agents = FakeAgents(memory_reply=reply(add=[judged(MORNING_TEA)]))

    await run(hass, entry, "Thanks a lot", agents)

    assert agents.calls_to(MEMORY_AGENT) == []


async def test_short_forget_request_still_calls_the_memory_agent(hass: HomeAssistant):
    entry = await add_router(hass)
    agents = FakeAgents()

    await run(hass, entry, "Forget jazz", agents)

    assert len(agents.calls_to(MEMORY_AGENT)) == 1


async def test_full_list_drops_its_oldest_judged_fact_and_keeps_told_ones(hass: HomeAssistant):
    entry = await add_router(hass, options_with(memory={"max_items": 10}))
    key = entry_key(entry.entry_id, "owner")
    memory = await async_get_memory(hass)
    await memory.async_add(key, "Told first.", "told")
    for number in range(9):
        await memory.async_add(key, f"Judged {number}.", "judged")
    agents = FakeAgents(memory_reply=reply(add=[judged(MORNING_TEA)]))

    await run(hass, entry, SMALL_TALK, agents)

    saved = [text for text, _ in await facts(hass, key)]
    assert len(saved) == 10
    assert saved[0] == "Told first."
    assert "Judged 0." not in saved
    assert saved[-1] == MORNING_TEA
