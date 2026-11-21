# SPDX-FileCopyrightText: 2026 rodavrow
# SPDX-License-Identifier: MIT
"""Tests for the background pass that decides what to remember after a reply."""

import asyncio
import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.voice_persona_router.memory import (
    async_get_memory,
    entry_key,
    global_key,
    has_memory_keyword,
    looks_secret,
    parse_extraction,
)

from .router_helpers import MEMORY_AGENT, FakeAgents, add_router, ask, options_with

WARM_LIGHTS = "Prefers the lights warm in the evening."


def reply(add: list[dict] | None = None, remove: list[str] | None = None) -> str:
    return json.dumps({"add": add or [], "remove": remove or []})


def told(text: str, scope: str = "assistant") -> dict:
    return {"text": text, "scope": scope, "source": "told"}


async def run(hass: HomeAssistant, entry, text: str, agents: FakeAgents):
    """Send a request and let the background pass finish."""
    with agents.patched():
        result = await ask(hass, entry, text)
        await hass.async_block_till_done(wait_background_tasks=True)
    return result


async def facts(hass: HomeAssistant, key: str) -> list[tuple[str, str]]:
    memory = await async_get_memory(hass)
    return [(item["text"], item["source"]) for item in memory.items(key)]


async def all_facts(hass: HomeAssistant, entry) -> list[tuple[str, str]]:
    found = []
    for person in ("owner", "wife"):
        found += await facts(hass, entry_key(entry.entry_id, person))
        found += await facts(hass, global_key(person))
    return found


# Pure helpers.


@pytest.mark.parametrize(
    "text",
    [
        "Remember that I like jazz",
        "please FORGET the dentist",
        "Keep in mind that Sam is away",
        "Everyone should know I am vegetarian",
        "Make a note that the bins go out on Monday",
    ],
)
def test_remember_and_forget_requests_are_recognised(text):
    assert has_memory_keyword(text)


@pytest.mark.parametrize("text", ["What is the weather", "Play something unforgettable", ""])
def test_other_requests_are_not_memory_requests(text):
    assert not has_memory_keyword(text)


@pytest.mark.parametrize(
    "text",
    [
        "The alarm code is 4821.",
        "Alex's PIN is 12 34.",
        "The wifi password is sunflower.",
        "Card number 4111 1111 1111 1111.",
        "The account number is 12345678.",
        "The door code is nine one one.",
        "Phone is 0612345678.",
        "The safe opens with 48-21-07.",
    ],
)
def test_secrets_are_recognised(text):
    assert looks_secret(text)


@pytest.mark.parametrize(
    "text",
    [
        "Prefers the lights warm in the evening.",
        "Has a dentist appointment on 2026-12-01 at 14:30.",
        "Was born in 1990.",
        "Is going to Lisbon on 12/03/2027.",
        "Gets up at 6.45 on weekdays.",
        "Has 3 cats and 12 plants.",
    ],
)
def test_ordinary_facts_with_dates_times_and_years_are_not_secrets(text):
    assert not looks_secret(text)


def test_parse_accepts_plain_json():
    assert parse_extraction('{"add": [{"text": "Likes jazz."}], "remove": ["a1"]}') == (
        [{"text": "Likes jazz."}],
        ["a1"],
    )


def test_parse_accepts_json_inside_a_code_fence_with_chatter():
    raw = 'Here you go:\n```json\n{"add": [], "remove": ["g2"]}\n```\nDone.'

    assert parse_extraction(raw) == ([], ["g2"])


@pytest.mark.parametrize(
    "raw",
    ["", "nothing to save", "[1, 2]", '{"add": "x", "remove": []}', '{"add": [], "remove": "a1"}', "{broken"],
)
def test_parse_rejects_anything_else(raw):
    assert parse_extraction(raw) is None


def test_parse_skips_entries_of_the_wrong_type():
    raw = '{"add": [{"text": "Likes jazz."}, "junk", 3], "remove": ["a1", 7, null]}'

    assert parse_extraction(raw) == ([{"text": "Likes jazz."}], ["a1"])


# Explicit remember and forget, through the router.


async def test_remember_request_saves_to_this_assistants_list_as_told(hass: HomeAssistant):
    entry = await add_router(hass)
    agents = FakeAgents(memory_reply=reply(add=[told(WARM_LIGHTS)]))

    await run(hass, entry, "Remember that I prefer the lights warm in the evening", agents)

    assert await facts(hass, entry_key(entry.entry_id, "owner")) == [(WARM_LIGHTS, "told")]
    assert await facts(hass, global_key("owner")) == []


async def test_fact_is_saved_for_the_person_who_spoke(hass: HomeAssistant):
    entry = await add_router(hass, options_with(advanced={"no_helper_role": "wife"}))
    agents = FakeAgents(memory_reply=reply(add=[told("Likes tea.")]))

    await run(hass, entry, "Remember that I like tea", agents)

    assert await facts(hass, entry_key(entry.entry_id, "wife")) == [("Likes tea.", "told")]
    assert await facts(hass, entry_key(entry.entry_id, "owner")) == []


async def test_remember_for_all_assistants_saves_to_the_global_list(hass: HomeAssistant):
    entry = await add_router(hass)
    agents = FakeAgents(memory_reply=reply(add=[told("Is vegetarian.", "global")]))

    await run(hass, entry, "Remember for all the assistants that I am vegetarian", agents)

    assert await facts(hass, global_key("owner")) == [("Is vegetarian.", "told")]
    assert await facts(hass, entry_key(entry.entry_id, "owner")) == []


async def test_global_request_stays_with_this_assistant_when_shared_lists_are_off(
    hass: HomeAssistant,
):
    entry = await add_router(hass, options_with(memory={"use_global": False}))
    agents = FakeAgents(memory_reply=reply(add=[told("Is vegetarian.", "global")]))

    await run(hass, entry, "Remember for all the assistants that I am vegetarian", agents)

    assert await facts(hass, entry_key(entry.entry_id, "owner")) == [("Is vegetarian.", "told")]
    assert await facts(hass, global_key("owner")) == []


async def test_memory_agent_gets_the_exchange_the_name_and_both_lists(hass: HomeAssistant):
    entry = await add_router(hass)
    memory = await async_get_memory(hass)
    await memory.async_add(entry_key(entry.entry_id, "owner"), "Likes jazz.", "told")
    await memory.async_add(global_key("owner"), "Has a cat.", "told")
    await memory.async_add(entry_key(entry.entry_id, "wife"), "Likes tea.", "told")
    agents = FakeAgents(main_reply="I will remember that.")

    await run(hass, entry, "Remember that I prefer the lights warm in the evening", agents)

    (call,) = agents.calls_to(MEMORY_AGENT)
    assert call["conversation_id"] is None
    assert "Remember that I prefer the lights warm in the evening" in call["text"]
    assert "I will remember that." in call["text"]
    prompt = call["extra_system_prompt"]
    assert "Alex" in prompt
    assert "a1: Likes jazz." in prompt
    assert "g1: Has a cat." in prompt
    assert "Likes tea." not in prompt


async def test_forget_request_removes_from_both_lists(hass: HomeAssistant):
    entry = await add_router(hass)
    memory = await async_get_memory(hass)
    await memory.async_add(entry_key(entry.entry_id, "owner"), "Likes jazz.", "told")
    await memory.async_add(entry_key(entry.entry_id, "owner"), "Has a dentist appointment.", "told")
    await memory.async_add(global_key("owner"), "Sees the dentist on Tuesday.", "told")
    agents = FakeAgents(memory_reply=reply(remove=["a2", "g1"]))

    await run(hass, entry, "Forget everything about the dentist", agents)

    assert await facts(hass, entry_key(entry.entry_id, "owner")) == [("Likes jazz.", "told")]
    assert await facts(hass, global_key("owner")) == []


async def test_unknown_removal_ids_are_ignored(hass: HomeAssistant):
    entry = await add_router(hass)
    memory = await async_get_memory(hass)
    jazz = await memory.async_add(entry_key(entry.entry_id, "owner"), "Likes jazz.", "told")
    tea = await memory.async_add(entry_key(entry.entry_id, "wife"), "Likes tea.", "told")
    agents = FakeAgents(memory_reply=reply(remove=["a9", "z1", jazz["id"], tea["id"]]))

    await run(hass, entry, "Forget something I never told you", agents)

    assert await facts(hass, entry_key(entry.entry_id, "owner")) == [("Likes jazz.", "told")]
    assert await facts(hass, entry_key(entry.entry_id, "wife")) == [("Likes tea.", "told")]


async def test_global_items_cannot_be_removed_when_shared_lists_are_off(hass: HomeAssistant):
    entry = await add_router(hass, options_with(memory={"use_global": False}))
    memory = await async_get_memory(hass)
    await memory.async_add(global_key("owner"), "Has a cat.", "told")
    agents = FakeAgents(memory_reply=reply(remove=["g1"]))

    await run(hass, entry, "Forget that I have a cat", agents)

    assert await facts(hass, global_key("owner")) == [("Has a cat.", "told")]
    (call,) = agents.calls_to(MEMORY_AGENT)
    assert "Has a cat." not in call["extra_system_prompt"]


@pytest.mark.parametrize(
    "memory_reply",
    ["Sure, I saved it!", "{not json", '{"add": "Likes jazz.", "remove": []}', ""],
)
async def test_invalid_reply_from_the_memory_agent_changes_nothing(hass: HomeAssistant, memory_reply):
    entry = await add_router(hass)
    memory = await async_get_memory(hass)
    await memory.async_add(entry_key(entry.entry_id, "owner"), "Likes jazz.", "told")
    agents = FakeAgents(memory_reply=memory_reply)

    await run(hass, entry, "Remember that I prefer the lights warm in the evening", agents)

    assert await all_facts(hass, entry) == [("Likes jazz.", "told")]


async def test_reply_inside_a_code_fence_is_accepted(hass: HomeAssistant):
    entry = await add_router(hass)
    agents = FakeAgents(memory_reply=f"```json\n{reply(add=[told(WARM_LIGHTS)])}\n```")

    await run(hass, entry, "Remember that I prefer the lights warm in the evening", agents)

    assert await facts(hass, entry_key(entry.entry_id, "owner")) == [(WARM_LIGHTS, "told")]


@pytest.mark.parametrize(
    "secret", ["The alarm code is 4821.", "Alex's PIN is 12 34.", "The wifi password is sunflower."]
)
async def test_a_pin_or_code_is_never_saved(hass: HomeAssistant, secret):
    entry = await add_router(hass)
    agents = FakeAgents(memory_reply=reply(add=[told(secret), told(secret, "global")]))

    await run(hass, entry, "Remember what I just told you about the alarm", agents)

    assert await all_facts(hass, entry) == []


async def test_memory_agent_is_told_not_to_save_secrets(hass: HomeAssistant):
    entry = await add_router(hass)
    agents = FakeAgents()

    await run(hass, entry, "Remember that I prefer the lights warm in the evening", agents)

    (call,) = agents.calls_to(MEMORY_AGENT)
    assert "password" in call["extra_system_prompt"].lower()
    assert "code" in call["extra_system_prompt"].lower()


async def test_empty_too_long_and_duplicate_additions_are_dropped(hass: HomeAssistant):
    entry = await add_router(hass)
    memory = await async_get_memory(hass)
    await memory.async_add(entry_key(entry.entry_id, "owner"), "Likes jazz.", "told")
    await memory.async_add(global_key("owner"), "Has a cat.", "told")
    agents = FakeAgents(
        memory_reply=reply(
            add=[
                told("  "),
                told("x" * 201),
                told("likes  JAZZ."),
                told("HAS A CAT."),
                told("Likes jazz.", "global"),
                {"scope": "assistant"},
                told(WARM_LIGHTS),
            ]
        )
    )

    await run(hass, entry, "Remember that I prefer the lights warm in the evening", agents)

    assert await facts(hass, entry_key(entry.entry_id, "owner")) == [
        ("Likes jazz.", "told"),
        (WARM_LIGHTS, "told"),
    ]
    assert await facts(hass, global_key("owner")) == [("Has a cat.", "told")]


async def test_a_new_fact_can_replace_the_one_it_makes_wrong(hass: HomeAssistant):
    entry = await add_router(hass)
    memory = await async_get_memory(hass)
    await memory.async_add(entry_key(entry.entry_id, "owner"), "Sees the dentist at 14:00.", "told")
    agents = FakeAgents(
        memory_reply=reply(add=[told("Sees the dentist at 16:30.")], remove=["a1"])
    )

    await run(hass, entry, "Remember that the dentist moved to half past four", agents)

    assert await facts(hass, entry_key(entry.entry_id, "owner")) == [
        ("Sees the dentist at 16:30.", "told")
    ]


# When the pass does not run at all.


async def test_unknown_voice_never_starts_the_pass(hass: HomeAssistant):
    entry = await add_router(hass, options_with(advanced={"no_helper_role": "stranger"}))
    agents = FakeAgents(memory_reply=reply(add=[told("Likes jazz.")]))

    await run(hass, entry, "Remember that I like jazz", agents)

    assert agents.calls == []
    assert await all_facts(hass, entry) == []


async def test_near_miss_never_reads_memory_or_starts_the_pass(hass: HomeAssistant):
    entry = await add_router(
        hass,
        options_with(
            near_miss={"enabled": True, "min_score": 0.5, "fixed_replies": "Say that again?"}
        ),
    )
    satellite_entry = MockConfigEntry(domain="test")
    satellite_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=satellite_entry.entry_id, identifiers={("test", "kitchen")}
    )
    score = er.async_get(hass).async_get_or_create(
        "sensor",
        "test",
        "kitchen-score",
        device_id=device.id,
        suggested_object_id="kitchen_satellite_last_speaker_score",
    )
    hass.states.async_set(score.entity_id, "0.6")
    hass.states.async_set(f"input_text.voice_speaker_{device.id}", "stranger")
    memory = await async_get_memory(hass)
    await memory.async_add(entry_key(entry.entry_id, "owner"), "Likes jazz.", "told")
    agents = FakeAgents(memory_reply=reply(add=[told("Likes tea.")]))

    with agents.patched():
        result = await ask(hass, entry, "Remember that I like tea", device_id=device.id)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert result.response.speech["plain"]["speech"] == "Say that again?"
    assert agents.calls == []
    assert await all_facts(hass, entry) == [("Likes jazz.", "told")]


async def test_pass_is_skipped_when_the_main_agent_returns_an_error(hass: HomeAssistant):
    entry = await add_router(hass)
    agents = FakeAgents(main_error=True, memory_reply=reply(add=[told("Likes jazz.")]))

    await run(hass, entry, "Remember that I like jazz", agents)

    assert agents.calls_to(MEMORY_AGENT) == []
    assert await all_facts(hass, entry) == []


async def test_pass_is_skipped_for_a_built_in_command(hass: HomeAssistant):
    entry = await add_router(hass, options_with(local={"enabled": True}))
    agents = FakeAgents(memory_reply=reply(add=[told("Likes jazz.")]))

    result = await run(hass, entry, "what time is it", agents)

    assert result.response.speech["plain"]["speech"]
    assert agents.calls == []
    assert await all_facts(hass, entry) == []


async def test_pass_is_skipped_when_memory_is_disabled(hass: HomeAssistant):
    entry = await add_router(hass, options_with(memory={"enabled": False}))
    agents = FakeAgents(memory_reply=reply(add=[told("Likes jazz.")]))

    await run(hass, entry, "Remember that I like jazz", agents)

    assert agents.calls_to(MEMORY_AGENT) == []
    assert await all_facts(hass, entry) == []


# The reply never waits, and the pass never raises.


async def test_reply_is_returned_before_the_memory_agent_finishes(hass: HomeAssistant):
    entry = await add_router(hass)
    gate = asyncio.Event()
    agents = FakeAgents(memory_reply=reply(add=[told(WARM_LIGHTS)]), memory_gate=gate)

    with agents.patched():
        result = await ask(hass, entry, "Remember that I prefer the lights warm in the evening")

        assert result.response.speech["plain"]["speech"] == "Noted."
        assert len(agents.calls_to(MEMORY_AGENT)) == 1
        assert await all_facts(hass, entry) == []

        gate.set()
        await hass.async_block_till_done(wait_background_tasks=True)

    assert await facts(hass, entry_key(entry.entry_id, "owner")) == [(WARM_LIGHTS, "told")]


async def test_a_failing_memory_agent_does_not_affect_the_reply(hass: HomeAssistant):
    entry = await add_router(hass)
    agents = FakeAgents(memory_raises=RuntimeError("model is down"))

    result = await run(hass, entry, "Remember that I like jazz", agents)

    assert result.response.speech["plain"]["speech"] == "Noted."
    assert await all_facts(hass, entry) == []


async def test_memory_creates_no_entities(hass: HomeAssistant):
    entry = await add_router(hass)
    agents = FakeAgents(memory_reply=reply(add=[told(WARM_LIGHTS, "global"), told("Likes jazz.")]))

    await run(hass, entry, "Remember that I prefer the lights warm in the evening", agents)

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert [entity.domain for entity in entities] == ["conversation"]
    assert hass.states.async_entity_ids("todo") == []
    assert hass.states.async_entity_ids("text") == []
