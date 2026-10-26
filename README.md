# Bank on a Phone Call

Voice-first loan pre-qualification agent for Indian languages, built on Sarvam AI.

A caller speaks in their language. The agent collects basic details, answers product questions only from the bank policy (with clause ids), reads an income proof photo, and hands a structured summary to a loan officer. It never approves or rejects a loan.

## How it works

| Step | Sarvam API | Model |
|------|------------|-------|
| Caller speech to text | Speech-to-Text | saaras:v4 |
| Reasoning, policy answers, field extraction (enforced JSON output) | Chat Completion | sarvam-105b |
| Agent speech | Text-to-Speech | bulbul:v4-flash |
| Income proof photo to fields | Document AI (Extract) | Sarvam Vision |

The whole policy sits in the prompt, so every product answer can be traced to a clause id. `policy.md` holds sample numbers for the demo. Replace them with the real bank policy.

The officer summary (right side of the page) shows collected fields, extracted document data, policy clauses used, flags (name mismatch, income mismatch, question outside policy) and what is still missing.

## Run locally

Needs Python 3.10 or newer and a Sarvam API key from https://indus.sarvam.ai.

```
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
```

Open `.env` and put your key after `SARVAM_API_KEY=`. Then:

```
python app.py
```

Open http://127.0.0.1:8000, pick a language, press Start call. The microphone works on localhost and on https only.

## Deploy on Render

1. Push this repo to GitHub.
2. On Render, create a new Blueprint (or Web Service) from the repo. `render.yaml` has the settings.
3. Add the environment variable `SARVAM_API_KEY` in Render before the first deploy. The app exits at startup if it is empty.
4. Open the live https link on your phone and test a full call before sharing.

Call state is kept in memory, so a restart clears active calls. Fine for a demo.

## Keep keys out of the repo

`.env` is in `.gitignore`. Never commit a real key.
