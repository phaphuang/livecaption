import os
import uuid
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from supabase import create_client, Client

app = FastAPI()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


@app.post("/api/session")
async def create_session():
    """Create a new session and return session_id."""
    if not supabase:
        return JSONResponse(
            status_code=500,
            content={"error": "Supabase not configured"}
        )
    
    session_id = str(uuid.uuid4())[:8]  # Short 8-char ID for easy sharing
    
    try:
        # Insert empty row into captions table
        result = supabase.table("captions").upsert({
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


# Vercel handler
from mangum import Adapter
handler = Adapter(app)
