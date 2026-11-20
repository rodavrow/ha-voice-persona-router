# Voice Persona Router

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/R5O720EQBI)

By [rodavrow](https://github.com/rodavrow).

A Home Assistant custom integration that makes a voice assistant behave differently depending on who is speaking.

It sits in front of a conversation agent you already have (any LLM agent). For each request it looks up who is speaking, then:

- **Someone who lives here**: the request goes to your normal agent, with a persona for that person added to the prompt. Their messages are stored in the shared history with their name in front, so the agent can tell two people apart in one conversation.
- **An unknown voice**: the request never reaches your normal agent or any of its tools. The assistant refuses instead, either with a line written by a second agent that has no tools, or with one of a list of fixed lines.
- **An unknown voice that came close to matching**: optionally, the assistant says they sound familiar and asks them to say it again.

It can also run Home Assistant's built-in quick commands ("turn off the kitchen lights") only for recognised speakers.

Optionally, each assistant **remembers things about the people who live here**: what they ask it to remember, and lasting facts that come up in conversation. What it remembers about a person is only used when that person is speaking. See [Memory](#memory).

Everything is set on a settings screen in the Home Assistant UI. There is no YAML to edit for the router itself.

> **This is not a security control.** Voice matching can be fooled, and some routes into Home Assistant bypass the router (see [Limits](#limits)). Treat it as a way to give each person their own assistant personality and to keep guests from switching your lights off for fun, not as a lock.

## What you need

- **Home Assistant 2026.11 or newer.** It has only been tested on 2026.11.2. Older versions are missing parts of the conversation history API the router uses.
- **A voice satellite that can tell who is speaking.** The router does not do speaker recognition itself. It reads a helper that you keep up to date with an automation (an example is included).
- **A conversation agent** to answer the people who live here, set up the way you like it.
- **A second conversation agent with no tools**, if you want refusals written by an AI. It must have no access to Assist or any other tool provider. Fixed lines need no second agent.
- **A cheap conversation agent with no tools**, if you want [memory](#memory). It decides what is worth remembering after each reply.

> **Tip:** Have an old Amazon Echo Dot or Echo Show lying around? Check out the excellent [EchoLocal](https://github.com/ygelfand/echolocal) project. It turns supported Echo devices into local Home Assistant voice satellites with voice match (who's speaking). This router was built and tested on EchoLocal satellites, and the [example automation](examples/speaker_tracking_automation.yaml) is written for the "last speaker" and "last speaker score" sensors that EchoLocal's voice match provides.

## Install

### With HACS

1. In HACS, open the menu and choose **Custom repositories**.
2. Add the address of this repository with the type **Integration**.
3. Find **Voice Persona Router** in HACS and download it.
4. Restart Home Assistant.

### By hand

1. Copy the `custom_components/voice_persona_router` folder into the `custom_components` folder of your Home Assistant configuration.
2. Restart Home Assistant.

## Set up

### 1. Create one helper per satellite

The router looks for a text helper named after the **device id** of the satellite the request came from:

```
input_text.voice_speaker_<device id>
```

To find the device id, paste this into **Developer tools > Template**, with your own satellite entity:

```
{{ device_id('assist_satellite.kitchen_satellite') }}
```

Then create a **Text** helper (Settings > Devices & services > Helpers) and name it `voice speaker <device id>`, so that its entity id becomes `input_text.voice_speaker_<device id>`.

The helper holds one of these values:

| Value | Meaning |
| --- | --- |
| `owner` | Person 1 in the router settings |
| `partner` | Person 2 in the router settings |
| `stranger` | Anybody else |
| `pending` | The wake word was heard and the voice match has not arrived yet |
| anything else, or empty | Treated as an unknown voice, so a helper that is not kept up to date refuses instead of answering |

### 2. Keep the helper up to date

[`examples/speaker_tracking_automation.yaml`](examples/speaker_tracking_automation.yaml) is an automation that does this for satellites which expose a "last speaker" sensor and a "last speaker score" sensor. When the satellite starts listening it writes `pending`. When the voice match arrives it writes the role.

Change the entity ids and the two names in it to match your setup. If your speaker recognition reports its result in another way, write the same four values into the helper by whatever means you have.

### 3. Add the router

1. Go to **Settings > Devices & services > Add integration** and pick **Voice Persona Router**.
2. Give it a name, for example `Kitchen assistant (by speaker)`, and choose your main agent.

This creates a new conversation agent with that name. Add the integration once for each assistant personality you want to route.

### 4. Fill in the settings

Open the new entry and choose **Configure**, then **Settings**. See [Settings](#settings) below.

### 5. Point your voice assistant at the router

1. Go to **Settings > Voice assistants** and open the assistant your satellite uses.
2. Set **Conversation agent** to the router you just added.
3. Switch **Prefer handling commands locally** off.

The last step matters. With that option on, Home Assistant runs its built-in commands before the router is asked anything, so an unknown voice could still switch things on and off. With it off, the router tries the built-in commands itself, and only for a recognised speaker.

### Phone app and browser

The phone app, the Assist chat window in the browser and other devices without a helper cannot match a voice. They do send the Home Assistant user who is logged in, so choose each person's **Home Assistant user** in the settings. For a request from a device without a helper, the router then works it out like this:

1. Logged in as the user chosen for Person 1 or Person 2: that person.
2. Logged in as any other user, once at least one person has a user chosen: an unknown voice, so a guest account gets a refusal.
3. No user at all, or no users chosen in the settings: whatever "A device without speaker recognition is" says.

A satellite with a helper is always decided by voice, whoever is logged in elsewhere.

## Settings

Changes apply to the next request. No restart is needed.

| Section | Setting | What it does |
| --- | --- | --- |
| **Agents** | Main agent | Answers Person 1 and Person 2, with its normal tools. |
| **Built-in commands** | Try built-in commands first | A request that exactly matches one of Home Assistant's own commands is carried out at once, without the main agent. Recognised speakers only. |
| | Leave questions and music searches to the main agent | State questions ("is the door closed") and play-music requests go to the main agent even when a built-in command matches. |
| **Memory** | Remember things about the people who live here | Turns memory on for this assistant. Needs the agent below. |
| | Agent that decides what to save | Reads each exchange after the reply has been given. Must not be the main agent or the router. Give it no tool providers. |
| | Save important facts without being asked | When off, only "remember" and "forget" requests change the memory. |
| | Most facts kept per list | 10 to 200, default 50. Also the most facts shown to the main agent. |
| | Use the lists shared by all assistants | Read the shared lists, and save to them when the person asks for all assistants to remember something. |
| **Person 1**, **Person 2** | Name | Put in front of that person's messages in the shared history. |
| | Home Assistant user | Requests from the phone app, the browser or any other device without a helper, made while logged in as this user, count as this person. See [Phone app and browser](#phone-app-and-browser). |
| | Persona | Instructions added to the main agent's prompt when that person speaks. |
| **Unknown voices** | How to answer | A refusal written by an agent without tools, or fixed lines only. |
| | Agent that writes the refusal | Must have no tool providers, and may not be the main agent. |
| | Instructions for the refusal | What the refusal agent is told about the person speaking. |
| | Fixed lines | One per row. Used when fixed lines are chosen, and as a fallback when the refusal agent fails or takes longer than 6 seconds. |
| **Almost recognised** | Ask to try again on a near miss | Turns the "you sound familiar" reply on. |
| | Lowest score that counts as a near miss | Compared with the satellite's last speaker score sensor. |
| | Instructions and fixed lines | The same idea as for unknown voices, for the try-again reply. |
| **Advanced** | Shared history rule | Added to the main agent's prompt after the persona. Use it to explain the name labels. |
| | Wait for the voice match | How long to wait while the helper says `pending`. If no match arrives in time, the voice counts as unknown. |
| | A device without speaker recognition is | Who to assume for a device with no helper when no Home Assistant user decides it: nobody is logged in, or no user is chosen under Person 1 or Person 2. |

### Example texts

Say the household is Alex and Sam, and the assistant is a sarcastic butler.

**Person 1 persona**

> The person speaking is Alex. Their partner is called Sam. Behave exactly as your main instructions say. Use their name only when it comes naturally, not in every reply.

**Instructions for the refusal**

> You do not know the person speaking. They are not part of this household. In your usual style, politely and drily refuse to help. Do not carry out the request and do not give out any information about the house or the people who live in it. One or two sentences at most.

**Fixed lines**

```
I'm afraid I only take instructions from the household.
We have not been introduced, so the answer is no.
```

**Shared history rule**

> The conversation history is shared by the household. Every user message starts with the name of the person who said it, followed by a colon. Answer only the person named at the start of the latest message. Never start your own reply with a name and a colon, and never read these labels aloud.

## Memory

With memory on, an assistant remembers facts about Person 1 and Person 2 and is told them again each time that person speaks.

### What is remembered, and for whom

- **Per person.** Every fact belongs to the person who was speaking when it was saved. When Person 1 speaks, the assistant is told Person 1's facts and none of Person 2's.
- **Per assistant by default.** A fact told to one router is only known to that router. If you have a kitchen assistant and an office assistant, each keeps its own lists.
- **For all assistants on request.** If the person says so ("remember for all the assistants that I am vegetarian", "everyone should know…"), the fact goes on a list shared by every router.
- **Told or judged.** "Remember that…" always saves. With "Save important facts without being asked" on, lasting facts that come up in conversation are saved as well: preferences, people, plans with dates, routines. "Forget…" removes matching facts.
- **Never for unknown voices.** An unknown voice or a near miss is never told anything from memory, and nothing they say is saved.

Saving never slows an answer down. The reply is given first, and the memory agent looks at the exchange afterwards. Because of that, the assistant confirms a "remember" request before the fact is actually stored a moment later.

### View and edit what is remembered

Open the router's **Configure**, choose **Memory**, and pick a list, for example "Alex: this assistant (12)" or "Alex: all assistants (3)". The list is shown one fact per line:

- delete a line to forget it
- change a line to correct it
- type a new line to add a fact

Saving returns to the menu, so you can go on to another list. The lists shared by all assistants can be edited from any router. This works even when memory is switched off.

Memory is kept in `.storage/voice_persona_router.memory` in your Home Assistant configuration. It creates no entities, so nothing shows up on dashboards or in the To-do panel. Removing a router deletes that router's own lists and leaves the shared lists alone.

### Choosing a memory agent

Add a second conversation agent for this and choose it under **Settings > Memory**:

- **A cheap, fast model.** It is called once after each conversational turn and only has to return a few lines of JSON.
- **No tools.** Give it no access to Assist or any other tool provider. It only needs to read an exchange and answer.
- **Not the main agent, and not a router.** The settings screen refuses the main agent and any Voice Persona Router.
- Its own instructions can stay empty. The router sends it the instructions it needs with each call.

### What is never saved

- Anything from an unknown voice or a near miss.
- Device commands handled by Home Assistant's built-in commands, and replies that ended in an error.
- Secrets: anything that mentions a password, PIN, code or similar word, a card or account number, or any run of four or more digits (also spelled out, or split by spaces or punctuation) that is not a date, a time or a year. Next to words such as alarm, door, gate or safe, any such number is dropped. This filter errs on the side of not saving, so now and then a harmless fact is not kept. It is a safety net, not a guarantee: do not tell the assistant secrets.
- Anything the assistant itself said. Only the person's own words can become a fact, and only a request to remember can put a fact on the shared lists.
- Facts longer than 200 characters, and facts that are already on the list.

The memory agent is also told to leave out small talk, one-off questions and sensitive things about other people (health, money, relationships), but that part is up to its judgement.

## How unknown voices are kept away from your devices

- The main agent is never called for an unknown voice, so none of its tools can run.
- The refusal is written by a separate agent in a conversation of its own, with only the refusal instructions. Give that agent no tool providers.
- The exchange is removed from the shared history, so it cannot influence later answers.
- Built-in commands are only tried for Person 1 and Person 2.
- The fixed lines are never empty for an unknown voice. If you leave them blank, a plain "Sorry, I can't help you." is used.

The near-miss reply needs a sensor on the satellite's device whose entity id ends in `_last_speaker_score`.

## Limits

- **Sentence-trigger automations bypass the router.** Home Assistant runs automations with a sentence trigger before any conversation agent is asked.
- **Voice triggers handled on the satellite itself bypass it too**, if your satellite firmware has them.
- **Devices without a helper go by the logged-in user, not the voice.** Anyone using a phone that is logged in as Person 1 is treated as Person 1. If no users are chosen, these devices count as Person 1 unless you change "A device without speaker recognition is".
- **Two people and strangers.** There are exactly two personas.
- **If the lookup itself fails**, the router answers as the main agent without a persona.
- **Built-in commands wait for the voice match** and are answered with a spoken reply, where Home Assistant on its own may only play a short acknowledge sound.
- **Only assistants that use the router are covered.** Any other voice assistant you have set up is unaffected.
- **Memory costs a second model call.** With memory on, the memory agent is called after each conversational turn (not for built-in commands or very short requests). That adds cost, not waiting time. With "Save important facts without being asked" off it is only called for remember and forget requests.
- **Remembered facts are only as good as the memory agent's judgement.** It can save something trivial, miss something important or word a fact wrongly. Check the lists now and then under Configure > Memory.
- **Remember and forget requests are recognised in English.** With auto-save off, a request in another language is not picked up.
- English is the only translation of the settings screen.

## Troubleshooting

Turn on debug logging for the integration (the entry's menu > **Enable debug logging**) to see whether a request was handled by a built-in command.

| Problem | Likely cause |
| --- | --- |
| Everyone is treated as Person 1 | No helper exists with the device id of that satellite, so the "device without speaker recognition" setting applies. On the phone app or browser, choose each person's Home Assistant user in the settings. |
| The phone app or browser is refused | Users are chosen in the settings, and the one logged in is not one of them. |
| Recognised people are refused | The helper still says `pending` when the wait runs out. Raise "Wait for the voice match", or check that your automation writes the role. |
| A satellite refuses everyone | Its helper is empty or holds a value other than `owner`, `partner`, `stranger` or `pending`. Check that the automation includes this satellite and writes exactly those words. |
| An unknown voice can still switch things | "Prefer handling commands locally" is still on for that voice assistant, or the command is a sentence-trigger automation. |
| The refusal is always a fixed line | The refusal agent is missing, is the same as the main agent, returned an error, or took longer than 6 seconds. |
| Nothing is remembered | Memory is off, no memory agent is chosen, or the memory agent does not answer with JSON. Turn on debug logging to see one line per memory pass. |

## Development

The tests use Home Assistant's own test package, pinned to the Home Assistant version the integration targets. Home Assistant only runs on Linux and macOS, so on Windows run them in Docker:

```
docker build -f Dockerfile.test -t voice-persona-router-test .
docker run --rm -v "$PWD:/src" voice-persona-router-test
```

On Linux or macOS with Python 3.14 you can run them directly:

```
python -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest
```

## Privacy

The router sends nothing anywhere by itself. It has no telemetry, no analytics and no network calls of its own. All the same, it does handle what people say, so here is where that goes:

- **Your conversation agents.** The words spoken, plus the persona and history-rule text from your settings, are passed to the main agent and the refusal agent you picked. If either one is a cloud LLM, that text leaves your network under that provider's terms. The router has no control over what they keep.
- **Settings.** Names, personas, instructions and fixed lines are saved in Home Assistant's own configuration storage (`.storage/core.config_entries`), the same place as every other integration's settings.
- **Shared history.** Messages from Person 1 and Person 2 stay in Home Assistant's conversation history with their name in front, the same as with any other agent. Exchanges with unknown voices are removed from it.
- **Logs.** With debug logging on, the router writes the text of each spoken request to the Home Assistant log. Turn debug logging off again when you are done, and check the log before you share it in a bug report.
- **Home Assistant users.** If you choose a user for Person 1 or Person 2, the router stores that user's internal id in its settings and compares it with the user behind each request. Nothing about the user is sent anywhere.
- **Memory.** With memory on, each exchange with a recognised person (their words and the assistant's reply), together with what is already remembered about them, is sent to the memory agent you chose. If that is a cloud LLM, it leaves your network under that provider's terms. The remembered facts are stored unencrypted in `.storage/voice_persona_router.memory` and are included in Home Assistant backups. With debug logging on, saved and removed facts are written to the log.
- **Voice data.** The router never sees audio or voiceprints. Speaker recognition happens on your satellite. The router only reads the role (`owner`, `partner`, `stranger`, `pending`) from your helper and, for near misses, the score sensor.

Tell the people in your home, and your guests, that the assistant recognises voices and, if you use a cloud agent, that what they say may be sent to it.

## Disclaimer

- This is an independent community project. It is not affiliated with, endorsed by or supported by Home Assistant, the Open Home Foundation or Nabu Casa, or any voice hardware or AI provider.
- **It is not a security control.** Do not rely on it to protect locks, alarms, garage doors, cameras or anything else where a wrong decision could cause harm or a loss. Voice recognition can be fooled or get it wrong, and some routes bypass the router entirely (see [Limits](#limits)).
- Replies come from AI models that can be wrong, rude or unpredictable. You are responsible for the agents you connect, the instructions you give them and what they do in your home.
- You are responsible for following the privacy and recording laws where you live, including getting consent from anyone whose voice is recognised.
- The software is provided "as is", without warranty of any kind. See [LICENSE](LICENSE).

## Support

If this is useful to you, you can buy me a coffee:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/R5O720EQBI)

Bug reports and feature requests go to the [issue tracker](https://github.com/rodavrow/ha-voice-persona-router/issues). Donations are entirely optional and do not buy priority support.

## License

[MIT](LICENSE) © 2026 rodavrow
