import os
import uuid
import asyncio
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from supabase import create_client, Client

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

# Public config endpoint for client-side Supabase connection
@app.get("/api/config")
async def get_config():
    """Return public Supabase configuration for client-side use."""
    return {
        "supabase_url": os.environ.get("SUPABASE_URL", ""),
        "supabase_key": os.environ.get("SUPABASE_KEY", ""),  # Use anon key here
        "deepgram_api_key": os.environ.get("DEEPGRAM_API_KEY", ""),
        "stt_provider": "deepgram" if os.environ.get("DEEPGRAM_API_KEY") else "webspeech"
    }

# Environment variables
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")

# API URLs
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

# Lazy-loaded Supabase client (initialized at runtime)
_supabase_client: Client = None

def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None and SUPABASE_URL and SUPABASE_KEY:
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


# Health check
@app.get("/api")
async def root():
    return {"status": "ok", "message": "LiveCaption API"}


# Session endpoint
@app.post("/api/session")
async def create_session():
    """Create a new session and return session_id."""
    supabase = get_supabase()
    if not supabase:
        return JSONResponse(
            status_code=500,
            content={"error": "Supabase not configured"}
        )
    
    session_id = str(uuid.uuid4())[:8]
    
    try:
        supabase.table("captions").upsert({
            "session_id": session_id,
            "en": "",
            "th": "",
            "zh": "",
            "updated_at": "now()"
        }).execute()
        
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
    supabase = get_supabase()
    if not supabase:
        return JSONResponse(
            status_code=500,
            content={"error": "Supabase not configured"}
        )
    
    try:
        en_text = request.text.strip()
        delta = (request.delta or "").strip()
        session_id = request.session_id
        
        # Step 1: Save English to Supabase IMMEDIATELY
        # English audience sees text with near-zero delay
        supabase.table("captions").upsert({
            "session_id": session_id,
            "en": en_text,
            "updated_at": "now()"
        }).execute()
        
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
            existing = supabase.table("captions").select("th,zh").eq(
                "session_id", session_id
            ).execute()
            existing_th = ""
            existing_zh = ""
            if existing.data and len(existing.data) > 0:
                existing_th = (existing.data[0].get("th") or "").strip()
                existing_zh = (existing.data[0].get("zh") or "").strip()
            
            th_text = (existing_th + " " + (th_new or "")).strip() if existing_th else (th_new or "")
            zh_text = (existing_zh + (zh_new or "")).strip() if existing_zh else (zh_new or "")
        else:
            th_text = th_new or ""
            zh_text = zh_new or ""
        
        # Step 5: Update Supabase with the (possibly appended) translations
        supabase.table("captions").upsert({
            "session_id": session_id,
            "en": en_text,
            "th": th_text,
            "zh": zh_text,
            "updated_at": "now()"
        }).execute()
        
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
