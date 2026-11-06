# Local Flyer Ads CT AI Receptionist

An ElevenLabs voice agent that answers calls to the Local Flyer Ads CT Google Voice number, answers questions about the $199/month plan, takes a message, and emails Tony a summary after every call.

**Live agent ID:** `agent_6301m6rzrx1ce54vptctfnha3gsz`
**Test it in a browser:** https://elevenlabs.io/app/talk-to?agent_id=agent_6301m6rzrx1ce54vptctfnha3gsz

## Files

| File | What it does |
|---|---|
| `prompt.md` | The receptionist's script: pricing, service details, rules |
| `agent.json` | Agent ID, name, greeting |
| `sync_agent.py` | Pushes `prompt.md` and `agent.json` to the live agent |
| `webhook.py` | Receives the post call event and emails the summary via Resend |

## How calls reach the agent

```
Caller -> Google Voice number -> (no answer) forwards to Twilio number -> ElevenLabs agent
                                                                            |
                                         webhook.py <- post call event -----+
                                             |
                                             +-> email to tcantave@localflyerads.com
```

## Setup

1. **Phone number.** In ElevenLabs, go to Agents > Phone Numbers > Import, connect a Twilio number (about $1.15/month), and assign it to this agent.
2. **Forward Google Voice.** Google Voice app > Settings > Calls > Forward calls to linked numbers, and add the Twilio number as a linked number. Voicemail can stay off since the agent takes messages.
3. **Email summaries.** Deploy `webhook.py` on Railway (start command `python receptionist/webhook.py`), set the env vars listed at the top of the file, then add the Railway URL in ElevenLabs > Agents > Settings > Post call webhook.
4. **Update the script.** Edit `prompt.md`, then run:

```bash
ELEVENLABS_API_KEY=your_key python receptionist/sync_agent.py
```
