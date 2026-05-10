import os
import asyncio
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI()

HF_TOKEN = os.environ.get("HF_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

THAI_API_URL = "https://api-inference.huggingface.co/models/Helsinki-NLP/opus-mt-en-th"
CHINESE_API_URL = "https://api-inference.huggingface.co/models/Helsinki-NLP/opus-mt-en-zh"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


class TranslateRequest(BaseModel):
    text: str
    session_id: str


async def translate_with_hf(text: str, api_url: str, retry_count: int = 0) -> str:
    """Call Hugging Face translation API with retry logic."""
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
        
        # Handle HF model cold start (503)
        if response.status_code == 503 and retry_count < 1:
            await asyncio.sleep(5)
            return await translate_with_hf(text, api_url, retry_count + 1)
        
        response.raise_for_status()
        result = response.json()
        
        # HF returns list of lists with translation_text
        if isinstance(result, list) and len(result) > 0:
            if isinstance(result[0], list):
                return result[0][0].get("translation_text", "")
            elif isinstance(result[0], dict):
                return result[0].get("translation_text", "")
        return ""


@app.post("/api/translate")
async def translate(request: TranslateRequest):
    """Translate English text to Thai and Chinese, store in Supabase."""
    if not HF_TOKEN:
        return JSONResponse(
            status_code=500,
            content={"error": "HF_TOKEN not configured"}
        )
    
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
        result = supabase.table("captions").upsert({
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


# Vercel handler
from mangum import Adapter
handler = Adapter(app)
