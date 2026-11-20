# SPDX-FileCopyrightText: 2026 rodavrow
# SPDX-License-Identifier: MIT
"""Memory and Home Assistant user mapping together: the phone app and browser."""

from homeassistant.core import HomeAssistant

from custom_components.voice_persona_router.memory import async_get_memory, entry_key

from .router_helpers import MEMORY_AGENT, FakeAgents, add_router, ask, options_with
from .test_memory_extraction import reply, told

ALEX_USER = "user-alex"
SAM_USER = "user-sam"
GUEST_USER = "user-guest"


async def add_mapped_router(hass: HomeAssistant):
    entry = await add_router(
        hass, options_with(owner={"user": ALEX_USER}, partner={"user": SAM_USER})
    )
    memory = await async_get_memory(hass)
    await memory.async_add(entry_key(entry.entry_id, "owner"), "Likes jazz.", "told")
    await memory.async_add(entry_key(entry.entry_id, "wife"), "Likes tea.", "told")
    return entry


async def test_person_2_on_their_phone_gets_their_own_memory(hass: HomeAssistant):
    entry = await add_mapped_router(hass)
    agents = FakeAgents()

    with agents.patched():
        await ask(hass, entry, "What should I drink tonight?", user_id=SAM_USER)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert "What you remember about Sam" in agents.main_prompt
    assert "Likes tea." in agents.main_prompt
    assert "Likes jazz." not in agents.main_prompt


async def test_fact_told_from_a_phone_is_saved_for_the_logged_in_person(hass: HomeAssistant):
    entry = await add_mapped_router(hass)
    agents = FakeAgents(memory_reply=reply(add=[told("Runs on Sundays.")]))

    with agents.patched():
        await ask(hass, entry, "Remember that I run on Sundays", user_id=SAM_USER)
        await hass.async_block_till_done(wait_background_tasks=True)

    memory = await async_get_memory(hass)
    assert [item["text"] for item in memory.items(entry_key(entry.entry_id, "wife"))] == [
        "Likes tea.",
        "Runs on Sundays.",
    ]
    assert [item["text"] for item in memory.items(entry_key(entry.entry_id, "owner"))] == [
        "Likes jazz."
    ]


async def test_unmapped_user_gets_no_memory_and_saves_nothing(hass: HomeAssistant):
    entry = await add_mapped_router(hass)
    agents = FakeAgents(memory_reply=reply(add=[told("Likes coffee.")]))

    with agents.patched():
        result = await ask(hass, entry, "Remember that I like coffee", user_id=GUEST_USER)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert result.response.speech["plain"]["speech"] == "The answer is no."
    assert agents.calls == []
    assert agents.calls_to(MEMORY_AGENT) == []


async def test_regression_review_5_unexpected_helper_value_gets_no_memory(hass: HomeAssistant):
    entry = await add_mapped_router(hass)
    hass.states.async_set("input_text.voice_speaker_kitchendevice", "guest")
    agents = FakeAgents(memory_reply=reply(add=[told("Likes coffee.")]))

    with agents.patched():
        result = await ask(
            hass,
            entry,
            "Remember that I like coffee",
            device_id="kitchendevice",
            user_id=ALEX_USER,
        )
        await hass.async_block_till_done(wait_background_tasks=True)

    assert result.response.speech["plain"]["speech"] == "The answer is no."
    assert agents.calls == []
