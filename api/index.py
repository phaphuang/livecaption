import os
import json
import time
import uuid
import asyncio
import httpx
import firebase_admin
from firebase_admin import credentials, db
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

app = FastAPI()

# Get the directory where this file is located
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)  # Parent of api/ folder

# Serve static files from root directory
@app.get("/")
async def root():
    return FileResponse(os.path.join(ROOT_DIR, "index.html"))

@app.get("/audience.html")
async def audience():
    return FileResponse(os.path.join(ROOT_DIR, "audience.html"))

@app.get("/s/{session_id}")
async def short_link(session_id: str):
    return FileResponse(os.path.join(ROOT_DIR, "audience.html"))

# Public config endpoint for client-side Firebase connection
@app.get("/api/config")
async def get_config():
    """Return public Firebase Web SDK configuration for client-side use.

    These values (apiKey, authDomain, etc.) are safe to expose — Firebase
    access control is enforced by Realtime Database security rules, not by
    keeping this config secret.
    """
    return {
        "firebase_api_key": os.environ.get("FIREBASE_API_KEY", ""),
        "firebase_auth_domain": os.environ.get("FIREBASE_AUTH_DOMAIN", ""),
        "firebase_database_url": os.environ.get("FIREBASE_DATABASE_URL", ""),
        "firebase_project_id": os.environ.get("FIREBASE_PROJECT_ID", ""),
        "firebase_app_id": os.environ.get("FIREBASE_APP_ID", ""),
        "deepgram_api_key": os.environ.get("DEEPGRAM_API_KEY", ""),
        "stt_provider": "deepgram" if os.environ.get("DEEPGRAM_API_KEY") else "webspeech"
    }

# Environment variables
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")
FIREBASE_DATABASE_URL = os.environ.get("FIREBASE_DATABASE_URL")
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")

# API URLs
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

# Lazy-initialized Firebase Admin app — writes with this app bypass
# Realtime Database security rules (server is fully trusted), while the
# client-side SDK only ever gets read access via those rules.
_firebase_app = None

def get_captions_ref(session_id: str):
    global _firebase_app
    if not FIREBASE_DATABASE_URL or not FIREBASE_SERVICE_ACCOUNT_JSON:
        return None
    if _firebase_app is None:
        cred = credentials.Certificate(json.loads(FIREBASE_SERVICE_ACCOUNT_JSON))
        _firebase_app = firebase_admin.initialize_app(cred, {
            "databaseURL": FIREBASE_DATABASE_URL
        })
    return db.reference(f"sessions/{session_id}", app=_firebase_app)


# Health check
@app.get("/api")
async def root():
    return {"status": "ok", "message": "LiveCaption API"}


# Session endpoint
@app.post("/api/session")
async def create_session():
    """Create a new session and return session_id."""
    session_id = str(uuid.uuid4())[:8]
    ref = get_captions_ref(session_id)
    if not ref:
        return JSONResponse(
            status_code=500,
            content={"error": "Firebase not configured"}
        )

    try:
        await run_in_threadpool(ref.set, {
            "en": "",
            "th": "",
            "zh": "",
            "updated_at": time.time()
        })

        return {"session_id": session_id}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to create session: {str(e)}"}
        )


# Translation request model
class TranslateRequest(BaseModel):
    text: str
    session_id: str
    is_final: bool = False
    delta: str = ""  # New portion since last final — if set, only translate this and append


# Translation helper using OpenAI GPT-4o-mini
async def translate_with_openai(text: str, target_lang: str) -> str:
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    lang_names = {"th": "Thai", "zh": "Chinese"}
    lang_name = lang_names.get(target_lang, target_lang)
    
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": (
                    f"Translate the following English text to {lang_name}. "
                    "Preserve the sentence structure: output one translated sentence per line, "
                    "matching the number of sentences in the input. Output only the translation, no explanations."
                )
            },
            {
                "role": "user",
                "content": text
            }
        ],
        "temperature": 0.1,
        "max_tokens": 500
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            OPENAI_CHAT_URL,
            headers=headers,
            json=payload,
            timeout=10.0
        )
        
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()


# Translate endpoint
@app.post("/api/translate")
async def translate(request: TranslateRequest):
    """Save English immediately, then translate and update."""
    session_id = request.session_id
    ref = get_captions_ref(session_id)
    if not ref:
        return JSONResponse(
            status_code=500,
            content={"error": "Firebase not configured"}
        )

    try:
        en_text = request.text.strip()
        delta = (request.delta or "").strip()

        # Step 1: Save English to Firebase IMMEDIATELY
        # English audience sees text with near-zero delay
        await run_in_threadpool(ref.update, {
            "en": en_text,
            "updated_at": time.time()
        })

        # Step 2: Only translate on final results to avoid wasting API calls
        if not request.is_final or not OPENAI_API_KEY:
            return {"en": en_text, "th": "", "zh": ""}

        # Step 3: Decide what to translate — delta if available, otherwise full text
        # Translating only the delta keeps already-translated text STABLE
        translate_text = delta if delta else en_text
        if not translate_text:
            return {"en": en_text, "th": "", "zh": ""}

        th_task = translate_with_openai(translate_text, "th")
        zh_task = translate_with_openai(translate_text, "zh")
        th_new, zh_new = await asyncio.gather(th_task, zh_task)

        # Step 4: If delta-mode, fetch existing translation and append
        if delta:
            existing = await run_in_threadpool(ref.get) or {}
            existing_th = (existing.get("th") or "").strip()
            existing_zh = (existing.get("zh") or "").strip()

            th_text = (existing_th + " " + (th_new or "")).strip() if existing_th else (th_new or "")
            zh_text = (existing_zh + (zh_new or "")).strip() if existing_zh else (zh_new or "")
        else:
            th_text = th_new or ""
            zh_text = zh_new or ""

        # Step 5: Update Firebase with the (possibly appended) translations
        await run_in_threadpool(ref.update, {
            "en": en_text,
            "th": th_text,
            "zh": zh_text,
            "updated_at": time.time()
        })

        return {
            "en": en_text,
            "th": th_text,
            "zh": zh_text
        }

    except httpx.HTTPStatusError as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Translation service error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Translation failed: {str(e)}"}
        )
