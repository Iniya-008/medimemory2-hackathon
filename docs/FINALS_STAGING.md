# Finals branch: staging setup (do NOT touch the live services)

1. Push this branch: `git checkout -b finals` -> copy the files in -> `git add .` -> `git commit -m "After-visit core loop"` -> `git push -u origin finals`.
2. Render -> New -> PostgreSQL (free) named `medimemory-finals-db`. Copy its Internal Database URL.
3. Render -> New -> Web Service -> same repo, **branch `finals`**, root `backend`.
   Build: `pip install -r requirements.txt`  Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   Environment:
   - DATABASE_URL = (the new staging database URL)
   - JWT_SECRET_KEY = (a new long random string, not the live one)
   - ELEVENLABS_API_KEY = (same key as live, or a separate one)
   - LLM_API_KEY = (Google AI Studio key)
   - LLM_BASE_URL = https://generativelanguage.googleapis.com/v1beta/openai
   - LLM_MODEL = (current Flash model name shown in AI Studio)
   - CORS_ORIGINS = (your staging Vercel URL, once you have it)
4. Vercel -> Add New Project -> same repo, root `frontend`, **production branch `finals`** (Settings -> Git).
   Env: `VITE_API_BASE` = the staging Render URL.
5. Exit check (from the repo root, any laptop with Python):
   `pip install httpx` then `python scripts/core_loop_check.py --base https://<staging>.onrender.com --lang ta`
   Save `core_loop_results.json`: these are the real latency numbers for the pitch.

Never paste API keys into chat, code or GitHub. Keys live only in Render's Environment tab.

## Languages and voice mode (added)
- 50+ answer languages. Voice model per language: Multilingual v2 where ElevenLabs supports it (English, Tamil, Hindi and 26 more), Eleven v3 for the rest (Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati, Punjabi, Urdu, Odia, Assamese, Nepali ...).
- Every translation is machine-made and shown as "not yet checked by a native speaker" until someone verifies it in the app.
- Safety rules for languages other than English/Tamil need the LLM (it translates the question to English first). Without LLM_API_KEY, only English and Tamil questions are safety-checked; always configure the LLM on staging.
- Eleven v3 uses more ElevenLabs credits than Flash/Multilingual. Use "Play all" once per language before the demo so clips are cached.
- Voice conversation (round button): hands-free. Listens, detects when you stop talking (about 1.3 s of silence), answers in the language you spoke, then listens again. Test once on the venue laptop with its real microphone.
