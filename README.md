# Chat Archive Tool

Export Telegram and Signal chat history to a browsable HTML archive with automatic voice transcription and image descriptions.

## Features

- WhatsApp-style HTML output with media viewer
- Automatic transcription of voice notes and video audio
- Automatic image descriptions using BLIP (local AI, no API)
- Language auto-detection for better transcription accuracy
- Caches transcriptions and descriptions — resumable runs

---

## Requirements

- **Python 3.8+**
- **ffmpeg** (for audio extraction)

### Install ffmpeg

| OS | Command |
|----|---------|
| Ubuntu/Debian | `sudo apt install ffmpeg` |
| macOS | `brew install ffmpeg` |
| Fedora | `sudo dnf install ffmpeg` |
| Arch | `sudo pacman -S ffmpeg` |
| Windows | Download from https://ffmpeg.org/download.html and add to PATH |

### Install Python dependencies

```bash
git clone https://github.com/demeesterroel/telegram-archive-tool.git
cd telegram-archive-tool
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## Usage

```bash
python social-archive.py
```

Interactive mode — prompts for platform, then chat. Or specify everything via flags:

```bash
python social-archive.py signal   [options]
python social-archive.py telegram [options]
```

---

## Signal

Signal Desktop must be installed and have your message history.

Runs `sigexport` automatically before prompting for a chat.

```bash
python social-archive.py signal
python social-archive.py signal --chat "Jane Doe"
python social-archive.py signal --chat "Jane Doe" --start-date 2024-01-01
python social-archive.py signal --chat "Jane Doe" --export-dir ~/my-signal-export
python social-archive.py signal --skip-export --chat "Jane Doe" --limit 500
```

**Options:**

| Flag | Description |
|------|-------------|
| `--chat`, `-c` | Chat name (directory name in export dir) |
| `--export-dir`, `-e` | Path to sigexport output (default: `~/signal-export`) |
| `--skip-export` | Skip running sigexport, use existing export as-is |
| `--start-date` | Start date `YYYY-MM-DD` (inclusive) |
| `--end-date` | End date `YYYY-MM-DD` (inclusive) |
| `--limit` | Max number of messages to include |
| `--transcription`, `-t` | Transcription method (see below) |

---

## Telegram

Requires API credentials — get from https://my.telegram.org/apps.

```bash
python social-archive.py telegram
python social-archive.py telegram --session my_account --chat "Jane Doe"
python social-archive.py telegram --session my_account --chat "Jane Doe" --start-date 2024-01-01
python social-archive.py telegram --session my_account --chat username123 --limit 500
```

**Options:**

| Flag | Description |
|------|-------------|
| `--session`, `-s` | Session name (login once, reuse later) |
| `--chat`, `-c` | Chat name, username, phone number, or ID |
| `--start-date` | Start date `YYYY-MM-DD` (inclusive) |
| `--end-date` | End date `YYYY-MM-DD` (inclusive, default: today) |
| `--limit` | Max number of messages to fetch |
| `--transcription`, `-t` | Transcription method (see below) |

### Getting API credentials

1. Go to https://my.telegram.org/apps
2. Log in with your phone number
3. Create a new application
4. Copy your `api_id` and `api_hash`

---

## Output

Writes to `archive/<platform>/<chat-name>/`:

| File | Contents |
|------|----------|
| `signal_archive.html` / `chat_export.html` | Browsable HTML archive |
| `transcriptions.json` | Cached voice/video transcriptions |
| `descriptions.json` | Cached image descriptions |
| `media/` | Downloaded photos, videos, voice notes, documents |

---

## Transcription Options

Choose at startup with `--transcription` / `-t`:

### Local Whisper (free, runs on your machine)

| Option | Model | Speed | Quality |
|--------|-------|-------|---------|
| `1` | tiny | Fastest | Lowest |
| `2` | base | Fast | Decent |
| `3` | small | Medium | Good — recommended for Dutch |
| `4` | medium | Slow | Very Good |
| `5` | large | Slowest | Best |

### Cloud API (requires API key)

| Option | Provider | Model | Quality |
|--------|----------|-------|---------|
| `6` | Google Gemini | gemini-flash | Excellent |
| `7` | Google Gemini | gemini-pro | Excellent |

**API keys** — stored in `sessions/config.json` or as environment variables:
```bash
export GEMINI_API_KEY=your_key
```

---

## Image Descriptions

Photos described automatically using BLIP (local model, no API):
- First run downloads ~1GB model
- Results cached in `descriptions.json`
- Skip with Ctrl+C during "PHASE 2b"

---

## Privacy & Security

- All data stored locally
- Session files contain auth tokens — never share or commit them
- Local Whisper and BLIP run entirely on your machine
- `archive/` and `sessions/` are in `.gitignore`

---

## License

MIT — see LICENSE file.
