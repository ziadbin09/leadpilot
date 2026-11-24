# LeadPilot — AI Lead Qualifier & Booker

A chat assistant for your website that talks to every visitor, works out whether they are a good fit, and books the sales call for you. Every conversation lands in a scored lead list.

## The problem

Most website visitors leave without saying a word. The ones who do message you wait hours for a reply, get asked the same five questions by hand, and half of them never book. Meanwhile you spend time on leads that were never going to buy.

## The solution

LeadPilot replies in seconds, any time of day. It asks a few friendly questions (what they need, budget, timeline, whether they decide), saves the answers, scores the lead with clear rules, and books a slot on your calendar once it has a valid email. You open the dashboard and see who to call first, and why.

<!-- Add a demo GIF here: record the chat booking a call, save as docs/demo.gif -->

## How it works

Visitor → Gemini (OpenAI-compatible) → tools → SQLite + Calendar → Dashboard

## Features

- Qualifies visitors in a natural chat, one question at a time.
- Rule-based lead scoring (hot / warm / cold). The AI collects facts; plain code does the math, so scores are explainable.
- Books meetings from real free slots. A slot already taken is detected and fresh slots are offered.
- Owner dashboard: stats, tier filters, and a per-lead breakdown of why it scored what it did.
- Works with any OpenAI-compatible provider (Gemini free tier by default).
- Demo mode with a built-in fake calendar, so it runs without any Google account.

## Setup

You need Python 3.11 or newer.

**Windows PowerShell**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then:

1. Get a free key at <https://aistudio.google.com> (sign in, then **Get API key**).
2. Open `.env` in your editor and paste the key after `LLM_API_KEY=` yourself.
3. Start the server:

   ```
   uvicorn app.main:app --reload
   ```

4. Open <http://localhost:8000>. Chat as a visitor, then switch to the **Owner dashboard** tab.

If you start the server without a key, it still runs, but the chat answers with "Server not configured" until you set `LLM_API_KEY`.

## Keep your key safe

- Your key lives only in `.env`. That file is git-ignored: never commit it, paste it into an issue, or share a screenshot of it.
- The app never logs the key, never sends it to the browser, and never stores it in the database.
- If a key ever leaks, revoke it in the provider's console and create a new one.

## Switching providers

Any provider with an OpenAI-compatible API works. Change three lines in `.env`: `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL`. Groq, NVIDIA and OpenAI all work this way (see each provider's docs for the exact base URL and model name). The model must support tool calling, because the assistant saves fields and books meetings through tools.

## Lead scoring

| Signal | Points |
| --- | --- |
| Budget ≥ $5,000 | 40 |
| Budget ≥ $1,000 | 25 |
| Budget below $1,000 | 5 |
| Timeline ≤ 30 days | 30 |
| Timeline ≤ 90 days | 15 |
| Timeline longer | 5 |
| Decision maker | 20 |
| Not the decision maker | 5 |
| Need described | 10 |

Unknown values score 0. Tiers: **hot** ≥ 70, **warm** ≥ 40, otherwise **cold**.

## Guardrails

- A meeting is only booked when a syntactically valid email has been captured.
- Messages are limited to 1,000 characters; empty or whitespace-only messages are rejected.
- Each chat session is capped at 20 visitor messages, then the bot asks for an email. This protects a free-tier quota on a public demo.
- Provider errors (bad key, quota) show the visitor a fixed friendly fallback, never the raw error. Logs record only the error type and status code.
- Budgets written as text ("10k", "$2,500", "not sure") are saved as whole USD or left unknown.
- Tool arguments from the model are validated; malformed ones become an error the model can recover from.
- The assistant only discusses qualifying and booking, and never reveals its instructions or other leads.

## Google Calendar (optional)

Without setup, LeadPilot uses a fake demo calendar. To use a real one:

1. In Google Cloud, create a service account, enable the Google Calendar API, and download the service account JSON key.
2. Save the file somewhere outside git (for example `credentials.json`, which is git-ignored) and set `GOOGLE_CREDENTIALS_FILE` in `.env` to its path.
3. In Google Calendar, open your calendar's **Settings and sharing**, share it with the service account's email address and choose **Make changes to events**.
4. On the same page, copy the **Calendar ID** (for your main calendar this is usually your Gmail address) and set `GOOGLE_CALENDAR_ID` in `.env` to it. Leaving it as `primary` would book into the service account's own calendar, which you cannot see.

Meetings are 30 minutes, in UTC, on weekdays at 10:00, 14:00 and 16:00. If Google cannot read the calendar's free/busy data, LeadPilot refuses to offer or book times rather than guessing. The free/busy check right before booking is best-effort: it greatly reduces double-booking, but it is not a transaction.

## Limitations

- **No authentication on `/leads` or the dashboard.** Add auth before using this with real clients.
- Chat sessions live in memory: they reset when the server restarts, and only the most recent 1,000 are kept.
- Leads are stored in a local SQLite file (`leads.db` in the project folder, git-ignored).
- Demo calendar bookings are kept in memory and reset when the server restarts (saved leads keep their booked time).
- Typing an email that already belongs to a lead updates that lead, so anyone who knows a lead's email can add details to it.
- On the Gemini free tier, Google may use your prompts to improve its models. Use demo data only, not real client details.

## Running the tests

```
python -m pytest
```

Tests use a stub model and a fake calendar. They never touch the network or need a key.
