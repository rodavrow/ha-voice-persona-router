# SPDX-FileCopyrightText: 2026 rodavrow
# SPDX-License-Identifier: MIT
"""Conversation entity that adds a per-speaker persona and delegates to another agent.

Settings come from the settings screen of the entry (its options). An entry
that has no saved settings yet uses the older "who is speaking" script named
in its data, if there is one.

Either source produces the same lookup result:
  persona_for_this_message  prompt text appended for this reply
  rule                      extra prompt text
  label                     optional name of the speaker. The user message is
                            stored in the shared history as "<label>: <text>"
  fixed_replies             optional list of lines. If not empty, one is spoken,
                            the real agent (and its tools) is never called and
                            the exchange is kept out of the shared history
  reply_agent               optional entity id of a separate agent that has no
                            tools. If set, that agent writes the reply from
                            persona_for_this_message alone, in a conversation
                            of its own. The real agent (and its tools) is never
                            called and the exchange is kept out of the shared
                            history. If that agent fails or is slow, one line
                            from fixed_replies is spoken instead.
"""

import asyncio
import logging
import random

from homeassistant.components import conversation
from homeassistant.components.conversation.chat_log import (
    DATA_CHAT_LOGS,
    UserContent,
    current_chat_log,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import intent
from homeassistant.util import ulid

from .memory import (
    REMEMBER_RULE,
    Exchange,
    MemorySettings,
    active_memory_settings,
    async_run_extraction,
    entry_key,
    get_loaded_memory,
    global_key,
    memory_block,
    should_extract,
)
from .speaker import Role, resolve_speaker

_LOGGER = logging.getLogger(__name__)
SCRIPT_TIMEOUT = 8
REPLY_AGENT_TIMEOUT = 6
LAST_RESORT_REPLY = "Sorry, I can't help you."
SETTINGS_KEY = {"owner": "owner", "wife": "partner"}


def _lines(text):
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _leave_to_main_agent(result):
    """Built-in commands that the main agent answers better: state questions and music searches."""
    return result.intent.name in ("HassGetState", "HassMediaSearchAndPlay")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    async_add_entities([PersonaRouter(entry)])


class PersonaRouter(conversation.ConversationEntity):
    _attr_supports_streaming = True

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_name = entry.title
        self._attr_unique_id = entry.entry_id
        self._last_fixed: str | None = None

    @property
    def supported_languages(self):
        return MATCH_ALL

    def _main_agent(self):
        chosen = (self._entry.options.get("agents") or {}).get("agent")
        return chosen or self._entry.data["agent"]

    def _turn_log(self, user_input):
        """Return the chat log of the running turn if its last entry is this user message."""
        log = current_chat_log.get()
        if log is None or log.conversation_id != user_input.conversation_id:
            log = self.hass.data.get(DATA_CHAT_LOGS, {}).get(user_input.conversation_id or "")
        if log is None or not log.turn_active or len(log.content) < 2:
            return None
        last = log.content[-1]
        if last.role != "user" or last.content != user_input.text:
            return None
        return log

    def _speak(self, user_input, text):
        """Speak a line without calling the real agent and keep the exchange out of the shared history."""
        try:
            log = self._turn_log(user_input)
            if log is not None:
                del log.content[-1]
                log.turn_start = min(log.turn_start, len(log.content))
        except Exception:  # noqa: BLE001 - tidying the history must never block the reply
            _LOGGER.exception("Could not keep the reply out of the history")
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(text)
        return conversation.ConversationResult(
            response=response,
            conversation_id=user_input.conversation_id or ulid.ulid_now(),
            continue_conversation=False,
        )

    def _fixed_reply(self, user_input, replies):
        """Answer with one of the fixed lines, without calling the real agent."""
        choices = [r for r in replies if r != self._last_fixed] or replies
        text = random.choice(choices)
        self._last_fixed = text
        return self._speak(user_input, text)

    async def _reply_agent_text(self, user_input, agent_id, persona):
        """Let a separate agent without tools write the reply, in a conversation of its own."""
        try:
            async with asyncio.timeout(REPLY_AGENT_TIMEOUT):
                result = await conversation.async_converse(
                    self.hass,
                    text=user_input.text,
                    conversation_id=None,
                    context=user_input.context,
                    language=user_input.language,
                    agent_id=agent_id,
                    extra_system_prompt=persona or None,
                )
            response = result.response
            if response.response_type == intent.IntentResponseType.ERROR:
                _LOGGER.warning("Reply agent returned an error, using a fixed line")
                return None
            speech = (response.speech.get("plain") or {}).get("speech") or ""
            return str(speech).strip() or None
        except Exception:  # noqa: BLE001 - a failed reply agent must never block the reply
            _LOGGER.exception("Reply agent failed, using a fixed line")
            return None

    def _labelled_text(self, user_input, label) -> str:
        """Store the user message as '<label>: <text>' and return that text."""
        text = user_input.text
        label = str(label or "").strip()
        if not label:
            return text
        labelled = f"{label}: {text.strip()}"
        try:
            log = self._turn_log(user_input)
            if log is not None:
                old = log.content[-1]
                log.content[-1] = UserContent(content=labelled, attachments=old.attachments)
        except Exception:  # noqa: BLE001 - labelling must never block the reply
            _LOGGER.exception("Could not label the user message")
            return text
        return labelled

    async def _helper_state(self, device_id, advanced) -> str | None:
        """Read the voice_speaker helper of the satellite, or None if it has none.

        Waits a little while the helper says pending, because the match lands a
        few seconds after the wake word.
        """
        helper = f"input_text.voice_speaker_{device_id or ''}"
        state = self.hass.states.get(helper)
        if state is None:
            return None
        try:
            steps = int(float(advanced.get("wait_seconds", 3)) * 10)
        except (TypeError, ValueError):
            steps = 30
        for _ in range(max(steps, 0)):
            if state.state != "pending":
                break
            await asyncio.sleep(0.1)
            state = self.hass.states.get(helper)
            if state is None:
                return None
        return state.state

    async def _who_is_speaking(self, user_input, settings) -> tuple[Role, bool]:
        """Return the role and whether a voice match decided it."""
        advanced = settings.get("advanced") or {}
        helper_state = await self._helper_state(user_input.device_id, advanced)
        user_id = user_input.context.user_id if user_input.context else None
        user_map: list[tuple[Role, str | None]] = [
            (role, (settings.get(SETTINGS_KEY[role]) or {}).get("user"))
            for role in ("owner", "wife")
        ]
        return resolve_speaker(
            helper_state, user_id, user_map, advanced.get("no_helper_role")
        )

    def _memory_settings(self) -> MemorySettings | None:
        """Memory settings of this router, or None when memory is not active."""
        return active_memory_settings(
            self._entry.options, (self._main_agent(), self.entity_id)
        )

    def _memory_block(self, who, name, settings: MemorySettings) -> str:
        """What this assistant remembers about one person. Reads memory only, no I/O."""
        memory = get_loaded_memory(self.hass)
        if memory is None:
            return ""
        shared = memory.items(global_key(who)) if settings.use_global else []
        return memory_block(
            name,
            memory.items(entry_key(self._entry.entry_id, who)),
            shared,
            max_items=settings.max_items,
        )

    def _start_memory_pass(self, user_input, resp, result) -> None:
        """Let the memory agent look at a finished turn, in the background.

        Only for a recognised person whose turn the main agent answered. The reply
        never waits for this.
        """
        try:
            if not resp or resp.get("who") not in ("owner", "wife"):
                return
            settings = self._memory_settings()
            memory = get_loaded_memory(self.hass)
            if settings is None or memory is None:
                return
            if result.response.response_type == intent.IntentResponseType.ERROR:
                return
            if not should_extract(user_input.text, auto_save=settings.auto_save):
                return
            exchange = Exchange(
                entry_id=self._entry.entry_id,
                person=resp["who"],
                name=str(resp.get("label") or ""),
                user_text=user_input.text,
                reply_text=str((result.response.speech.get("plain") or {}).get("speech") or ""),
                language=user_input.language,
                context=user_input.context,
            )
            self.hass.async_create_background_task(
                async_run_extraction(self.hass, memory, settings, exchange),
                name=f"{self.entity_id} memory pass",
            )
        except Exception:  # noqa: BLE001 - memory must never block the reply
            _LOGGER.exception("Could not start the memory pass")

    def _last_score(self, device_id):
        """Voice match score of the satellite's last request, if it reports one."""
        if not device_id:
            return None
        registry = er.async_get(self.hass)
        for entity in er.async_entries_for_device(registry, device_id):
            if entity.entity_id.endswith("_last_speaker_score"):
                state = self.hass.states.get(entity.entity_id)
                try:
                    return float(state.state)
                except (AttributeError, TypeError, ValueError):
                    return None
        return None

    async def _lookup_from_settings(self, user_input, settings):
        """Work out who is speaking and what to do with them, from the settings screen."""
        advanced = settings.get("advanced") or {}
        who, matched = await self._who_is_speaking(user_input, settings)
        rule = str(advanced.get("rule") or "").strip()

        if who != "stranger":
            person = settings.get(SETTINGS_KEY[who]) or {}
            name = str(person.get("name") or "").strip()
            memory = ""
            memory_settings = self._memory_settings()
            if memory_settings is not None:
                memory = self._memory_block(who, name, memory_settings)
                rule = "\n".join(part for part in (rule, REMEMBER_RULE) if part)
            return {
                "who": who,
                "persona_for_this_message": str(person.get("persona") or "").strip(),
                "memory": memory,
                "rule": rule,
                "label": name,
                "fixed_replies": [],
                "reply_agent": "",
            }

        strangers = settings.get("strangers") or {}
        persona = str(strangers.get("persona") or "").strip()
        lines = _lines(strangers.get("fixed_replies"))
        near = settings.get("near_miss") or {}
        if matched and near.get("enabled"):
            score = self._last_score(user_input.device_id)
            try:
                lowest = float(near.get("min_score", 0.5))
            except (TypeError, ValueError):
                lowest = 0.5
            if score is not None and score >= lowest:
                who = "near_miss"
                persona = str(near.get("persona") or "").strip() or persona
                lines = _lines(near.get("fixed_replies")) or lines
        reply_agent = ""
        if strangers.get("mode", "ai") == "ai":
            reply_agent = str(strangers.get("reply_agent") or "").strip()
        return {
            "who": who,
            "persona_for_this_message": persona,
            "rule": rule,
            "label": "",
            # Never empty for an unknown voice, so the real agent stays out of reach.
            "fixed_replies": lines or [LAST_RESORT_REPLY],
            "reply_agent": reply_agent,
        }

    async def _try_built_in(self, user_input, log, local):
        """Run the request through the built-in commands, using the given history."""
        intent_filter = _leave_to_main_agent if local.get("leave_questions", True) else None
        response = await conversation.async_handle_intents(
            self.hass, user_input, log, intent_filter=intent_filter
        )
        if response is None:
            _LOGGER.debug(f"No built-in command for: {user_input.text}")
            return None
        _LOGGER.debug(f"Built-in command handled: {user_input.text}")
        speech = (response.speech.get("plain") or {}).get("speech") or ""
        log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=conversation.HOME_ASSISTANT_AGENT, content=speech)
        )
        return conversation.ConversationResult(response=response, conversation_id=log.conversation_id)

    async def _local_command(self, user_input, log, local, text):
        """Let Home Assistant's built-in commands handle the request, if one matches exactly.

        Only called for a recognised speaker. Returns None when nothing matched,
        so the main agent answers instead.
        """
        if not local.get("enabled", True):
            return None
        try:
            if log is not None:
                return await self._try_built_in(user_input, log, local)
            # No voice assistant opened the history for this request, so open it here.
            from homeassistant.components.conversation.chat_log import async_get_chat_log
            from homeassistant.helpers.chat_session import async_get_chat_session

            with (
                async_get_chat_session(self.hass, user_input.conversation_id) as session,
                async_get_chat_log(self.hass, session, user_input) as own_log,
            ):
                place = len(own_log.content) - 1
                handled = await self._try_built_in(user_input, own_log, local)
                if handled is not None and text != user_input.text:
                    old = own_log.content[place]
                    if old.role == "user":
                        own_log.content[place] = UserContent(content=text, attachments=old.attachments)
                return handled
        except Exception:  # noqa: BLE001 - the main agent can still answer
            _LOGGER.exception("Built-in command handling failed, asking the main agent")
            return None

    async def _lookup_from_script(self, user_input):
        """Older way: ask the 'who is speaking' script named in the entry data."""
        script = self._entry.data.get("script")
        if not script:
            return None
        async with asyncio.timeout(SCRIPT_TIMEOUT):
            return await self.hass.services.async_call(
                "script",
                script.split(".", 1)[1],
                {"device": user_input.device_id or ""},
                blocking=True,
                return_response=True,
            )

    async def async_process(self, user_input):
        """Find out who is speaking, then let the right agent answer."""
        extra = user_input.extra_system_prompt
        resp = None
        try:
            settings = self._entry.options
            if settings:
                resp = await self._lookup_from_settings(user_input, settings)
            else:
                resp = await self._lookup_from_script(user_input)
            if resp:
                parts = [
                    resp.get("persona_for_this_message"),
                    resp.get("memory"),
                    resp.get("rule"),
                    extra,
                ]
                extra = "\n\n".join(p for p in parts if p) or None
        except Exception:  # noqa: BLE001 - a failed lookup must never block the reply
            resp = None
            _LOGGER.exception("Persona lookup failed, answering without a persona")

        text = user_input.text
        main_agent = self._main_agent()
        if resp:
            replies = resp.get("fixed_replies")
            if isinstance(replies, str):
                replies = [replies]
            if isinstance(replies, list):
                replies = [str(r).strip() for r in replies if str(r).strip()]
            else:
                replies = []

            reply_agent = str(resp.get("reply_agent") or "").strip()
            if reply_agent:
                # From here on the real agent, and with it every tool, is out of reach.
                written = None
                if reply_agent in (main_agent, self.entity_id):
                    _LOGGER.error("reply_agent must not be the real agent or this router, using a fixed line")
                else:
                    written = await self._reply_agent_text(
                        user_input, reply_agent, resp.get("persona_for_this_message")
                    )
                if written:
                    return self._speak(user_input, written)
                return self._fixed_reply(user_input, replies or [LAST_RESORT_REPLY])

            if replies:
                return self._fixed_reply(user_input, replies)
            log = self._turn_log(user_input) or current_chat_log.get()
            text = self._labelled_text(user_input, resp.get("label"))
            if resp.get("who") in ("owner", "wife"):
                handled = await self._local_command(
                    user_input, log, self._entry.options.get("local") or {}, text
                )
                if handled is not None:
                    return handled

        result = await conversation.async_converse(
            self.hass,
            text=text,
            conversation_id=user_input.conversation_id,
            context=user_input.context,
            language=user_input.language,
            agent_id=main_agent,
            device_id=user_input.device_id,
            satellite_id=user_input.satellite_id,
            extra_system_prompt=extra,
        )
        self._start_memory_pass(user_input, resp, result)
        return result
