# LiveCaption 🎤

A full-stack live multilingual captioning web app that allows a presenter to speak in English and audience members to read live captions in their chosen language (English, Thai 🇹🇭, Chinese 🇨🇳) — no app download required.

**Live Demo**: https://livecaption.vercel.app

---

## Features

- 🎤 **Presenter**: Speak in English, see live captions
- 🌐 **Audience**: Read captions in English, Thai, or Chinese
- 📱 **Mobile-first**: Works on any device with a browser
- ⚡ **Real-time**: ~150ms STT latency via Deepgram Nova-3 WebSocket streaming
- 🔗 **Easy sharing**: QR code + shareable URL
- 🔤 **Font size control**: Audience can adjust caption text size
- 🔄 **Graceful fallback**: Works with Web Speech API if Deepgram is unavailable

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | HTML + Vanilla JavaScript |
| Backend | FastAPI (Python) on Vercel |
| Speech-to-Text | **Deepgram Nova-3** (WebSocket streaming) with Web Speech API fallback |
| Translation | OpenAI GPT-4o-mini (with streaming support) |
| Real-time | Supabase Realtime |
| Hosting | Vercel |

---

## Quick Start

### 1. Fork & Clone

```bash
git clone https://github.com/yourusername/livecaption.git
cd livecaption
```

### 2. Supabase Setup

1. Go to [supabase.com](https://supabase.com) and create a new project
2. Open the SQL Editor and run:

```sql
-- Create captions table
CREATE TABLE captions (
  session_id TEXT PRIMARY KEY,
  en TEXT,
  th TEXT,
  zh TEXT,
  updated_at TIMESTAMP DEFAULT now()
);

-- Enable Realtime
ALTER TABLE captions REPLICA IDENTITY FULL;
```

3. Go to **Database → Replication** and enable Realtime for the `captions` table
4. Copy your **Project URL** and **anon public key** from Settings → API

### 3. Deepgram Setup (Recommended - fastest STT)

1. Go to [deepgram.com](https://deepgram.com) and create an account
2. Create an API key from the Dashboard
3. This enables **Deepgram Nova-3** streaming STT with ~150ms first-token latency
4. If no Deepgram key is provided, the app falls back to the browser's Web Speech API

### 4. OpenAI Setup

1. Go to [platform.openai.com](https://platform.openai.com) and get an API key
2. This is used for translation (GPT-4o-mini) and optional batch transcription

### 5. Vercel Deploy

1. Go to [vercel.com](https://vercel.com) and import your GitHub repo
2. Add Environment Variables in Project Settings:

```
DEEPGRAM_API_KEY=your_deepgram_api_key
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=your_anon_public_key
```

3. Deploy!

---

## How to Use

### Presenter Flow

1. Open `https://your-app.vercel.app/`
2. Click **"Start Session"** to create a new session
3. Share the QR code or URL with your audience
4. Click **"Start Captioning"** and allow microphone access
5. Speak naturally — captions will appear in real-time

### Audience Flow

1. Scan the QR code or open the shared URL
2. Select your preferred language (🇺🇸 / 🇹🇭 / 🇨🇳)
3. Read live captions as the presenter speaks

---

## Project Structure

```
livecaption/
├── api/
│   ├── transcribe.py       # Speech-to-text endpoint
│   ├── translate.py        # Translation endpoint
│   └── session.py          # Session creation endpoint
├── public/
│   ├── index.html          # Presenter page
│   └── audience.html       # Audience page
├── vercel.json             # Vercel configuration
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/session` | POST | Create new session |
| `/api/config` | GET | Get client-side configuration (STT provider, Supabase keys) |
| `/api/transcribe` | POST | Convert audio to English text (batch fallback) |
| `/api/translate` | POST | Translate text to TH/ZH and save to Supabase |

---

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DEEPGRAM_API_KEY` | Deepgram API key for Nova-3 streaming STT | Recommended |
| `OPENAI_API_KEY` | OpenAI API key for translation & fallback STT | Yes |
| `SUPABASE_URL` | Supabase project URL | Yes |
| `SUPABASE_KEY` | Supabase anon public key | Yes |

---

## Architecture

```
Browser Mic (16kHz Opus, mono)
    | WebSocket stream (20ms chunks)
    v
Deepgram Nova-3 Streaming (~150ms first token)
    | Partial + final transcripts
    v
[Parallel]
+-- Display partial transcript immediately (optimistic UI)
+-- Send to /api/translate
        | Parallel translation (Thai + Chinese)
        v
    Supabase Realtime --> Audience pages
```

## Troubleshooting

### No captions appearing
- Check that Realtime is enabled in Supabase
- Verify environment variables are set correctly
- Check browser console for errors

### Microphone not working
- Ensure HTTPS is enabled (required for getUserMedia)
- Check browser permissions
- Try a different browser

### Deepgram not connecting
- Verify `DEEPGRAM_API_KEY` is set in environment
- Check browser console for WebSocket errors
- The app will automatically fall back to Web Speech API if Deepgram is unavailable

---

## License

MIT License — feel free to use for personal or commercial projects.
