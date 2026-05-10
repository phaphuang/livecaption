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
HF_TOKEN = os.environ.get("HF_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# API URLs
OPENAI_API_URL = "https://api.openai.com/v1/audio/transcriptions"
THAI_API_URL = "https://api-inference.huggingface.co/models/Helsinki-NLP/opus-mt-en-th"
CHINESE_API_URL = "https://api-inference.huggingface.co/models/Helsinki-NLP/opus-mt-en-zh"

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


# Transcription helper using OpenAI Whisper
async def transcribe_with_openai(audio_bytes: bytes) -> dict:
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}"  # Use OpenAI API key here
    }
    
    # OpenAI expects multipart/form-data
    files = {
        "file": ("audio.webm", audio_bytes, "audio/webm"),
        "model": (None, "whisper-1")
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
    if not HF_TOKEN:
        return JSONResponse(
            status_code=500,
            content={"error": "HF_TOKEN not configured"}
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


# Translation helper
async def translate_with_hf(text: str, api_url: str, retry_count: int = 0) -> str:
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"inputs": text}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            api_url,
            headers=headers,
            json=payload,
            timeout=30.0
        )
        
        if response.status_code == 503 and retry_count < 1:
            await asyncio.sleep(5)
            return await translate_with_hf(text, api_url, retry_count + 1)
        
        response.raise_for_status()
        result = response.json()
        
        if isinstance(result, list) and len(result) > 0:
            if isinstance(result[0], list):
                return result[0][0].get("translation_text", "")
            elif isinstance(result[0], dict):
                return result[0].get("translation_text", "")
        return ""


# Translate endpoint
@app.post("/api/translate")
async def translate(request: TranslateRequest):
    """Translate English text to Thai and Chinese, store in Supabase."""
    if not HF_TOKEN:
        return JSONResponse(
            status_code=500,
            content={"error": "HF_TOKEN not configured"}
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
        
        # Translate in parallel
        th_task = translate_with_hf(en_text, THAI_API_URL)
        zh_task = translate_with_hf(en_text, CHINESE_API_URL)
        
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
