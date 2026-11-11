OPEN THIS FOLDER IN VS CODE: MulaStream_VentureOS_DEMO_OPEN_THIS

This is the most complete VentureOS 90-Day Incubator ZIP from our previous builds.
It is NOT the earlier Timeout Repair build.

1. Keep your previous working folder and its data/ventureos.sqlite3 as a backup.
2. Open this folder (the one containing app.py) in VS Code.
3. Run: python -m pip install -r requirements.txt
4. Run: START_GEMINI_WINDOWS.bat, entering the Gemini API key privately.
5. Visit: http://127.0.0.1:8501
6. Test website login, business chat, and the 90-day incubator before judging.

Existing accounts/chats: this ZIP does not contain your old private database.
Stop both servers and copy your previous data/ventureos.sqlite3 into this folder's data/ only if you need to keep those accounts and chats. Back up both database files first.

WHAT THIS BUILD HAS: FastAPI application; login/venture/chat storage; Gemini chatbot connection; business budget calculator; 8-stage incubator with 48 deliverables; draft assessments and stage gates; draft investor dossier JSON export.

KNOWN GAPS: No Twilio WhatsApp webhook; no independent investor deal-discovery portal; no verified gamification token/badge ledger; no secure actual document authenticity verification/mentor approval. Gemini live service needs your account/API key and local testing.

WARNING: For a localhost demonstration. Do not expose the whole application to the public via ngrok until security and webhook validation are implemented.
