# LiveCaption 🎤

A full-stack live multilingual captioning web app that allows a presenter to speak in English and audience members to read live captions in their chosen language (English, Thai 🇹🇭, Chinese 🇨🇳) — no app download required.

**Live Demo**: https://livecaption.vercel.app

---

## Features

- 🎤 **Presenter**: Speak in English, see live captions
- 🌐 **Audience**: Read captions in English, Thai, or Chinese
- 📱 **Mobile-first**: Works on any device with a browser
- ⚡ **Real-time**: Live sync via Supabase Realtime
- 🔗 **Easy sharing**: QR code + shareable URL

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | HTML + Vanilla JavaScript |
| Backend | FastAPI (Python) on Vercel |
| Speech-to-Text | Hugging Face Whisper |
| Translation | Hugging Face Helsinki-NLP |
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

### 3. Hugging Face Setup

1. Go to [huggingface.co](https://huggingface.co) and create an account
2. Generate an access token at [Settings → Access Tokens](https://huggingface.co/settings/tokens)
3. Accept the model licenses:
   - https://huggingface.co/openai/whisper-large-v3-turbo
   - https://huggingface.co/Helsinki-NLP/opus-mt-en-th
   - https://huggingface.co/Helsinki-NLP/opus-mt-en-zh

### 4. Vercel Deploy

1. Go to [vercel.com](https://vercel.com) and import your GitHub repo
2. Add Environment Variables in Project Settings:

```
HF_TOKEN=hf_xxxxxxxxxxxxxxxx
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
| `/api/transcribe` | POST | Convert audio to English text |
| `/api/translate` | POST | Translate text to TH/ZH |

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `HF_TOKEN` | Hugging Face API token |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon public key |

---

## Troubleshooting

### Hugging Face API returns 503
The HF models may be "warming up" on first request. The app automatically retries once after 5 seconds.

### No captions appearing
- Check that Realtime is enabled in Supabase
- Verify environment variables are set correctly
- Check browser console for errors

### Microphone not working
- Ensure HTTPS is enabled (required for getUserMedia)
- Check browser permissions
- Try a different browser

---

## License

MIT License — feel free to use for personal or commercial projects.
