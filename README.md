# MulaStream VentureOS — Next Edition

A free, local-first working prototype with a modern responsive UI, user accounts, separate chat histories, venture workspaces, evidence ledger, mission checklist and business scenario calculator.

## Start on Windows
1. Extract the complete ZIP. Do not run from inside the ZIP.
2. Open the `MulaStream_VentureOS_Next` folder and double-click `RUN_WINDOWS.bat`.
3. Visit http://127.0.0.1:8501 and create an account (password at least 12 characters).
4. For AI chat, install Ollama from https://ollama.com/download/windows, run `ollama pull qwen3:4b`, and keep Ollama running.
5. The AI can be offline and the other features still work. Chat questions sent while offline are saved.

## Linux or macOS
`python -m venv .venv` then install `pip install -r requirements.txt`; run `python -m uvicorn app:app --host 127.0.0.1 --port 8501`.

## What's real
- SQLite stores Argon2-hashed account passwords, expiry-limited HTTP-only sessions, ventures, chat threads, messages, unreviewed evidence and mission checkboxes.
- Server checks venture and chat ownership on every relevant route; conversation rename, resume and delete work.
- Financial metrics recompute on saved inputs in Namibian dollars; mission checkboxes are self-reported.
- Ollama runs on the same local machine and is not required on the browsers of other users, once a properly secured deployment exists.

## Important boundaries
This is a local demo, **not** a production-ready investment, banking, or public multi-user service. Do not expose the app directly to the internet. HTTPS, email verification, password recovery, rate limiting, persistent audit logs, secure encrypted backups, regulatory review, document scanning, independent evidence verification, admin workflow, performance tests, accessibility audit and security assessment are needed before production. Account creation has no email verification. Public deployment requires a host, networking and ongoing costs even if the software is free. It uses no remote paid AI API. `COOKIE_SECURE=1` must be used behind real HTTPS; default cookies are appropriate only for localhost. Sessions expire after 8 hours. Database data is not encrypted at rest. Only founder accounts may create ventures; investor accounts can use general mentor chat but cannot view others' private ventures.

No official MulaStream logo was supplied in the accessible project files. The wordmark is represented by a replaceable lettermark; use a licensed official SVG/PNG before public presentation. No fabricated organization branding is claimed.

## Structure
`app.py` API and persistence; `static/index.html`, `style.css`, `app.js` frontend; `data/` generated database; `RUN_WINDOWS.bat` launcher; `tests/` smoke tests.

## Change AI model
Set environment variable `OLLAMA_MODEL` to the installed Ollama model name. Ollama default address is `http://127.0.0.1:11434`.
