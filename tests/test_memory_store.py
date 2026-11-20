# SPDX-FileCopyrightText: 2026 rodavrow
# SPDX-License-Identifier: MIT
"""Tests for the shared memory store in memory.py."""

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry, flush_store

from custom_components.voice_persona_router.const import DOMAIN
from custom_components.voice_persona_router.memory import (
    STORAGE_KEY,
    LineTooLongError,
    MemoryStore,
    async_get_memory,
    entry_key,
    global_key,
)

KITCHEN = entry_key("kitchen-entry", "owner")
GLOBAL_ALEX = global_key("owner")


@pytest.fixture
async def memory(hass: HomeAssistant) -> MemoryStore:
    return await async_get_memory(hass)


def texts(memory: MemoryStore, key: str) -> list[str]:
    return [item["text"] for item in memory.items(key)]


async def test_list_keys_follow_the_documented_scheme():
    assert entry_key("abc", "wife") == "entry:abc:wife"
    assert global_key("owner") == "global:owner"


async def test_add_stores_text_source_and_todays_date(memory, freezer: FrozenDateTimeFactory):
    freezer.move_to("2026-11-21 10:00:00")

    item = await memory.async_add(KITCHEN, "Prefers the lights warm in the evening.", "told")

    assert memory.items(KITCHEN) == [item]
    assert item["text"] == "Prefers the lights warm in the evening."
    assert item["source"] == "told"
    assert item["saved"] == "2026-11-21"
    assert item["id"]


async def test_add_gives_each_item_a_distinct_id(memory):
    first = await memory.async_add(KITCHEN, "Likes jazz.", "judged")
    second = await memory.async_add(KITCHEN, "Has a cat called Pixel.", "judged")

    assert first["id"] != second["id"]


async def test_add_collapses_newlines_and_spaces(memory):
    item = await memory.async_add(KITCHEN, "  Likes\n  jazz   on Sundays. ", "told")

    assert item["text"] == "Likes jazz on Sundays."


@pytest.mark.parametrize("text", ["", "   \n  ", "x" * 201])
async def test_add_rejects_empty_or_too_long_text(memory, text):
    with pytest.raises(ValueError):
        await memory.async_add(KITCHEN, text, "told")
    assert memory.items(KITCHEN) == []


async def test_add_accepts_text_of_exactly_200_characters(memory):
    assert await memory.async_add(KITCHEN, "x" * 200, "told") is not None


async def test_add_skips_duplicate_ignoring_case_and_spacing(memory):
    await memory.async_add(KITCHEN, "Likes jazz.", "told")

    duplicate = await memory.async_add(KITCHEN, "  likes   JAZZ. ", "judged")

    assert duplicate is None
    assert texts(memory, KITCHEN) == ["Likes jazz."]


async def test_lists_are_separate(memory):
    await memory.async_add(KITCHEN, "Likes jazz.", "told")

    assert memory.items(GLOBAL_ALEX) == []
    assert memory.items(entry_key("kitchen-entry", "wife")) == []


async def test_items_returns_copies_that_do_not_change_the_store(memory):
    await memory.async_add(KITCHEN, "Likes jazz.", "told")

    memory.items(KITCHEN)[0]["text"] = "changed"

    assert texts(memory, KITCHEN) == ["Likes jazz."]


async def test_remove_deletes_the_given_ids_and_ignores_unknown_ones(memory):
    jazz = await memory.async_add(KITCHEN, "Likes jazz.", "told")
    await memory.async_add(KITCHEN, "Has a cat called Pixel.", "judged")

    removed = await memory.async_remove(KITCHEN, [jazz["id"], "no-such-id"])

    assert removed == [jazz]
    assert texts(memory, KITCHEN) == ["Has a cat called Pixel."]


async def test_cap_drops_oldest_judged_items_first(memory):
    await memory.async_add(KITCHEN, "Told one.", "told")
    await memory.async_add(KITCHEN, "Judged old.", "judged")
    await memory.async_add(KITCHEN, "Judged new.", "judged")

    await memory.async_add(KITCHEN, "Told two.", "told", max_items=3)

    assert texts(memory, KITCHEN) == ["Told one.", "Judged new.", "Told two."]


async def test_cap_never_drops_told_items(memory):
    for number in range(3):
        await memory.async_add(KITCHEN, f"Told {number}.", "told")

    await memory.async_add(KITCHEN, "Told 3.", "told", max_items=2)

    assert texts(memory, KITCHEN) == ["Told 0.", "Told 1.", "Told 2.", "Told 3."]


async def test_memory_survives_a_restart(hass: HomeAssistant, memory, hass_storage):
    await memory.async_add(KITCHEN, "Likes jazz.", "told")
    await flush_store(memory.store)

    reloaded = MemoryStore(hass)
    await reloaded.async_load()

    assert texts(reloaded, KITCHEN) == ["Likes jazz."]
    assert STORAGE_KEY in hass_storage


async def test_async_get_memory_returns_one_shared_store(hass: HomeAssistant):
    assert await async_get_memory(hass) is await async_get_memory(hass)


# Applying an edit from the settings screen.


async def test_edit_removes_deleted_lines(memory):
    jazz = await memory.async_add(KITCHEN, "Likes jazz.", "judged")
    cat = await memory.async_add(KITCHEN, "Has a cat called Pixel.", "judged")

    await memory.async_apply_edit(KITCHEN, [jazz, cat], ["Has a cat called Pixel."])

    assert texts(memory, KITCHEN) == ["Has a cat called Pixel."]


async def test_edit_keeps_unchanged_items_with_their_source_and_date(
    memory, freezer: FrozenDateTimeFactory
):
    freezer.move_to("2026-11-01 10:00:00")
    jazz = await memory.async_add(KITCHEN, "Likes jazz.", "judged")
    freezer.move_to("2026-11-21 10:00:00")

    await memory.async_apply_edit(KITCHEN, [jazz], ["Likes jazz."])

    assert memory.items(KITCHEN) == [jazz]


async def test_edit_adds_new_and_changed_lines_as_told_with_todays_date(
    memory, freezer: FrozenDateTimeFactory
):
    freezer.move_to("2026-11-01 10:00:00")
    jazz = await memory.async_add(KITCHEN, "Likes jazz.", "judged")
    freezer.move_to("2026-11-21 10:00:00")

    await memory.async_apply_edit(KITCHEN, [jazz], ["Likes jazz and blues.", "Has a cat."])

    items = memory.items(KITCHEN)
    assert [item["text"] for item in items] == ["Likes jazz and blues.", "Has a cat."]
    assert {(item["source"], item["saved"]) for item in items} == {("told", "2026-11-21")}


async def test_edit_keeps_items_added_while_the_form_was_open(memory):
    jazz = await memory.async_add(KITCHEN, "Likes jazz.", "judged")
    shown = memory.items(KITCHEN)
    await memory.async_add(KITCHEN, "Has a cat called Pixel.", "judged")

    await memory.async_apply_edit(KITCHEN, shown, [])

    assert texts(memory, KITCHEN) == ["Has a cat called Pixel."]
    assert jazz not in memory.items(KITCHEN)


async def test_edit_trims_lines_and_drops_empty_and_duplicate_lines(memory):
    await memory.async_apply_edit(
        KITCHEN, [], ["  Likes jazz.  ", "", "   ", "likes JAZZ.", "Has a cat."]
    )

    assert texts(memory, KITCHEN) == ["Likes jazz.", "Has a cat."]


async def test_edit_does_not_add_a_line_that_duplicates_a_kept_item(memory):
    jazz = await memory.async_add(KITCHEN, "Likes jazz.", "judged")

    await memory.async_apply_edit(KITCHEN, [jazz], ["Likes jazz.", "LIKES JAZZ."])

    assert memory.items(KITCHEN) == [jazz]


async def test_edit_rejects_a_line_over_200_characters_and_changes_nothing(memory):
    jazz = await memory.async_add(KITCHEN, "Likes jazz.", "judged")
    long_line = "y" * 201

    with pytest.raises(LineTooLongError) as raised:
        await memory.async_apply_edit(KITCHEN, [jazz], [long_line])

    assert raised.value.line == long_line
    assert memory.items(KITCHEN) == [jazz]


# Removing a router entry.


async def test_removing_an_entry_deletes_its_lists_and_keeps_global_and_other_entries(
    hass: HomeAssistant,
):
    assert await async_setup_component(hass, "homeassistant", {})
    kitchen = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen assistant",
        data={"name": "Kitchen assistant", "agent": "conversation.home_assistant"},
    )
    kitchen.add_to_hass(hass)
    assert await hass.config_entries.async_setup(kitchen.entry_id)
    await hass.async_block_till_done()
    memory = await async_get_memory(hass)
    await memory.async_add(entry_key(kitchen.entry_id, "owner"), "Likes jazz.", "told")
    await memory.async_add(entry_key(kitchen.entry_id, "wife"), "Likes tea.", "told")
    await memory.async_add(entry_key("office-entry", "owner"), "Likes coffee.", "told")
    await memory.async_add(GLOBAL_ALEX, "Has a cat called Pixel.", "told")

    await hass.config_entries.async_remove(kitchen.entry_id)
    await hass.async_block_till_done()

    assert memory.items(entry_key(kitchen.entry_id, "owner")) == []
    assert memory.items(entry_key(kitchen.entry_id, "wife")) == []
    assert texts(memory, entry_key("office-entry", "owner")) == ["Likes coffee."]
    assert texts(memory, GLOBAL_ALEX) == ["Has a cat called Pixel."]
