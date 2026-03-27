# Telegram Chat Archive Tool

Export your Telegram chat history with automatic transcription of voice and video messages using OpenAI Whisper.

## Features

- Export all text messages from any Telegram chat
- Download all media (photos, videos, voice notes, documents)
- Automatic transcription of voice notes using local Whisper
- Automatic transcription of video audio using local Whisper
- Beautiful HTML output with media viewer
- Works with private chats, groups, and channels
- Session management (login once, reuse for future exports)

## Requirements

- **Python 3.8+** (with venv module)
- **ffmpeg** (for video audio extraction)
- **Telegram API credentials** (get from https://my.telegram.org/apps)

## Installing Prerequisites

### Python 3

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

**macOS (using Homebrew):**
```bash
brew install python3
```

**Fedora/RHEL:**
```bash
sudo dnf install python3 python3-pip
```

**Arch Linux:**
```bash
sudo pacman -S python python-pip
```

**Windows:**
Download from https://www.python.org/downloads/ (includes venv by default)

### ffmpeg

**Ubuntu/Debian:**
```bash
sudo apt install ffmpeg
```

**macOS (using Homebrew):**
```bash
brew install ffmpeg
```

**Fedora/RHEL:**
```bash
sudo dnf install ffmpeg
```

**Arch Linux:**
```bash
sudo pacman -S ffmpeg
```

**Windows:**
Download from https://ffmpeg.org/download.html and add to PATH

### Verify Installation

```bash
python3 --version   # Should show Python 3.8+
ffmpeg -version     # Should show ffmpeg version
```

## Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/telegram-archive-tool.git
cd telegram-archive-tool

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

```bash
python3 main.py
```

On first run, you'll be prompted for:
1. **API ID** - Get from https://my.telegram.org/apps
2. **API Hash** - Get from https://my.telegram.org/apps
3. **Phone number** - Your Telegram phone number with country code
4. **Session name** - A name for this session (e.g., "my_account")

After authentication, select the chat you want to export from the list, or paste a username/ID directly.

## Output

The tool creates an `exports/` directory containing:
- `chat_export.html` - Browsable archive with all messages and media
- `media/` - Downloaded photos, videos, voice notes, documents

Voice notes and videos will have transcriptions embedded in the HTML.

## Transcription Options

At startup, you'll choose a transcription method:

### Local Whisper (Free, runs on your machine)

| Model | Speed | Quality | Best For |
|-------|-------|---------|----------|
| tiny | Fastest | Lowest | Quick tests |
| base | Fast | Decent | Default |
| **small** | Medium | Good | **Recommended for Dutch** |
| medium | Slow (5x) | Very Good | Better accuracy |
| large | Slowest (10x) | Best | Maximum quality |

### Cloud API (Requires API key, faster)

| Provider | Model | Cost | Quality |
|----------|-------|------|---------|
| Google Gemini | gemini-flash | ~$0.075/min | Excellent |
| Google Gemini | gemini-pro | ~$0.075/min | Excellent |
| OpenRouter | claude-sonnet | ~$0.008/min | Excellent |
| OpenRouter | claude-opus | ~$0.008/min | Best |

**API Keys:**
- **Gemini**: Get from https://aistudio.google.com/app/apikey
- **OpenRouter**: Get from https://openrouter.ai/keys

Keys are stored in `sessions/config.json` or set as environment variables:
```bash
export GEMINI_API_KEY=your_key
export OPENROUTER_API_KEY=your_key
```

**Note:** OpenAI Whisper API is not included due to ethical concerns. See [QuitGPT](https://quitgpt.org/) for more information.

### Language Detection

For local Whisper, the tool auto-detects the language from the first audio file and uses it for all transcriptions. This improves accuracy for non-English languages like Dutch.

## Privacy & Security

- All data is stored locally on your machine
- Session files contain authentication data - never share them
- Local Whisper runs entirely on your machine
- Cloud API keys are stored locally in `sessions/config.json`
- Exported files are private - use `.gitignore` to prevent accidental commits

## Getting Telegram API Credentials

1. Go to https://my.telegram.org/apps
2. Log in with your phone number
3. Create a new application
4. You'll receive an `api_id` and `api_hash`
5. Keep these credentials safe and never share them

## Troubleshooting

### "FloodWaitError"
Telegram has rate limits. Wait a few minutes and try again.

### Large chats take forever
Use the message limit option when prompted to export only recent messages.

### Whisper is slow
Use a smaller model (`tiny` or `base`) or consider using a GPU-enabled machine.

## License

MIT License - See LICENSE file for details.

## Disclaimer

This is an unofficial tool and is not affiliated with Telegram. Use responsibly and respect others' privacy when exporting conversations.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.