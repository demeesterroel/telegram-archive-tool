"""
Shared utilities for telegram-archive and signal-archive.
Handles config, transcription (local Whisper + cloud APIs), image description, and HTML generation.
"""

import os
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import whisper

MEDIA_DIR = "media"
OUTPUT_FILE = "chat_export.html"
SESSIONS_DIR = "sessions"
CONFIG_FILE = "config.json"

TRANSCRIPTION_METHODS = {
    "1": {"name": "tiny",          "type": "local", "speed": "Fastest",          "quality": "Lowest"},
    "2": {"name": "base",          "type": "local", "speed": "Fast",             "quality": "Decent"},
    "3": {"name": "small",         "type": "local", "speed": "Medium",           "quality": "Good"},
    "4": {"name": "medium",        "type": "local", "speed": "Slow (5x base)",   "quality": "Very Good"},
    "5": {"name": "large",         "type": "local", "speed": "Slowest (10x base)","quality": "Best"},
    "6": {"name": "gemini-flash",  "type": "api",   "speed": "Fast",             "quality": "Excellent", "provider": "gemini"},
    "7": {"name": "gemini-pro",    "type": "api",   "speed": "Medium",           "quality": "Excellent", "provider": "gemini"},
    "8": {"name": "claude-sonnet", "type": "api",   "speed": "Medium",           "quality": "Excellent", "provider": "openrouter"},
    "9": {"name": "claude-opus",   "type": "api",   "speed": "Slower",           "quality": "Best",      "provider": "openrouter"},
}

DEFAULT_METHOD = "3"

model_cache: Dict[str, Any] = {}
blip_processor = None
blip_model = None


def load_blip_model():
    global blip_processor, blip_model
    if blip_processor is None:
        print("  Downloading BLIP model for image descriptions...")
        print("  (This may take a few minutes on first run)")
        from transformers import BlipProcessor, BlipForConditionalGeneration
        import warnings
        warnings.filterwarnings("ignore")
        blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
        blip_model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
        print("  BLIP model loaded successfully!")
    return blip_processor, blip_model


def describe_image(image_path: str, language: Optional[str] = None) -> Optional[str]:
    try:
        from PIL import Image
        processor, model = load_blip_model()
        print(f"  Describing: {os.path.basename(image_path)}")
        image = Image.open(image_path).convert("RGB")
        inputs = processor(image, return_tensors="pt")
        output = model.generate(**inputs, max_length=100)
        return processor.decode(output[0], skip_special_tokens=True)
    except Exception as e:
        print(f"  Error describing image: {e}")
        return None


def load_config() -> Dict[str, Any]:
    config_path = Path(SESSIONS_DIR) / CONFIG_FILE
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"transcription_method": DEFAULT_METHOD}


def save_config(config: Dict[str, Any]) -> None:
    config_path = Path(SESSIONS_DIR) / CONFIG_FILE
    config_path.parent.mkdir(exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def add_transcription_arg(parser: Any) -> None:
    """Add --transcription / -t argument to an argparse ArgumentParser."""
    parser.add_argument(
        "--transcription", "-t",
        choices=["1", "2", "3", "4", "5", "6", "7", "8", "9"],
        help=(
            "Transcription method: 1=tiny, 2=base, 3=small, 4=medium, 5=large "
            "(local Whisper); 6=gemini-flash, 7=gemini-pro, 8=claude-sonnet, 9=claude-opus (API)"
        ),
    )


def resolve_transcription(config: Dict[str, Any], transcription_arg: Optional[str]) -> None:
    """Apply --transcription arg directly, or prompt interactively if not given."""
    if transcription_arg:
        config["transcription_method"] = transcription_arg
    else:
        select_transcription_method(config)


def select_transcription_method(config: Dict[str, Any]) -> str:
    current = config.get("transcription_method", DEFAULT_METHOD)

    print("\n" + "=" * 60)
    print("TRANSCRIPTION METHOD")
    print("=" * 60)
    print("\nLocal Whisper (free, runs on your machine):")
    for key in ["1", "2", "3", "4", "5"]:
        m = TRANSCRIPTION_METHODS[key]
        print(f"  {key}. {m['name']:8} - {m['quality']:10} quality, {m['speed']}")

    print("\nCloud API (requires API key):")
    for key in ["6", "7", "8", "9"]:
        m = TRANSCRIPTION_METHODS[key]
        cost = "~$0.008/min" if m["provider"] == "openrouter" else "~$0.075/min"
        print(f"  {key}. {m['name']:12} - {m['quality']:10} quality, {m['speed']}, {cost}")

    print(f"\nCurrent: {TRANSCRIPTION_METHODS[current]['name']}")
    choice = input(f"Select [1-9] (default: {current}): ").strip()

    if choice in TRANSCRIPTION_METHODS:
        config["transcription_method"] = choice
        save_config(config)
        return choice
    return current


def get_api_key(provider: str, config: Dict[str, Any]) -> str:
    key_names = {
        "gemini": "GEMINI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    key_name = key_names.get(provider, f"{provider.upper()}_API_KEY")
    config_key = f"{provider}_api_key"

    if config.get(config_key):
        return config[config_key]

    env_key = os.environ.get(key_name)
    if env_key:
        return env_key

    print(f"\n{key_name} required for {provider}.")
    print("Get it from:")
    if provider == "gemini":
        print("  https://aistudio.google.com/app/apikey")
    elif provider == "openrouter":
        print("  https://openrouter.ai/keys")

    api_key = input(f"\nEnter {key_name}: ").strip()
    if api_key:
        config[config_key] = api_key
        save_config(config)
    return api_key


def transcribe_with_gemini(file_path: str, language: Optional[str], api_key: str) -> Optional[str]:
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        with open(file_path, "rb") as f:
            audio_data = f.read()
        prompt = "Transcribe this audio. Output only the transcribed text."
        if language:
            prompt = f"Transcribe this {language} audio. Output only the transcribed text."
        response = model.generate_content([
            {"mime_type": "audio/ogg", "data": audio_data},
            prompt,
        ])
        return response.text.strip()
    except Exception as e:
        print(f"  Gemini error: {e}")
        return None


def transcribe_with_openrouter(file_path: str, language: Optional[str], model: str, api_key: str) -> Optional[str]:
    try:
        import base64
        import requests
        with open(file_path, "rb") as f:
            audio_base64 = base64.b64encode(f.read()).decode()
        prompt = "Transcribe this audio. Output only the transcribed text."
        if language:
            prompt = f"Transcribe this {language} audio. Output only the transcribed text."
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:audio/ogg;base64,{audio_base64}"}},
                    ],
                }],
            },
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()
        print(f"  OpenRouter error: {response.status_code} - {response.text}")
        return None
    except Exception as e:
        print(f"  OpenRouter error: {e}")
        return None


def load_whisper_model(model_size: str = "base"):
    if model_size not in model_cache:
        print(f"Loading Whisper model ({model_size})...")
        model_cache[model_size] = whisper.load_model(model_size)
    return model_cache[model_size]


def detect_language(file_path: str, model_size: str = "base") -> Optional[str]:
    try:
        model = load_whisper_model(model_size)
        print(f"  Detecting language from: {os.path.basename(file_path)}")
        audio = whisper.load_audio(file_path)
        audio = whisper.pad_or_trim(audio)
        mel = whisper.log_mel_spectrogram(audio, n_mels=80).to(model.device)
        _, probs = model.detect_language(mel)
        detected = max(probs, key=probs.get)
        print(f"  Detected language: {detected} ({probs[detected]*100:.1f}% confidence)")
        return detected
    except Exception as e:
        print(f"  Error detecting language: {e}")
        return None


def transcribe_audio(file_path: str, model_size: str = "base", language: Optional[str] = None) -> Optional[str]:
    try:
        import torch
        model = load_whisper_model(model_size)
        print(f"  Transcribing: {os.path.basename(file_path)}")
        result = model.transcribe(file_path, language=language, fp16=torch.cuda.is_available())
        return result["text"].strip()
    except Exception as e:
        print(f"  Error transcribing {file_path}: {e}")
        return None


def get_audio_duration(file_path: str) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", file_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0


def _fmt_secs(secs: float) -> str:
    s = int(secs)
    if s < 60:
        return f"{s}s"
    elif s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {(s % 3600) // 60}m"


def extract_audio_from_video(video_path: str, audio_path: str) -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path],
            capture_output=True, text=True,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"  Error extracting audio: {e}")
        return False


def transcribe_media(messages: List[Dict[str, Any]], output_dir: str, config: Dict[str, Any]) -> None:
    print(f"\n{'='*60}")
    print("PHASE 2: Transcribing voice and video messages")
    print(f"{'='*60}")

    method_key = config.get("transcription_method", DEFAULT_METHOD)
    method_info = TRANSCRIPTION_METHODS[method_key]
    print(f"  Method: {method_info['name']} ({method_info['quality']} quality)")

    transcriptions_file = os.path.join(output_dir, "transcriptions.json")

    existing_transcriptions: Dict[str, str] = {}
    if os.path.exists(transcriptions_file):
        try:
            with open(transcriptions_file, "r", encoding="utf-8") as f:
                existing_transcriptions = json.load(f)
            print(f"  Loaded {len(existing_transcriptions)} existing transcriptions")
        except Exception:
            pass

    media_to_transcribe = []
    for msg in messages:
        if msg.get("media"):
            m = msg["media"]
            if m["type"] in ("voice", "video"):
                if m["filename"] in existing_transcriptions:
                    m["transcription"] = existing_transcriptions[m["filename"]]
                else:
                    media_to_transcribe.append(m)

    if not media_to_transcribe and not existing_transcriptions:
        print("  No voice or video messages to transcribe.")
        return

    if media_to_transcribe:
        media_to_transcribe.reverse()
        print(f"  Found {len(media_to_transcribe)} voice/video messages to transcribe")

        detected_language = None
        if method_info["type"] == "local":
            first_media = media_to_transcribe[0]
            first_file = first_media["path"]
            if first_media["type"] == "video":
                first_file = first_file.rsplit(".", 1)[0] + "_audio.wav"
                extract_audio_from_video(first_media["path"], first_file)
            detected_language = detect_language(first_file, method_info["name"])
            if first_media["type"] == "video":
                try:
                    os.remove(first_file)
                except Exception:
                    pass

        print()

        api_key = None
        if method_info["type"] == "api":
            api_key = get_api_key(method_info["provider"], config)

        # Probe durations for ETA estimation
        print("  Probing audio durations...", end="", flush=True)
        durations: Dict[str, float] = {m["filename"]: get_audio_duration(m["path"]) for m in media_to_transcribe}
        total_audio_secs = sum(durations.values())
        print(f" total {_fmt_secs(total_audio_secs)} of audio\n")

        done_audio_secs = 0.0
        loop_start = time.time()

        for i, m in enumerate(media_to_transcribe, 1):
            print(f"[{i}/{len(media_to_transcribe)}] {m['filename']}")

            file_path = m["path"]
            if m["type"] == "video":
                audio_path = m["path"].rsplit(".", 1)[0] + "_audio.wav"
                if extract_audio_from_video(m["path"], audio_path):
                    file_path = audio_path
                else:
                    m["transcription"] = None
                    print("  → [Audio extraction failed]")
                    continue

            if method_info["type"] == "local":
                m["transcription"] = transcribe_audio(file_path, method_info["name"], language=detected_language)
            elif method_info["provider"] == "gemini":
                m["transcription"] = transcribe_with_gemini(file_path, detected_language, api_key)
            elif method_info["provider"] == "openrouter":
                model_map = {
                    "claude-sonnet": "anthropic/claude-3.5-sonnet",
                    "claude-opus": "anthropic/claude-3-opus",
                }
                model = model_map.get(method_info["name"], "anthropic/claude-3.5-sonnet")
                m["transcription"] = transcribe_with_openrouter(file_path, detected_language, model, api_key)

            if m["type"] == "video":
                try:
                    os.remove(file_path)
                except Exception:
                    pass

            if m["transcription"]:
                existing_transcriptions[m["filename"]] = m["transcription"]
                preview = m["transcription"][:100] + ("..." if len(m["transcription"]) > 100 else "")
                print(f"  → {preview}")
                with open(transcriptions_file, "w", encoding="utf-8") as f:
                    json.dump(existing_transcriptions, f, ensure_ascii=False, indent=2)
            else:
                print("  → [Transcription failed]")

            # Progress bar + ETA
            done_audio_secs += durations.get(m["filename"], 0)
            elapsed = time.time() - loop_start
            bar_len = 24
            filled = int(bar_len * i / len(media_to_transcribe))
            bar = "█" * filled + "░" * (bar_len - filled)
            if elapsed > 0 and done_audio_secs > 0:
                speed = done_audio_secs / elapsed  # audio-secs per wall-sec
                remaining = total_audio_secs - done_audio_secs
                eta = f"~{_fmt_secs(remaining / speed)}" if speed > 0 else "?"
                speed_str = f"{speed:.1f}x realtime"
            else:
                eta = "?"
                speed_str = ""
            print(f"  [{bar}] {i}/{len(media_to_transcribe)}  {_fmt_secs(done_audio_secs)}/{_fmt_secs(total_audio_secs)} audio  ETA {eta}  {speed_str}\n")

        print("  Transcription complete!")
    else:
        print("  All transcriptions already exist. Skipping...")

    for msg in messages:
        if msg.get("media") and msg["media"]["type"] in ("voice", "video"):
            if msg["media"]["filename"] in existing_transcriptions:
                msg["media"]["transcription"] = existing_transcriptions[msg["media"]["filename"]]


def describe_images(messages: List[Dict[str, Any]], output_dir: str, language: Optional[str] = None) -> None:
    print(f"\n{'='*60}")
    print("PHASE 2b: Describing images")
    print(f"{'='*60}")

    descriptions_file = os.path.join(output_dir, "descriptions.json")

    existing_descriptions: Dict[str, str] = {}
    if os.path.exists(descriptions_file):
        try:
            with open(descriptions_file, "r", encoding="utf-8") as f:
                existing_descriptions = json.load(f)
            print(f"  Loaded {len(existing_descriptions)} existing descriptions")
        except Exception:
            pass

    images_to_describe = []
    for msg in messages:
        if msg.get("media") and msg["media"]["type"] == "photo":
            if msg["media"]["filename"] in existing_descriptions:
                msg["media"]["description"] = existing_descriptions[msg["media"]["filename"]]
            else:
                images_to_describe.append(msg["media"])

    if not images_to_describe and not existing_descriptions:
        print("  No images to describe.")
        return

    if images_to_describe:
        print(f"  Found {len(images_to_describe)} images to describe\n")
        for i, img in enumerate(images_to_describe, 1):
            print(f"[{i}/{len(images_to_describe)}] {img['filename']}")
            description = describe_image(img["path"], language)
            if description:
                img["description"] = description
                existing_descriptions[img["filename"]] = description
                print(f"  → {description[:80]}{'...' if len(description) > 80 else ''}")
                with open(descriptions_file, "w", encoding="utf-8") as f:
                    json.dump(existing_descriptions, f, ensure_ascii=False, indent=2)
            else:
                print("  → [Description failed]")
            print()
        print("  Image description complete!")
    else:
        print("  All image descriptions already exist. Skipping...")

    for msg in messages:
        if msg.get("media") and msg["media"]["type"] == "photo":
            if msg["media"]["filename"] in existing_descriptions:
                msg["media"]["description"] = existing_descriptions[msg["media"]["filename"]]


def generate_html(
    messages: List[Dict],
    participants: Dict[int, str],
    output_path: str,
    chat_name: str,
    app_name: str = "Chat",
) -> None:
    print(f"\n{'='*60}")
    print("PHASE 3: Generating HTML output")
    print(f"{'='*60}")

    html_template = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{app_name} Archive - {chat_name}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #ece5dd;
            color: #303030;
            line-height: 1.5;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: #fff;
            min-height: 100vh;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
        }}
        .header {{
            padding: 20px;
            background: #075e54;
            color: #fff;
        }}
        .header h1 {{
            font-size: 22px;
            font-weight: 500;
        }}
        .header .info {{
            color: rgba(255,255,255,0.7);
            font-size: 13px;
            margin-top: 5px;
        }}
        .messages {{
            padding: 20px;
            background: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23d4cfc4' fill-opacity='0.1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
        }}
        .message {{
            display: flex;
            margin-bottom: 12px;
        }}
        .message.outgoing {{
            justify-content: flex-end;
        }}
        .avatar {{
            width: 36px;
            height: 36px;
            border-radius: 50%;
            background: #6b9bc3;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 14px;
            color: #fff;
            flex-shrink: 0;
            margin-right: 10px;
        }}
        .message.outgoing .avatar {{
            background: #25d366;
            margin-right: 0;
            margin-left: 10px;
            order: 2;
        }}
        .message-content {{
            max-width: 65%;
        }}
        .sender {{
            font-size: 12px;
            color: #128c7e;
            margin-bottom: 3px;
            font-weight: 500;
        }}
        .message.outgoing .sender {{
            text-align: right;
            color: #075e54;
        }}
        .bubble {{
            background: #fff;
            padding: 8px 12px;
            border-radius: 8px;
            box-shadow: 0 1px 1px rgba(0,0,0,0.1);
            display: inline-block;
            position: relative;
        }}
        .message.outgoing .bubble {{
            background: #dcf8c6;
        }}
        .bubble::before {{
            content: '';
            position: absolute;
            top: 0;
            left: -8px;
            width: 0;
            height: 0;
            border: 8px solid transparent;
            border-right-color: #fff;
            border-top: 0;
        }}
        .message.outgoing .bubble::before {{
            left: auto;
            right: -8px;
            border-right-color: transparent;
            border-left-color: #dcf8c6;
        }}
        .timestamp {{
            font-size: 11px;
            color: #667781;
            margin-top: 4px;
        }}
        .message.outgoing .timestamp {{
            text-align: right;
        }}
        .text {{
            white-space: pre-wrap;
            word-break: break-word;
            color: #303030;
        }}
        .media {{
            margin-top: 8px;
            max-width: 100%;
        }}
        .media img {{
            max-width: 100%;
            border-radius: 8px;
            cursor: pointer;
        }}
        .media video {{
            max-width: 100%;
            border-radius: 8px;
        }}
        .media audio {{
            max-width: 100%;
        }}
        .media a {{
            color: #128c7e;
            text-decoration: none;
        }}
        .media a:hover {{
            text-decoration: underline;
        }}
        .description {{
            margin-top: 8px;
            padding: 6px 10px;
            background: rgba(0,0,0,0.03);
            border-radius: 6px;
            font-size: 12px;
            color: #54656f;
        }}
        .description-label {{
            font-weight: 500;
            color: #128c7e;
            margin-right: 5px;
        }}
        .transcription {{
            margin-top: 8px;
            padding: 6px 10px;
            background: rgba(0,0,0,0.03);
            border-radius: 6px;
            font-size: 13px;
            color: #54656f;
            font-style: italic;
        }}
        .transcription-label {{
            font-weight: 500;
            color: #075e54;
            font-size: 11px;
            text-transform: uppercase;
            margin-bottom: 3px;
        }}
        .lightbox {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.95);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }}
        .lightbox img {{
            max-width: 95%;
            max-height: 95%;
        }}
        .lightbox.active {{
            display: flex;
        }}
        .lightbox-close {{
            position: fixed;
            top: 20px;
            right: 30px;
            font-size: 40px;
            color: #fff;
            cursor: pointer;
            z-index: 1001;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{chat_name}</h1>
            <div class="info">Exported on {export_date}</div>
        </div>
        <div class="messages">
            {messages_html}
        </div>
    </div>
    <div class="lightbox" id="lightbox" onclick="closeLightbox()">
        <span class="lightbox-close" onclick="closeLightbox()">&times;</span>
        <img id="lightbox-img" src="">
    </div>
    <script>
        function openLightbox(src) {{
            document.getElementById('lightbox-img').src = src;
            document.getElementById('lightbox').classList.add('active');
        }}
        function closeLightbox() {{
            document.getElementById('lightbox').classList.remove('active');
        }}
        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') closeLightbox();
        }});
    </script>
</body>
</html>'''

    messages_html = []

    for msg in reversed(messages):
        sender_name = participants.get(msg["sender_id"], f"User {msg['sender_id']}")
        is_outgoing = 0 < msg["sender_id"] < 1_000_000_000

        avatar_char = sender_name[0].upper() if sender_name else "?"

        media_html = ""
        if msg.get("media"):
            m = msg["media"]
            if m["type"] == "photo":
                rel_path = os.path.join(MEDIA_DIR, m["filename"])
                media_html = f'''<div class="media">
                    <img src="{rel_path}" onclick="openLightbox('{rel_path}')" alt="Photo">
                </div>'''
                if m.get("description"):
                    media_html += f'''<div class="description">
                        <span class="description-label">📷</span> {m['description']}
                    </div>'''
            elif m["type"] == "video":
                rel_path = os.path.join(MEDIA_DIR, m["filename"])
                media_html = f'''<div class="media">
                    <video controls><source src="{rel_path}" type="video/mp4"></video>
                </div>'''
            elif m["type"] == "voice":
                rel_path = os.path.join(MEDIA_DIR, m["filename"])
                media_html = f'''<div class="media">
                    <audio controls><source src="{rel_path}" type="audio/ogg"></audio>
                </div>'''
            elif m["type"] == "document":
                rel_path = os.path.join(MEDIA_DIR, m["filename"])
                media_html = f'''<div class="media">
                    <a href="{rel_path}" target="_blank">📄 {m['filename']}</a>
                </div>'''

            if m.get("transcription"):
                media_html += f'''<div class="transcription">
                    <div class="transcription-label">📝 Transcription</div>
                    {m['transcription']}
                </div>'''

        timestamp = msg["date"].split("T")[0] if msg.get("date") else ""

        msg_html = f'''<div class="message {'outgoing' if is_outgoing else ''}">
            <div class="avatar">{avatar_char}</div>
            <div class="message-content">
                <div class="sender">{sender_name}</div>
                <div class="bubble">
                    <div class="text">{msg['text']}</div>
                    {media_html}
                </div>
                <div class="timestamp">{timestamp}</div>
            </div>
        </div>'''

        messages_html.append(msg_html)

    html = html_template.format(
        app_name=app_name,
        chat_name=chat_name,
        export_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        messages_html="\n".join(messages_html),
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Output: {output_path}")
