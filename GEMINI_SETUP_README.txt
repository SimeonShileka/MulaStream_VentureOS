MULASTREAM GEMINI CHAT - QUICK START (PRESENTATION VERSION)

1. Back up your ORIGINAL VentureOS folder and data/ventureos.sqlite3.
2. Stop the current web server with Ctrl+C. Extract this ZIP as a NEW folder.
3. To preserve accounts and saved chats, copy your previous
   data/ventureos.sqlite3 (with the server STOPPED) into this new project's data folder.
   Do not delete your existing database or use a fresh account unless you want to.
4. Open https://aistudio.google.com/apikey, sign in, create a Gemini API key.
   Verify that your project has access to the free tier (subject to usage limits).
5. In the extracted project folder run:
     python -m pip install -r requirements.txt
6. Double-click START_GEMINI_WINDOWS.bat and paste the API key when asked.
   Do NOT put the key in static/app.js, HTML, GitHub or the chat.
7. Open http://127.0.0.1:8501 and sign in.
8. Test IN ONE conversation:
     I want to start a shoe shop in Windhoek. Help me draft a business plan.
     My customers are local Namibians and my budget is N$10,000.
     Now estimate a sample opening budget, clearly labelled as assumptions.
     What does MulaStream do?
     What was the weather yesterday?  (should decline unrelated query)

REQUIREMENTS:
Internet access is essential. Gemini may be unavailable or limited by free-tier rate limits.
Do not describe an unverified platform policy as confirmed. Do not send real user or
confidential financial information without informed consent; Google free-tier content may
be used to improve products. This is a local prototype, NOT production security hardened.

TO USE IT INSIDE YOUR EXISTING CURRENT PROJECT INSTEAD:
Copy only chatbot2_engine/service.py from this archive to your existing
chatbot2_engine/service.py, after backing up the old file. This assumes your current
app.py calls chatbot2_engine.service.reply, as Enhanced and Timeout Repair versions do.
Then start with GEMINI_API_KEY in the server environment. The frontend stays unchanged.
