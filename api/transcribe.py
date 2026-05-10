import os
import asyncio
import httpx
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse

app = FastAPI()

HF_TOKEN = os.environ.get("HF_TOKEN")
WHISPER_API_URL = "https://api-inference.huggingface.co/models/openai/whisper-large-v3-turbo"


async def transcribe_with_hf(audio_bytes: bytes, retry_count: int = 0) -> dict:
    """Call Hugging Face Whisper API with retry logic."""
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "audio/webm"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            WHISPER_API_URL,
            headers=headers,
            content=audio_bytes,
            timeout=30.0
        )
        
        # Handle HF model cold start (503)
        if response.status_code == 503 and retry_count < 1:
            await asyncio.sleep(5)
            return await transcribe_with_hf(audio_bytes, retry_count + 1)
        
        response.raise_for_status()
        return response.json()


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
        
        result = await transcribe_with_hf(audio_bytes)
        
        # Extract text from HF response
        text = result.get("text", "")
        if not text and "chunks" in result:
            text = " ".join([chunk.get("text", "") for chunk in result["chunks"]])
        
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


# Vercel handler
from mangum import Adapter
handler = Adapter(app)
