"""Config flow and settings screen for Voice Persona Router."""

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

DOMAIN = "voice_persona_router"

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


def _opt(key, current):
    """Optional field that shows the saved value and may be cleared."""
    value = current.get(key)
    if value is None or value == "":
        return vol.Optional(key)
    return vol.Optional(key, description={"suggested_value": value})


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


def settings_schema(current):
    agents = current.get("agents") or {}
    local = current.get("local") or {}
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
            vol.Required("owner"): section(
                vol.Schema(
                    {
                        _opt("name", owner): _text(),
                        _opt("persona", owner): _text(True),
                    }
                ),
                {"collapsed": True},
            ),
            vol.Required("partner"): section(
                vol.Schema(
                    {
                        _opt("name", partner): _text(),
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
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=settings_schema(current_settings(self.hass, self.config_entry)),
        )
