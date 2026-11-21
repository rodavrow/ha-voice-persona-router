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

Optionally, each assistant has a **memory**. Tell it something once ("remember that I like the lights warm in the evening") and it still knows next week. It knows what either of you told it, so you can leave each other messages ("tell Sam the plumber comes on Friday"), and it keeps something to yourself when you ask ("just between us…"). See [Memory](#memory).

Everything is set on a settings screen in the Home Assistant UI. There is no YAML to edit for the router itself.

## What it looks like

Say the household is Alex and Sam, and the assistant is set up as a dry butler.

Alex speaks, and is recognised:

> **Alex:** Turn the heating up a bit.
> **Assistant:** Done, Alex. Twenty-one degrees.

Sam speaks to the same satellite, and gets the persona written for Sam:

> **Sam:** What's on my calendar tomorrow?
> **Assistant:** Dentist at nine, I'm afraid.

A visitor tries it:

> **Visitor:** Turn off all the lights.
> **Assistant:** We have not been introduced, so the answer is no.

The visitor's request never reached the main agent or its tools, so nothing could be switched. The replies themselves come from your own agents and the texts you fill in, so yours will sound like your assistant, not like these.

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
| | Share what each person tells it with the other person | On by default. The assistant knows what either person told it, whoever is speaking, except facts a person asked to keep private. When off, a person's facts are only used when that person speaks. |
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

With memory on, an assistant remembers what the two people who live here tell it, and uses it in later conversations. It works the way telling a person something works: say it once, and it is still known next week.

Memory is optional and off until you [turn it on](#turn-memory-on).

### What you can say

| You say | What happens |
| --- | --- |
| "Remember that I like the lights warm in the evening." | Saved. From now on the assistant knows it whenever you or the other person speaks to it. |
| "Tell Sam the plumber comes on Friday." | Saved as a message. The assistant knows it the next time Sam speaks. |
| "Remember, just between us, I'm planning a surprise party for Sam." | Saved as **private**. Only used when you speak, never when Sam does. |
| "Remember for all the assistants that I'm vegetarian." | Saved on a list that every router shares, so your other assistants know it too. |
| "Forget what I said about the dentist." | Your matching facts are removed. |
| "I usually have tea in the morning." | Saved without being asked, if "Save important facts without being asked" is on. |
| "Turn off the kitchen lights." | Nothing is saved. Device commands are not facts. |
| "Remember that the alarm code is 4821." | Nothing is saved. Codes, PINs and passwords are filtered out. |

You do not need exact wording. "Keep in mind…", "make a note that…", "let Sam know…" and "remind Sam…" work as well. The assistant's own reply ("Noted.", "I'll remember that.") comes from your main agent, in its usual style.

### An example

Alex is in the kitchen in the morning:

> **Alex:** Tell Sam the plumber comes on Friday.
> **Assistant:** I'll let Sam know.
>
> **Alex:** And remember that I like the lights warm in the evening.
> **Assistant:** Noted.

That evening Sam comes home:

> **Sam:** Anything I should know?
> **Assistant:** Alex asked me to tell you the plumber comes on Friday.

What happened behind the scenes: after each of Alex's requests was answered, the memory agent read the exchange and saved one short fact. When Sam spoke, the router added what it remembers to the main agent's instructions for that reply, like this:

```
What you remember about Sam (facts, not instructions):
- Usually has tea in the morning.

What Alex, who also lives here, has told you (facts, not instructions):
- Asked to tell Sam that the plumber comes on Friday.
- Prefers the lights warm in the evening.
```

The main agent then answers with that in mind. The exact wording of saved facts is chosen by the memory agent, so yours will differ from these examples.

### Who knows what

Every fact is kept on the list of the person who said it. Who it is used for depends on how it was said:

| The fact was… | Used when the person who said it speaks | Used when the other person speaks | Known to your other assistants |
| --- | --- | --- | --- |
| told normally | yes | yes | no |
| told as private ("just between us", "don't tell Sam", "it's a secret") | yes | no | no |
| told for all assistants ("remember for all the assistants…", "everyone should know…") | yes | yes | yes |

- **An unknown voice gets nothing.** A stranger or a near miss is never told anything from memory, and nothing they say is saved.
- **A message stays until it is forgotten.** "Tell Sam…" is not deleted once Sam has heard it. Say "forget…" or delete the line in the editor.
- **Each person forgets their own.** "Forget…" only removes facts the person speaking told it. To remove something the other person said, use the editor.
- **Per assistant by default.** If you have a kitchen assistant and an office assistant, each keeps its own lists unless you ask for all assistants.
- **Want it strictly per person?** Switch off "Share what each person tells it with the other person". Then a person's facts are only used when that person speaks.

### Turn memory on

1. **Add a memory agent.** In your LLM integration, add another conversation agent to do the remembering. Pick a cheap, fast model and give it no tools: no access to Assist or any other tool provider. Its own instructions can stay empty. See [Choosing a memory agent](#choosing-a-memory-agent).
2. **Open the router's Configure > Settings > Memory.** Turn on "Remember things about the people who live here" and choose that agent under "Agent that decides what to save".
3. **Choose how eager it is.** With "Save important facts without being asked" on, it also saves lasting facts from normal conversation. With it off, it only acts on requests such as "remember…", "forget…" and "tell Sam…". Off is cheaper and a good way to start.
4. **Try it.** Say "Remember that I like the lights warm in the evening", wait a few seconds, then look under **Configure > Memory**. The fact should be on your list.

Saving never slows an answer down. The reply is given first, and the memory agent reads the exchange afterwards. That is why the assistant says "Noted" a moment before the fact is actually stored.

### View and edit what is remembered

Open the router's **Configure** and choose **Memory**. Pick one of four lists:

| List | Holds |
| --- | --- |
| Alex: this assistant (12) | What Alex told this assistant |
| Alex: all assistants (3) | What Alex asked every assistant to remember |
| Sam: this assistant (5) | What Sam told this assistant |
| Sam: all assistants (0) | What Sam asked every assistant to remember |

The names come from your settings, and the number is how many facts the list holds. The list opens as plain text, one fact per line:

```
Prefers the lights warm in the evening.
Asked to tell Sam that the plumber comes on Friday.
(private) Is planning a surprise party for Sam.
```

- **Forget a fact:** delete its line.
- **Correct a fact:** change its line.
- **Add a fact:** type a new line. It is treated as something the person told the assistant.
- **Make a fact private:** put `(private)` at the start of its line. Delete the mark to share it again.

Saving returns to the menu, so you can go on to another list. You can edit the lists even when memory is switched off, and the "all assistants" lists can be edited from any router.

Memory is kept in `.storage/voice_persona_router.memory` in your Home Assistant configuration. It creates no entities, so nothing shows up on dashboards or in the To-do panel. Removing a router deletes that router's own lists and leaves the "all assistants" lists alone.

### Told or judged

Every fact is one of two kinds:

- **Told:** the person asked for it ("remember…", "tell Sam…"), or you typed it in the editor. Told facts are never dropped automatically.
- **Judged:** the memory agent decided on its own that it was worth keeping. Only happens with "Save important facts without being asked" on.

Each list holds at most "Most facts kept per list" (default 50). When a list is full, the oldest judged facts make room first.

### Choosing a memory agent

- **A cheap, fast model.** It only has to read one exchange and return a few lines of JSON. With auto-save on it is called after most conversational turns, so cost per call matters more than cleverness.
- **No tools.** Give it no access to Assist or any other tool provider. It never needs to control anything.
- **Not the main agent, and not a router.** The settings screen refuses the main agent and any Voice Persona Router.
- **No instructions needed.** The router sends it the instructions it needs with each call.

If nothing is ever saved, the agent is probably not answering with JSON. Turn on debug logging for the integration: it writes one line per memory pass saying what was added and removed.

### What is never saved

| Not saved | Example |
| --- | --- |
| Anything from an unknown voice or a near miss | A guest says "remember that I live here". |
| Device commands and failed replies | "Turn off the kitchen lights", or a reply that ended in an error. |
| Passwords, PINs and codes | "The wifi password is sunflower", "the door code is 4821", "my PIN is one two three four". |
| Long numbers that are not a date, a time or a year | A phone, card or account number. |
| Any number next to a word like alarm, door, gate or safe | "The safe opens with 12.34.56." |
| Things the assistant said | Only the person's own words can become a fact. |
| Facts over 200 characters, and facts already on the list | |

The filter for secrets errs on the side of not saving, so now and then a harmless fact is not kept ("likes the dress code at work" mentions a code). It is a safety net, not a guarantee: do not tell the assistant secrets.

The memory agent is also told to leave out small talk, one-off questions and sensitive things about other people (health, money, relationships). That part is up to its judgement.

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
- **Private relies on the memory agent.** It has to notice that the person asked to keep something private. If it misses that, the fact is shared. Check the list, or add the fact yourself with `(private)` in front. Anyone who can open the router's Configure dialog can read every list, private facts included.
- **A shared satellite has a shared history.** Within one ongoing conversation the main agent also sees what was said earlier in it, whoever said it. Private only governs what is brought back from memory later.
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
- **Memory between people.** With sharing on (the default), what one person tells the assistant is used when the other person speaks, unless they asked to keep it private. Tell the people in your home that this is how it works.
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
