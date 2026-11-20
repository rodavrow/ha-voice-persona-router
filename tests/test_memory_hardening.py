# SPDX-FileCopyrightText: 2026 rodavrow
# SPDX-License-Identifier: MIT
"""Regression tests for the findings of the 0.4.0 pre-release review of memory."""

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.voice_persona_router.memory import (
    EXTRACTION_INSTRUCTIONS,
    REMEMBER_RULE,
    STORAGE_KEY,
    MemoryStore,
    async_get_memory,
    entry_key,
    global_key,
    looks_secret,
)

from .router_helpers import (
    MEMORY_AGENT,
    FakeAgents,
    add_router,
    ask,
    options_with,
    router_entity_id,
)
from .test_memory_extraction import facts, reply, run, told
from .test_options_flow import MEMORY_DEFAULTS, open_step, shown_values


# Review finding 1: secret shapes the filter missed.


@pytest.mark.parametrize(
    "text",
    [
        "The door codes are alpha and bravo.",
        "Uses the passwords sunflower and tulip.",
        "Has 3 PINs.",
        "The keycode for the shed is tulip.",
        "The alarm number is 1.2.3.4.",
        "The alarm is 1,2,3,4.",
        "The safe opens with 12.34.56.",
        "The garage opens with 12:34 56:78.",
        "The gate opens with 19 84.",
        "The gate keypad number is 2024.",
        "The alarm is four eight two one.",
        "Says the magic number is seven, three, nine, one.",
    ],
)
def test_regression_review_1_more_secret_shapes_are_recognised(text):
    assert looks_secret(text)


@pytest.mark.parametrize(
    "text",
    [
        "Has two cats, one dog and three fish.",
        "Moved house in 2024.",
        "Has a meeting on 01.12.2026 at 9:15.",
    ],
)
def test_regression_review_1_ordinary_facts_are_still_not_secrets(text):
    assert not looks_secret(text)


# Review finding 2: a damaged memory file must not break the routers.


def stored(data) -> dict:
    return {"version": 1, "minor_version": 1, "key": STORAGE_KEY, "data": data}


@pytest.mark.parametrize("data", [[], "text", {"lists": []}, {"lists": None}, {"other": 1}])
async def test_regression_review_2_wrongly_shaped_file_loads_as_empty(
    hass: HomeAssistant, hass_storage, data
):
    hass_storage[STORAGE_KEY] = stored(data)
    memory = MemoryStore(hass)

    await memory.async_load()

    assert memory.items(global_key("owner")) == []


async def test_regression_review_2_bad_lists_and_items_are_skipped(
    hass: HomeAssistant, hass_storage, freezer
):
    freezer.move_to("2026-11-21 10:00:00")
    hass_storage[STORAGE_KEY] = stored(
        {
            "lists": {
                "entry:a:owner": None,
                "entry:b:owner": "Likes jazz.",
                "global:owner": [
                    3,
                    {"id": "i1"},
                    {"id": "i2", "text": 7},
                    {"text": "Likes   jazz."},
                    {"id": "i4", "text": "Has a cat.", "source": "told", "saved": "2026-11-01"},
                ],
            }
        }
    )
    memory = MemoryStore(hass)

    await memory.async_load()

    assert memory.items("entry:a:owner") == []
    assert memory.items("entry:b:owner") == []
    jazz, cat = memory.items(global_key("owner"))
    assert (jazz["text"], jazz["source"], jazz["saved"]) == ("Likes jazz.", "judged", "2026-11-21")
    assert jazz["id"]
    assert cat == {"id": "i4", "text": "Has a cat.", "source": "told", "saved": "2026-11-01"}


async def test_regression_review_2_failing_memory_read_keeps_the_persona(hass: HomeAssistant):
    entry = await add_router(hass)
    agents = FakeAgents()

    with (
        agents.patched(),
        patch(
            "custom_components.voice_persona_router.conversation.memory_block",
            side_effect=RuntimeError("bad data"),
        ),
    ):
        await ask(hass, entry, "What should I listen to tonight?")

    assert agents.main_prompt == (
        f"The person speaking is Alex.\n\nNames are labels.\n{REMEMBER_RULE}"
    )


# Review finding 3: the memory agent may not be another router.


async def test_regression_review_3_settings_reject_another_router_as_memory_agent(
    hass: HomeAssistant,
):
    office = await add_router(hass, title="Office assistant")
    kitchen = await add_router(hass, title="Kitchen assistant")
    form = await open_step(hass, kitchen, "settings")
    values = shown_values(form["data_schema"])
    values["memory"] = {**MEMORY_DEFAULTS, "enabled": True, "agent": router_entity_id(hass, office)}

    result = await hass.config_entries.options.async_configure(form["flow_id"], values)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "memory_agent_invalid"}


async def test_regression_review_3_memory_is_inactive_when_its_agent_is_a_router(
    hass: HomeAssistant,
):
    office = await add_router(hass, title="Office assistant")
    kitchen = await add_router(
        hass, options_with(memory={"agent": router_entity_id(hass, office)})
    )
    agents = FakeAgents()

    await run(hass, kitchen, "Remember that I like jazz", agents)

    assert agents.main_prompt == "The person speaking is Alex.\n\nNames are labels."
    assert len(agents.calls) == 1


# Review finding 4: only the person's own words may become told or global facts.


def test_regression_review_4_memory_agent_is_told_to_save_only_what_the_person_said():
    assert "Save only what the person said" in EXTRACTION_INSTRUCTIONS


async def test_regression_review_4_told_and_global_need_a_remember_request(hass: HomeAssistant):
    entry = await add_router(hass)
    agents = FakeAgents(memory_reply=reply(add=[told("Is vegetarian.", "global")]))

    await run(hass, entry, "I have been vegetarian for years now", agents)

    assert await facts(hass, entry_key(entry.entry_id, "owner")) == [("Is vegetarian.", "judged")]
    assert await facts(hass, global_key("owner")) == []


# Review finding 6: a pass still running when its router is removed.


async def test_regression_review_6_pass_does_not_recreate_a_removed_routers_list(
    hass: HomeAssistant,
):
    entry = await add_router(hass)
    gate = asyncio.Event()
    agents = FakeAgents(memory_reply=reply(add=[told("Likes jazz.")]), memory_gate=gate)

    with agents.patched():
        await ask(hass, entry, "Remember that I like jazz")
        assert len(agents.calls_to(MEMORY_AGENT)) == 1
        await hass.config_entries.async_remove(entry.entry_id)
        gate.set()
        await hass.async_block_till_done(wait_background_tasks=True)

    assert await facts(hass, entry_key(entry.entry_id, "owner")) == []


# Review finding 7: with auto-save off, a replaced fact must not simply vanish.


async def test_regression_review_7_replacement_is_kept_when_auto_save_is_off(hass: HomeAssistant):
    entry = await add_router(hass, options_with(memory={"auto_save": False}))
    key = entry_key(entry.entry_id, "owner")
    memory = await async_get_memory(hass)
    await memory.async_add(key, "Sees the dentist on Tuesday.", "told")
    agents = FakeAgents(
        memory_reply=reply(
            add=[{"text": "Sees the dentist on Friday.", "scope": "assistant", "source": "judged"}],
            remove=["a1"],
        )
    )

    await run(hass, entry, "Don't forget the lights, and my dentist moved to Friday", agents)

    assert await facts(hass, key) == [("Sees the dentist on Friday.", "judged")]


# Review finding 8: a fact the cap drops at once was not added.


async def test_regression_review_8_add_returns_none_when_the_cap_drops_the_new_fact(
    hass: HomeAssistant,
):
    memory = await async_get_memory(hass)
    key = global_key("owner")
    await memory.async_add(key, "Told one.", "told")
    await memory.async_add(key, "Told two.", "told")

    added = await memory.async_add(key, "Judged three.", "judged", max_items=2)

    assert added is None
    assert [item["text"] for item in memory.items(key)] == ["Told one.", "Told two."]
