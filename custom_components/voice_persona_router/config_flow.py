# SPDX-FileCopyrightText: 2026 rodavrow
# SPDX-License-Identifier: MIT
"""Config flow and settings screen for Voice Persona Router."""

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .const import DOMAIN
from .memory import (
    LineTooLongError,
    MemoryItem,
    MemoryStore,
    Person,
    async_get_memory,
    entry_key,
    global_key,
    item_line,
    router_agent_ids,
)

MEMORY_DEFAULTS = {
    "enabled": False,
    "auto_save": True,
    "max_items": 50,
    "use_global": True,
    "shared": True,
}
LINE_PREVIEW_LENGTH = 60

DEFAULT_NEAR_PERSONA = (
    "The voice sounded a little like someone who lives here, but you could not be sure. "
    "Do not help yet and do not carry out the request. Say in one short sentence, in your "
    "own style, that they sound familiar and ask them to say it again clearly."
)
DEFAULT_NEAR_LINES = "You sound familiar, but I am not sure it is you. Say that again?"


def _text(multiline=False):
    return selector.TextSelector(selector.TextSelectorConfig(multiline=multiline))


def _agent():
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="conversation"))


def _choice(options):
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[selector.SelectOptionDict(value=v, label=l) for v, l in options],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _number(low, high, step, unit=None):
    config = {"min": low, "max": high, "step": step, "mode": selector.NumberSelectorMode.BOX}
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


def _opt(key, current, allowed=None):
    """Optional field that shows the saved value and may be cleared.

    With `allowed`, a saved value that is no longer one of the choices (a deleted
    user, say) is not suggested, so the form can still be saved.
    """
    value = current.get(key)
    if value is None or value == "" or (allowed is not None and value not in allowed):
        return vol.Optional(key)
    return vol.Optional(key, description={"suggested_value": value})


async def login_users(hass):
    """(id, name) of the active people who can log in, without Home Assistant's own accounts."""
    users = await hass.auth.async_get_users()
    return [(u.id, u.name or u.id) for u in users if u.is_active and not u.system_generated]


def same_user_for_both(settings) -> bool:
    owner_user = (settings.get("owner") or {}).get("user")
    partner_user = (settings.get("partner") or {}).get("user")
    return bool(owner_user) and owner_user == partner_user


def _fixed(key, current, fallback):
    """Field that always has a value."""
    value = current.get(key)
    return vol.Optional(key, default=fallback if value is None else value)


def _script_texts(hass, script_entity_id):
    """Collect the texts of an older 'who is speaking' script, if it has the expected shape."""
    found = {}

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            variables = node.get("variables")
            if isinstance(variables, dict):
                if isinstance(variables.get("personas"), dict):
                    found["personas"] = variables["personas"]
                if isinstance(variables.get("refusals"), list):
                    found["refusals"] = variables["refusals"]
                result = variables.get("result")
                if isinstance(result, dict) and isinstance(result.get("rule"), str):
                    found["rule"] = result["rule"]
            for value in node.values():
                walk(value)

    try:
        component = hass.data.get("script")
        entity = component.get_entity(script_entity_id) if component and script_entity_id else None
        walk(getattr(entity, "raw_config", None) or {})
    except Exception:  # noqa: BLE001 - the import is a convenience only
        return {}
    return found


def current_settings(hass, entry):
    """Saved settings, or a first proposal taken from the older script."""
    if entry.options:
        return dict(entry.options)
    texts = _script_texts(hass, entry.data.get("script"))
    personas = texts.get("personas") or {}
    lines = [str(line).strip() for line in texts.get("refusals") or [] if str(line).strip()]
    return {
        "agents": {"agent": entry.data.get("agent")},
        "local": {"enabled": True, "leave_questions": True},
        "memory": dict(MEMORY_DEFAULTS),
        "owner": {"persona": str(personas.get("owner") or "")},
        "partner": {"persona": str(personas.get("wife") or "")},
        "strangers": {
            "mode": "ai",
            "persona": str(personas.get("stranger") or ""),
            "fixed_replies": "\n".join(lines),
        },
        "near_miss": {
            "enabled": False,
            "min_score": 0.5,
            "persona": DEFAULT_NEAR_PERSONA,
            "fixed_replies": DEFAULT_NEAR_LINES,
        },
        "advanced": {"rule": str(texts.get("rule") or ""), "wait_seconds": 3, "no_helper_role": "owner"},
    }


def settings_schema(current, users):
    """Build the settings form. `users` is the (id, name) list from login_users."""
    user_ids = {user_id for user_id, _ in users}
    agents = current.get("agents") or {}
    local = current.get("local") or {}
    memory = current.get("memory") or {}
    owner = current.get("owner") or {}
    partner = current.get("partner") or {}
    strangers = current.get("strangers") or {}
    near = current.get("near_miss") or {}
    advanced = current.get("advanced") or {}
    return vol.Schema(
        {
            vol.Required("agents"): section(
                vol.Schema({_opt("agent", agents): _agent()}),
                {"collapsed": False},
            ),
            vol.Required("local"): section(
                vol.Schema(
                    {
                        _fixed("enabled", local, True): selector.BooleanSelector(),
                        _fixed("leave_questions", local, True): selector.BooleanSelector(),
                    }
                ),
                {"collapsed": True},
            ),
            vol.Required("memory"): section(
                vol.Schema(
                    {
                        _fixed("enabled", memory, False): selector.BooleanSelector(),
                        _opt("agent", memory): _agent(),
                        _fixed("auto_save", memory, True): selector.BooleanSelector(),
                        _fixed("max_items", memory, 50): _number(10, 200, 1),
                        _fixed("use_global", memory, True): selector.BooleanSelector(),
                        _fixed("shared", memory, True): selector.BooleanSelector(),
                    }
                ),
                {"collapsed": True},
            ),
            vol.Required("owner"): section(
                vol.Schema(
                    {
                        _opt("name", owner): _text(),
                        _opt("user", owner, user_ids): _choice(users),
                        _opt("persona", owner): _text(True),
                    }
                ),
                {"collapsed": True},
            ),
            vol.Required("partner"): section(
                vol.Schema(
                    {
                        _opt("name", partner): _text(),
                        _opt("user", partner, user_ids): _choice(users),
                        _opt("persona", partner): _text(True),
                    }
                ),
                {"collapsed": True},
            ),
            vol.Required("strangers"): section(
                vol.Schema(
                    {
                        _fixed("mode", strangers, "ai"): _choice(
                            [
                                ("ai", "Refusal written by an agent without tools"),
                                ("fixed", "Fixed lines only"),
                            ]
                        ),
                        _opt("reply_agent", strangers): _agent(),
                        _opt("persona", strangers): _text(True),
                        _opt("fixed_replies", strangers): _text(True),
                    }
                ),
                {"collapsed": True},
            ),
            vol.Required("near_miss"): section(
                vol.Schema(
                    {
                        _fixed("enabled", near, False): selector.BooleanSelector(),
                        _fixed("min_score", near, 0.5): _number(0, 1, 0.01),
                        _opt("persona", near): _text(True),
                        _opt("fixed_replies", near): _text(True),
                    }
                ),
                {"collapsed": True},
            ),
            vol.Required("advanced"): section(
                vol.Schema(
                    {
                        _opt("rule", advanced): _text(True),
                        _fixed("wait_seconds", advanced, 3): _number(0, 6, 0.5, "s"),
                        _fixed("no_helper_role", advanced, "owner"): _choice(
                            [
                                ("owner", "Person 1"),
                                ("wife", "Person 2"),
                                ("stranger", "An unknown voice"),
                            ]
                        ),
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


def memory_settings_error(settings, other_agents) -> str | None:
    """Form error key for the Memory section, or None when it is fine.

    `other_agents` are the entity ids the memory agent may not be: the main agent
    and this router itself.
    """
    memory = settings.get("memory") or {}
    agent = memory.get("agent")
    if agent and agent in other_agents:
        return "memory_agent_invalid"
    if memory.get("enabled") and not agent:
        return "memory_agent_required"
    return None


def memory_list_choices(memory: MemoryStore, entry_id: str, settings) -> list[tuple[str, str]]:
    """(list key, label) of the lists one router entry can see, with their item counts."""
    choices = []
    people: tuple[tuple[Person, str, str], ...] = (
        ("owner", "owner", "Person 1"),
        ("wife", "partner", "Person 2"),
    )
    for person, settings_key, fallback in people:
        name = str((settings.get(settings_key) or {}).get("name") or "").strip() or fallback
        for key, scope in (
            (entry_key(entry_id, person), "this assistant"),
            (global_key(person), "all assistants"),
        ):
            choices.append((key, f"{name}: {scope} ({len(memory.items(key))})"))
    return choices


class PersonaRouterFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PersonaRouterOptionsFlow()

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title=user_input["name"], data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): str,
                    vol.Required("agent"): _agent(),
                }
            ),
        )


class PersonaRouterOptionsFlow(OptionsFlow):
    """Configure dialog: a menu leading to the settings form or the memory editor."""

    def __init__(self) -> None:
        self._list_key = ""
        self._list_label = ""
        # What the memory editor showed, so a save is a diff against it.
        self._shown: list[MemoryItem] = []

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["settings", "memory"])

    def _other_agents(self, settings) -> set[str]:
        """Agents the memory agent may not be: the main agent and any router."""
        return {
            (settings.get("agents") or {}).get("agent"),
            self.config_entry.data.get("agent"),
            *router_agent_ids(self.hass),
        } - {None}

    async def async_step_settings(self, user_input=None):
        errors = {}
        if user_input is not None:
            error = memory_settings_error(user_input, self._other_agents(user_input))
            if same_user_for_both(user_input):
                error = "same_user"
            if error is None:
                return self.async_create_entry(title="", data=user_input)
            errors["base"] = error
        current = user_input or current_settings(self.hass, self.config_entry)
        return self.async_show_form(
            step_id="settings",
            data_schema=settings_schema(current, await login_users(self.hass)),
            errors=errors,
        )

    async def async_step_memory(self, user_input=None):
        """Pick the list to edit."""
        memory = await async_get_memory(self.hass)
        choices = memory_list_choices(
            memory, self.config_entry.entry_id, self.config_entry.options
        )
        if user_input is not None:
            self._list_key = user_input["list"]
            self._list_label = dict(choices)[self._list_key]
            self._shown = memory.items(self._list_key)
            return await self.async_step_memory_edit()
        return self.async_show_form(
            step_id="memory",
            data_schema=vol.Schema({vol.Required("list"): _choice(choices)}),
        )

    async def async_step_memory_edit(self, user_input=None):
        """Edit one list, one fact per line. Saving never touches the entry's options."""
        errors = {}
        placeholders = {"list": self._list_label}
        text = "\n".join(item_line(item) for item in self._shown)
        if user_input is not None:
            text = str(user_input.get("facts") or "")
            memory = await async_get_memory(self.hass)
            try:
                await memory.async_apply_edit(self._list_key, self._shown, text.splitlines())
            except LineTooLongError as err:
                errors["base"] = "line_too_long"
                placeholders["line"] = f"{err.line[:LINE_PREVIEW_LENGTH]}…"
            else:
                return await self.async_step_init()
        return self.async_show_form(
            step_id="memory_edit",
            data_schema=vol.Schema({_opt("facts", {"facts": text}): _text(True)}),
            errors=errors,
            description_placeholders=placeholders,
        )
