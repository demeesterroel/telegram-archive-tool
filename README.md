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

- Python 3.8+
- python3-venv (on Debian/Ubuntu: `sudo apt install python3-venv`)
- Telegram API credentials (get from https://my.telegram.org/apps)
- ffmpeg (for video audio extraction)

## Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/telegram-archive-tool.git
cd telegram-archive-tool

# Install Python venv (Debian/Ubuntu)
sudo apt install python3-venv

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install ffmpeg (if not already installed)
# Ubuntu/Debian:
sudo apt install ffmpeg

# macOS:
brew install ffmpeg
```

## Usage

```bash
python3 main.py```
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

## Whisper Model

By default, this tool uses the "base" Whisper model for transcription. You can change this in `main.py` by modifying:

```python
transcription = transcribe_audio(filepath, "base")
```

Available models (faster → slower, less accurate → more accurate):
- `tiny` - Fastest, lowest accuracy
- `base` - Good balance (default)
- `small` - Better accuracy
- `medium` - High accuracy
- `large` - Best accuracy, slowest

## Privacy & Security

- All data is stored locally on your machine
- Session files contain authentication data - never share them
- This tool does not send your data to any third-party servers
- Whisper runs locally - no API calls to external services
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