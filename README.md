# Chat Archive Tool

Export Telegram, Signal, and WhatsApp chat history to a browsable HTML archive with automatic voice transcription and image descriptions.

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
./run.sh                                                    # fully interactive (auto-uses venv)
./run.sh --platform signal   [options]
./run.sh --platform telegram [options]
./run.sh --platform whatsapp [options]
```

**Common options (both platforms):**

| Flag | Description |
|------|-------------|
| `--platform`, `-p` | `signal`, `telegram`, or `whatsapp` |
| `--chat`, `-c` | Chat name to archive |
| `--start-date` | Start date `YYYY-MM-DD` (inclusive) |
| `--end-date` | End date `YYYY-MM-DD` (inclusive) |
| `--limit` | Max number of messages |
| `--transcription`, `-t` | Transcription method (see below) |

---

## Signal

Signal Desktop must be installed and have your message history.
Runs `sigexport` automatically before prompting for a chat.

```bash
python social-archive.py --platform signal --chat "Jane Doe"
python social-archive.py --platform signal --chat "Jane Doe" --start-date 2024-01-01
python social-archive.py --platform signal --skip-export --chat "Jane Doe" --limit 500
```

**Signal-specific options:**

| Flag | Description |
|------|-------------|
| `--export-dir`, `-e` | Path to sigexport output (default: `./archive/signal/source`) |
| `--signal-source` | Path to Signal config dir (see below) |
| `--skip-export` | Skip running sigexport, use existing export as-is |

**Signal config location** — pass via `--signal-source` if sigexport can't find it automatically:

| Install type | Path |
|---|---|
| Standard | `~/.config/Signal` |
| Flatpak | `~/.var/app/org.signal.Signal/config/Signal` |
| Snap | `~/snap/signal-desktop/current/.config/Signal` |

Flatpak example:
```bash
python social-archive.py --platform signal --chat "Jane Doe" \
  --signal-source ~/.var/app/org.signal.Signal/config/Signal
```

---

## Telegram

Requires API credentials — get from https://my.telegram.org/apps.

```bash
python social-archive.py --platform telegram --session my_account --chat "Jane Doe"
python social-archive.py --platform telegram --session my_account --chat "Jane Doe" --start-date 2024-01-01
python social-archive.py --platform telegram --session my_account --chat username123 --limit 500
```

**Telegram-specific options:**

| Flag | Description |
|------|-------------|
| `--session`, `-s` | Session name (login once, reuse later) |
| `--chat`, `-c` | Accepts name, username, phone number, or ID |

### Getting API credentials

1. Go to https://my.telegram.org/apps
2. Log in with your phone number
3. Create a new application
4. Copy your `api_id` and `api_hash`

---

## WhatsApp

No third-party tool required — export directly from the WhatsApp app.

### How to export a chat

**Android:**
1. Open the chat → tap ⋮ (three dots) → **More** → **Export chat**
2. Choose **Include media** (recommended) or **Without media**
3. Share/save the `.zip` file to your computer
4. Unzip it — you'll get a folder containing `_chat.txt` and media files

**iOS:**
1. Open the chat → tap the contact/group name at the top → **Export Chat**
2. Choose **Attach Media** (recommended) or **Without Media**
3. Share/save the `.zip` file to your computer
4. Unzip it — you'll get a folder containing `_chat.txt` and media files

### Usage

```bash
# Interactive — prompts for export folder and your name
python social-archive.py --platform whatsapp

# Point directly at a single unzipped export folder
python social-archive.py --platform whatsapp --export-dir ~/Downloads/WhatsApp\ Chat\ -\ Jane\ Doe

# Non-interactive with owner name (enables outgoing bubble styling)
python social-archive.py --platform whatsapp \
  --export-dir ~/Downloads/whatsapp-exports \
  --chat "WhatsApp Chat - Jane Doe" \
  --wa-owner "John Smith"

# Date range filter
python social-archive.py --platform whatsapp \
  --export-dir ~/Downloads/whatsapp-exports \
  --start-date 2024-01-01 --end-date 2024-12-31
```

**WhatsApp-specific options:**

| Flag | Description |
|------|-------------|
| `--export-dir`, `-e` | Path to the unzipped WhatsApp export folder |
| `--wa-owner` | Your name exactly as it appears in the export (enables outgoing styling) |

> **Note on `--wa-owner`**: WhatsApp exports use your contact name, not "Me". Run once without it to see all sender names, then re-run with the correct `--wa-owner` value to get proper outgoing/incoming bubble layout.

---

## Output

Writes to `archive/<platform>/output/<chat-name>/`:

| File | Contents |
|------|----------|
| `signal_archive.html` / `chat_export.html` / `whatsapp_archive.html` | Browsable HTML archive |
| `transcriptions.json` | Cached voice/video transcriptions |
| `descriptions.json` | Cached image descriptions |
| `media/` | Symlink to export's media folder (Signal/WhatsApp) or downloaded files (Telegram) |

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
