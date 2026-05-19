import os
import json
import uuid
import asyncio
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
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
    source_lang: str = "en"  # 'en' or 'th'


# Streaming translation endpoint
class StreamTranslateRequest(BaseModel):
    text: str
    session_id: str
    target_lang: str = "th"


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
                "content": f"Translate to {lang_name}. Output only the translation."
            },
            {
                "role": "user",
                "content": text
            }
        ],
        "temperature": 0.1,
        "max_tokens": 200
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


# Streaming translation helper - returns tokens as they arrive
async def translate_streaming(text: str, target_lang: str):
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
                "content": f"Translate to {lang_name}. Output only the translation."
            },
            {
                "role": "user",
                "content": text
            }
        ],
        "temperature": 0.1,
        "max_tokens": 200,
        "stream": True
    }
    
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            OPENAI_CHAT_URL,
            headers=headers,
            json=payload,
            timeout=15.0
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue


@app.post("/api/translate-stream")
async def translate_stream(request: StreamTranslateRequest):
    """Stream translation tokens for real-time display."""
    if not OPENAI_API_KEY:
        return JSONResponse(
            status_code=500,
            content={"error": "OPENAI_API_KEY not configured"}
        )
    
    if not request.text.strip():
        return JSONResponse(content={"translation": ""})
    
    async def generate():
        async for token in translate_streaming(request.text, request.target_lang):
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")


# Translate endpoint
@app.post("/api/translate")
async def translate(request: TranslateRequest):
    """Save source text immediately, then translate and update based on source language."""
    supabase = get_supabase()
    if not supabase:
        return JSONResponse(
            status_code=500,
            content={"error": "Supabase not configured"}
        )
    
    try:
        text = request.text.strip()
        session_id = request.session_id
        source_lang = request.source_lang  # 'en' or 'th'
        
        # Step 1: Save source text to Supabase immediately so audience sees it fast
        supabase.table("captions").upsert({
            "session_id": session_id,
            source_lang: text,
            "updated_at": "now()"
        }).execute()
        
        # Step 2: Only translate on final results
        if not request.is_final or not OPENAI_API_KEY:
            return {"en": text if source_lang == "en" else "",
                    "th": text if source_lang == "th" else "",
                    "zh": ""}
        
        # Step 3: Translate to the two other languages in parallel
        if source_lang == "th":
            # Thai speaker → translate to English and Chinese
            en_task = translate_with_openai(text, "en")
            zh_task = translate_with_openai(text, "zh")
            en_text, zh_text = await asyncio.gather(en_task, zh_task)
            th_text = text
        else:
            # English speaker → translate to Thai and Chinese (default)
            th_task = translate_with_openai(text, "th")
            zh_task = translate_with_openai(text, "zh")
            th_text, zh_text = await asyncio.gather(th_task, zh_task)
            en_text = text
        
        # Step 4: Update Supabase with all translations
        supabase.table("captions").upsert({
            "session_id": session_id,
            "en": en_text,
            "th": th_text,
            "zh": zh_text or "",
            "updated_at": "now()"
        }).execute()
        
        return {
            "en": en_text,
            "th": th_text,
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
