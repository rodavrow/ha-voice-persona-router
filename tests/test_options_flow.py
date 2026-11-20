# SPDX-FileCopyrightText: 2026 rodavrow
# SPDX-License-Identifier: MIT
"""Tests for the Configure dialog: the menu, the Settings form and the Memory editor."""

import copy

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, section
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

from custom_components.voice_persona_router.const import DOMAIN
from custom_components.voice_persona_router.memory import (
    async_get_memory,
    entry_key,
    global_key,
)

MAIN_AGENT = "conversation.home_assistant"
MEMORY_AGENT = "conversation.memory_writer"
MEMORY_DEFAULTS = {"enabled": False, "auto_save": True, "max_items": 50, "use_global": True}
EXISTING_OPTIONS = {
    "agents": {"agent": MAIN_AGENT},
    "local": {"enabled": True, "leave_questions": False},
    "owner": {"name": "Alex", "persona": "The person speaking is Alex."},
    "partner": {"name": "Sam", "persona": "The person speaking is Sam."},
    "strangers": {"mode": "fixed", "fixed_replies": "The answer is no."},
    "near_miss": {
        "enabled": True,
        "min_score": 0.4,
        "persona": "Ask them to repeat.",
        "fixed_replies": "Say that again?",
    },
    "advanced": {"rule": "Names are labels.", "wait_seconds": 2, "no_helper_role": "stranger"},
}


@pytest.fixture
async def entry(hass: HomeAssistant) -> MockConfigEntry:
    assert await async_setup_component(hass, "homeassistant", {})
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen assistant",
        data={"name": "Kitchen assistant", "agent": MAIN_AGENT},
        options=copy.deepcopy(EXISTING_OPTIONS),
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


def shown_values(schema) -> dict:
    """What a form would submit if the person saved it without touching anything."""
    values = {}
    for marker, field in schema.schema.items():
        if isinstance(field, section):
            values[str(marker)] = shown_values(field.schema)
        elif marker.description and "suggested_value" in marker.description:
            values[str(marker)] = marker.description["suggested_value"]
        elif callable(getattr(marker, "default", None)):
            values[str(marker)] = marker.default()
    return values


async def open_step(hass: HomeAssistant, entry: MockConfigEntry, step: str):
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        menu["flow_id"], {"next_step_id": step}
    )


async def open_list(hass: HomeAssistant, entry: MockConfigEntry, key: str):
    picker = await open_step(hass, entry, "memory")
    return await hass.config_entries.options.async_configure(picker["flow_id"], {"list": key})


def picker_labels(picker) -> dict[str, str]:
    (selector,) = picker["data_schema"].schema.values()
    return {option["value"]: option["label"] for option in selector.config["options"]}


def facts_shown(form) -> str:
    return shown_values(form["data_schema"]).get("facts", "")


# The menu.


async def test_configure_opens_a_menu_with_settings_and_memory(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert list(result["menu_options"]) == ["settings", "memory"]


# The Settings form.


async def test_settings_form_shows_existing_values_and_memory_defaults(hass, entry):
    form = await open_step(hass, entry, "settings")

    assert form["type"] is FlowResultType.FORM
    assert shown_values(form["data_schema"]) == {**EXISTING_OPTIONS, "memory": MEMORY_DEFAULTS}


async def test_saving_untouched_settings_keeps_options_and_adds_memory_defaults(hass, entry):
    form = await open_step(hass, entry, "settings")

    result = await hass.config_entries.options.async_configure(
        form["flow_id"], shown_values(form["data_schema"])
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {**EXISTING_OPTIONS, "memory": MEMORY_DEFAULTS}


async def test_memory_section_comes_right_after_built_in_commands(hass, entry):
    form = await open_step(hass, entry, "settings")

    sections = [str(marker) for marker in form["data_schema"].schema]
    assert sections.index("memory") == sections.index("local") + 1


async def test_settings_for_an_entry_without_options_propose_memory_defaults(hass):
    assert await async_setup_component(hass, "homeassistant", {})
    new_entry = MockConfigEntry(domain=DOMAIN, title="Office assistant", data={"agent": MAIN_AGENT})
    new_entry.add_to_hass(hass)

    form = await open_step(hass, new_entry, "settings")

    assert shown_values(form["data_schema"])["memory"] == MEMORY_DEFAULTS


async def submit_memory_settings(hass, entry, memory_settings):
    form = await open_step(hass, entry, "settings")
    values = shown_values(form["data_schema"])
    values["memory"] = {**MEMORY_DEFAULTS, **memory_settings}
    return await hass.config_entries.options.async_configure(form["flow_id"], values)


async def test_memory_can_be_enabled_with_a_separate_agent(hass, entry):
    result = await submit_memory_settings(hass, entry, {"enabled": True, "agent": MEMORY_AGENT})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["memory"] == {**MEMORY_DEFAULTS, "enabled": True, "agent": MEMORY_AGENT}


async def test_enabling_memory_without_an_agent_is_a_form_error(hass, entry):
    result = await submit_memory_settings(hass, entry, {"enabled": True})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "memory_agent_required"}
    assert entry.options == EXISTING_OPTIONS


async def test_memory_agent_may_not_be_the_main_agent(hass, entry):
    result = await submit_memory_settings(hass, entry, {"enabled": True, "agent": MAIN_AGENT})

    assert result["errors"] == {"base": "memory_agent_invalid"}
    assert entry.options == EXISTING_OPTIONS


async def test_memory_agent_may_not_be_this_router(hass, entry):
    router = er.async_get(hass).async_get_entity_id("conversation", DOMAIN, entry.entry_id)
    assert router is not None

    result = await submit_memory_settings(hass, entry, {"agent": router})

    assert result["errors"] == {"base": "memory_agent_invalid"}


async def test_a_rejected_settings_form_keeps_what_was_typed(hass, entry):
    result = await submit_memory_settings(hass, entry, {"enabled": True, "max_items": 80})

    assert shown_values(result["data_schema"])["memory"]["max_items"] == 80


async def test_same_home_assistant_user_for_both_people_is_a_form_error(
    hass, entry, hass_admin_user
):
    form = await open_step(hass, entry, "settings")
    values = shown_values(form["data_schema"])
    values["owner"] = {**values["owner"], "user": hass_admin_user.id}
    values["partner"] = {**values["partner"], "user": hass_admin_user.id}

    result = await hass.config_entries.options.async_configure(form["flow_id"], values)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "same_user"}
    assert entry.options == EXISTING_OPTIONS


async def test_a_home_assistant_user_can_be_chosen_for_one_person(hass, entry, hass_admin_user):
    form = await open_step(hass, entry, "settings")
    values = shown_values(form["data_schema"])
    values["owner"] = {**values["owner"], "user": hass_admin_user.id}

    result = await hass.config_entries.options.async_configure(form["flow_id"], values)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["owner"]["user"] == hass_admin_user.id


# The Memory picker.


async def test_picker_lists_four_lists_with_names_and_counts(hass, entry):
    memory = await async_get_memory(hass)
    await memory.async_add(entry_key(entry.entry_id, "owner"), "Likes jazz.", "told")
    await memory.async_add(entry_key(entry.entry_id, "owner"), "Has a cat.", "judged")
    await memory.async_add(global_key("wife"), "Likes tea.", "told")

    picker = await open_step(hass, entry, "memory")

    assert picker["type"] is FlowResultType.FORM
    assert picker_labels(picker) == {
        entry_key(entry.entry_id, "owner"): "Alex: this assistant (2)",
        global_key("owner"): "Alex: all assistants (0)",
        entry_key(entry.entry_id, "wife"): "Sam: this assistant (0)",
        global_key("wife"): "Sam: all assistants (1)",
    }


async def test_picker_falls_back_to_person_1_and_person_2_without_names(hass):
    assert await async_setup_component(hass, "homeassistant", {})
    unnamed = MockConfigEntry(domain=DOMAIN, title="Office assistant", data={"agent": MAIN_AGENT})
    unnamed.add_to_hass(hass)

    picker = await open_step(hass, unnamed, "memory")

    assert list(picker_labels(picker).values()) == [
        "Person 1: this assistant (0)",
        "Person 1: all assistants (0)",
        "Person 2: this assistant (0)",
        "Person 2: all assistants (0)",
    ]


async def test_picker_does_not_show_another_assistants_lists(hass, entry):
    picker = await open_step(hass, entry, "memory")

    assert entry_key("office-entry", "owner") not in picker_labels(picker)


# The Memory editor.


async def test_editor_shows_one_fact_per_line_in_saved_order(hass, entry):
    key = entry_key(entry.entry_id, "owner")
    memory = await async_get_memory(hass)
    await memory.async_add(key, "Likes jazz.", "told")
    await memory.async_add(key, "Has a cat.", "judged")

    form = await open_list(hass, entry, key)

    assert form["type"] is FlowResultType.FORM
    assert form["step_id"] == "memory_edit"
    assert facts_shown(form) == "Likes jazz.\nHas a cat."


async def test_saving_an_edit_removes_keeps_and_adds_then_returns_to_the_menu(hass, entry):
    key = entry_key(entry.entry_id, "owner")
    memory = await async_get_memory(hass)
    await memory.async_add(key, "Likes jazz.", "judged")
    cat = await memory.async_add(key, "Has a cat.", "judged")
    form = await open_list(hass, entry, key)

    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {"facts": "Has a cat.\nPrefers tea in the morning."}
    )

    assert result["type"] is FlowResultType.MENU
    items = memory.items(key)
    assert items[0] == cat
    assert [(item["text"], item["source"]) for item in items[1:]] == [
        ("Prefers tea in the morning.", "told")
    ]


async def test_an_item_saved_while_the_editor_was_open_survives(hass, entry):
    key = entry_key(entry.entry_id, "owner")
    memory = await async_get_memory(hass)
    await memory.async_add(key, "Likes jazz.", "judged")
    form = await open_list(hass, entry, key)
    await memory.async_add(key, "Has a cat.", "judged")

    await hass.config_entries.options.async_configure(form["flow_id"], {"facts": "Likes jazz."})

    assert [item["text"] for item in memory.items(key)] == ["Likes jazz.", "Has a cat."]


async def test_clearing_the_box_forgets_every_shown_fact(hass, entry):
    key = entry_key(entry.entry_id, "owner")
    memory = await async_get_memory(hass)
    await memory.async_add(key, "Likes jazz.", "judged")
    form = await open_list(hass, entry, key)

    await hass.config_entries.options.async_configure(form["flow_id"], {})

    assert memory.items(key) == []


async def test_a_line_over_200_characters_is_a_form_error_naming_the_line(hass, entry):
    key = entry_key(entry.entry_id, "owner")
    memory = await async_get_memory(hass)
    jazz = await memory.async_add(key, "Likes jazz.", "judged")
    form = await open_list(hass, entry, key)
    long_line = "Remembers " + "very " * 40 + "much."

    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {"facts": f"Likes jazz.\n{long_line}"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "line_too_long"}
    assert long_line.startswith(result["description_placeholders"]["line"].rstrip("…"))
    assert facts_shown(result) == f"Likes jazz.\n{long_line}"
    assert memory.items(key) == [jazz]


async def test_global_list_edits_are_seen_by_other_assistants(hass, entry):
    form = await open_list(hass, entry, global_key("owner"))

    await hass.config_entries.options.async_configure(form["flow_id"], {"facts": "Has a cat."})

    memory = await async_get_memory(hass)
    assert [item["text"] for item in memory.items(global_key("owner"))] == ["Has a cat."]


async def test_saving_memory_leaves_the_entrys_options_unchanged(hass, entry):
    form = await open_list(hass, entry, entry_key(entry.entry_id, "owner"))

    await hass.config_entries.options.async_configure(form["flow_id"], {"facts": "Has a cat."})

    assert entry.options == EXISTING_OPTIONS


async def test_memory_can_be_edited_while_memory_is_disabled(hass, entry):
    key = entry_key(entry.entry_id, "wife")
    assert "memory" not in entry.options
    form = await open_list(hass, entry, key)

    await hass.config_entries.options.async_configure(form["flow_id"], {"facts": "Likes tea."})

    memory = await async_get_memory(hass)
    assert [item["text"] for item in memory.items(key)] == ["Likes tea."]


async def test_a_list_key_that_is_not_offered_is_rejected(hass, entry):
    picker = await open_step(hass, entry, "memory")

    with pytest.raises(Exception):  # noqa: B017, PT011 - schema validation error
        await hass.config_entries.options.async_configure(
            picker["flow_id"], {"list": entry_key("office-entry", "owner")}
        )
