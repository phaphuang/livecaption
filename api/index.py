import os
import uuid
import asyncio
import httpx
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
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

# Environment variables
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
HF_TOKEN = os.environ.get("HF_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# API URLs
OPENAI_API_URL = "https://api.openai.com/v1/realtime/transcription_sessions"
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


# Transcription helper using OpenAI GPT Realtime Whisper
async def transcribe_with_openai(audio_bytes: bytes) -> dict:
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }
    
    # OpenAI expects multipart/form-data
    files = {
        "file": ("audio.webm", audio_bytes, "audio/webm"),
        "model": (None, "gpt-realtime-whisper")
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            OPENAI_API_URL,
            headers=headers,
            files=files,
            timeout=30.0
        )
        
        response.raise_for_status()
        return response.json()


# Transcribe endpoint
@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    """Receive audio blob and return English transcription."""
    if not OPENAI_API_KEY:
        return JSONResponse(
            status_code=500,
            content={"error": "OPENAI_API_KEY not configured"}
        )
    
    try:
        audio_bytes = await audio.read()
        result = await transcribe_with_openai(audio_bytes)
        
        # OpenAI returns { "text": "transcribed text" }
        text = result.get("text", "")
        
        return {"text": text.strip()}
    
    except httpx.HTTPStatusError as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Transcription service error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Transcription failed: {str(e)}"}
        )


# Translation request model
class TranslateRequest(BaseModel):
    text: str
    session_id: str


# Translation helper using OpenAI GPT-4
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
                "content": f"You are a translator. Translate the following English text to {lang_name}. Return only the translation, nothing else."
            },
            {
                "role": "user",
                "content": text
            }
        ],
        "temperature": 0.3
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            OPENAI_CHAT_URL,
            headers=headers,
            json=payload,
            timeout=30.0
        )
        
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()


# Translate endpoint
@app.post("/api/translate")
async def translate(request: TranslateRequest):
    """Translate English text to Thai and Chinese, store in Supabase."""
    if not OPENAI_API_KEY:
        return JSONResponse(
            status_code=500,
            content={"error": "OPENAI_API_KEY not configured"}
        )
    
    supabase = get_supabase()
    if not supabase:
        return JSONResponse(
            status_code=500,
            content={"error": "Supabase not configured"}
        )
    
    try:
        en_text = request.text.strip()
        session_id = request.session_id
        
        # Translate in parallel using OpenAI
        th_task = translate_with_openai(en_text, "th")
        zh_task = translate_with_openai(en_text, "zh")
        
        th_text, zh_text = await asyncio.gather(th_task, zh_task)
        
        # Upsert to Supabase
        supabase.table("captions").upsert({
            "session_id": session_id,
            "en": en_text,
            "th": th_text or "",
            "zh": zh_text or "",
            "updated_at": "now()"
        }).execute()
        
        return {
            "en": en_text,
            "th": th_text or "",
            "zh": zh_text or ""
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
