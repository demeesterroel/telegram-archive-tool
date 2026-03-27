#!/usr/bin/env python3
"""
Telegram Chat Archive Tool
Exports Telegram chat history with transcribed voice/video messages
"""

import os
import sys
import json
import asyncio
import mimetypes
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from telethon import TelegramClient, sync
from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument
import whisper

MEDIA_DIR = "media"
OUTPUT_FILE = "chat_export.html"
SESSIONS_DIR = "sessions"
CONFIG_FILE = "config.json"

TRANSCRIPTION_METHODS = {
    "1": {"name": "tiny", "type": "local", "speed": "Fastest", "quality": "Lowest"},
    "2": {"name": "base", "type": "local", "speed": "Fast", "quality": "Decent"},
    "3": {"name": "small", "type": "local", "speed": "Medium", "quality": "Good"},
    "4": {"name": "medium", "type": "local", "speed": "Slow (5x base)", "quality": "Very Good"},
    "5": {"name": "large", "type": "local", "speed": "Slowest (10x base)", "quality": "Best"},
    "6": {"name": "gemini-flash", "type": "api", "speed": "Fast", "quality": "Excellent", "provider": "gemini"},
    "7": {"name": "gemini-pro", "type": "api", "speed": "Medium", "quality": "Excellent", "provider": "gemini"},
    "8": {"name": "claude-sonnet", "type": "api", "speed": "Medium", "quality": "Excellent", "provider": "openrouter"},
    "9": {"name": "claude-opus", "type": "api", "speed": "Slower", "quality": "Best", "provider": "openrouter"},
}

DEFAULT_METHOD = "3"

model_cache = {}
blip_processor = None
blip_model = None

def load_blip_model():
    global blip_processor, blip_model
    if blip_processor is None:
        print("  Downloading BLIP model for image descriptions...")
        print("  (This may take a few minutes on first run)")
        from transformers import BlipProcessor, BlipForConditionalGeneration
        from tqdm import tqdm
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
        image = Image.open(image_path).convert('RGB')
        inputs = processor(image, return_tensors="pt")
        
        output = model.generate(**inputs, max_length=100)
        description = processor.decode(output[0], skip_special_tokens=True)
        
        return description
    except Exception as e:
        print(f"  Error describing image: {e}")
        return None

def load_config() -> Dict[str, Any]:
    config_path = Path(SESSIONS_DIR) / CONFIG_FILE
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"transcription_method": DEFAULT_METHOD}

def save_config(config: Dict[str, Any]):
    config_path = Path(SESSIONS_DIR) / CONFIG_FILE
    config_path.parent.mkdir(exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

def select_transcription_method(config: Dict[str, Any]) -> str:
    current = config.get("transcription_method", DEFAULT_METHOD)
    
    print("\n" + "="*60)
    print("TRANSCRIPTION METHOD")
    print("="*60)
    print("\nLocal Whisper (free, runs on your machine):")
    for key in ["1", "2", "3", "4", "5"]:
        m = TRANSCRIPTION_METHODS[key]
        print(f"  {key}. {m['name']:8} - {m['quality']:10} quality, {m['speed']}")
    
    print("\nCloud API (requires API key):")
    for key in ["6", "7", "8", "9"]:
        m = TRANSCRIPTION_METHODS[key]
        cost = "~$0.008/min" if m['provider'] == 'openrouter' else "~$0.075/min"
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
    print(f"Get it from:")
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
        
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        with open(file_path, 'rb') as f:
            audio_data = f.read()
        
        prompt = "Transcribe this audio. Output only the transcribed text."
        if language:
            prompt = f"Transcribe this {language} audio. Output only the transcribed text."
        
        response = model.generate_content([
            {"mime_type": "audio/ogg", "data": audio_data},
            prompt
        ])
        
        return response.text.strip()
    except Exception as e:
        print(f"  Gemini error: {e}")
        return None

def transcribe_with_openrouter(file_path: str, language: Optional[str], model: str, api_key: str) -> Optional[str]:
    try:
        import base64
        import requests
        
        with open(file_path, 'rb') as f:
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
                        {"type": "image_url", "image_url": {"url": f"data:audio/ogg;base64,{audio_base64}"}}
                    ]
                }]
            }
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
        model = load_whisper_model(model_size)
        print(f"  Transcribing: {os.path.basename(file_path)}")
        result = model.transcribe(file_path, language=language)
        return result["text"].strip()
    except Exception as e:
        print(f"  Error transcribing {file_path}: {e}")
        return None

def extract_audio_from_video(video_path: str, audio_path: str) -> bool:
    try:
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception as e:
        print(f"  Error extracting audio: {e}")
        return False

async def download_media(client: TelegramClient, message: Message, media_dir: str) -> Optional[Dict[str, Any]]:
    try:
        os.makedirs(media_dir, exist_ok=True)
        media = message.media
        sender_id = message.sender_id or 0
        
        if isinstance(media, MessageMediaPhoto):
            photo = media.photo
            if not photo:
                return None
            
            date_str = datetime.fromtimestamp(photo.date.timestamp()).strftime("%Y%m%d")
            filename = f"{date_str}_{photo.id}_{sender_id}_photo.jpg"
            filepath = os.path.join(media_dir, filename)
            
            if os.path.exists(filepath):
                print(f"  Skipped (exists): {filename}")
            else:
                await client.download_media(message, filepath)
                print(f"  Downloaded: {filename}")
            
            return {
                "type": "photo",
                "path": filepath,
                "filename": filename
            }
            
        elif isinstance(media, MessageMediaDocument):
            doc = media.document
            if not doc:
                return None
            
            mime_type = getattr(doc, 'mime_type', '')
            is_voice = 'audio/ogg' in mime_type or 'audio/oga' in mime_type
            is_video = 'video' in mime_type
            
            ext = mimetypes.guess_extension(mime_type) or ''
            if is_voice and ext == '.oga':
                ext = '.oga'
            
            media_type = 'voice' if is_voice else ('video' if is_video else 'file')
            date_str = datetime.fromtimestamp(doc.date.timestamp()).strftime("%Y%m%d")
            filename = f"{date_str}_{doc.id}_{sender_id}_{media_type}{ext}"
            filepath = os.path.join(media_dir, filename)
            
            if os.path.exists(filepath):
                print(f"  Skipped (exists): {filename}")
            else:
                await client.download_media(message, filepath)
                print(f"  Downloaded: {filename}")
            
            return {
                "type": "voice" if is_voice else ("video" if is_video else "document"),
                "path": filepath,
                "filename": filename
            }
        
        return None
        
    except Exception as e:
        print(f"  Error downloading media: {e}")
        return None

async def download_messages(
    client: TelegramClient,
    entity,
    output_dir: str,
    limit: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    
    messages_data = []
    media_dir = os.path.join(output_dir, MEDIA_DIR)
    os.makedirs(media_dir, exist_ok=True)
    
    print(f"\n{'='*60}")
    print("PHASE 1: Downloading messages and media")
    print(f"{'='*60}")
    if start_date:
        print(f"  From: {start_date.strftime('%Y-%m-%d')}")
    if end_date:
        print(f"  Until: {end_date.strftime('%Y-%m-%d')}")
    print()
    
    async for message in client.iter_messages(entity, limit=limit):
        if start_date and message.date and message.date < start_date:
            continue
        if end_date and message.date and message.date > end_date:
            continue
        
        msg_data = {
            "id": message.id,
            "date": message.date.isoformat() if message.date else None,
            "text": message.text or "",
            "sender_id": message.sender_id,
            "media": None
        }
        
        if message.media:
            media_info = await download_media(client, message, media_dir)
            if media_info:
                msg_data["media"] = media_info
        
        messages_data.append(msg_data)
        
        if len(messages_data) % 50 == 0:
            print(f"  Progress: {len(messages_data)} messages processed")
    
    print(f"\n  Total messages: {len(messages_data)}")
    
    messages_file = os.path.join(output_dir, "messages.json")
    with open(messages_file, 'w', encoding='utf-8') as f:
        json.dump(messages_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {messages_file}")
    
    return messages_data

def transcribe_media(messages: List[Dict[str, Any]], output_dir: str, config: Dict[str, Any]) -> None:
    print(f"\n{'='*60}")
    print("PHASE 2: Transcribing voice and video messages")
    print(f"{'='*60}")
    
    method_key = config.get("transcription_method", DEFAULT_METHOD)
    method_info = TRANSCRIPTION_METHODS[method_key]
    print(f"  Method: {method_info['name']} ({method_info['quality']} quality)")
    
    media_dir = os.path.join(output_dir, MEDIA_DIR)
    transcriptions_file = os.path.join(output_dir, "transcriptions.json")
    
    existing_transcriptions = {}
    if os.path.exists(transcriptions_file):
        try:
            with open(transcriptions_file, 'r', encoding='utf-8') as f:
                existing_transcriptions = json.load(f)
            print(f"  Loaded {len(existing_transcriptions)} existing transcriptions")
        except:
            pass
    
    media_to_transcribe = []
    for msg in messages:
        if msg.get('media'):
            m = msg['media']
            if m['type'] in ('voice', 'video'):
                if m['filename'] in existing_transcriptions:
                    m['transcription'] = existing_transcriptions[m['filename']]
                else:
                    media_to_transcribe.append(m)
    
    if not media_to_transcribe and not existing_transcriptions:
        print("  No voice or video messages to transcribe.")
        return
    
    if media_to_transcribe:
        print(f"  Found {len(media_to_transcribe)} voice/video messages to transcribe")
        
        detected_language = None
        if method_info['type'] == 'local':
            first_media = media_to_transcribe[0]
            first_file = first_media['path']
            if first_media['type'] == 'video':
                first_file = first_file.rsplit('.', 1)[0] + "_audio.wav"
                extract_audio_from_video(first_media['path'], first_file)
            
            detected_language = detect_language(first_file, method_info['name'])
            
            if first_media['type'] == 'video':
                try:
                    os.remove(first_file)
                except:
                    pass
        
        print()
        
        api_key = None
        if method_info['type'] == 'api':
            api_key = get_api_key(method_info['provider'], config)
        
        for i, m in enumerate(media_to_transcribe, 1):
            print(f"[{i}/{len(media_to_transcribe)}] {m['filename']}")
            
            file_path = m['path']
            if m['type'] == 'video':
                audio_path = m['path'].rsplit('.', 1)[0] + "_audio.wav"
                if extract_audio_from_video(m['path'], audio_path):
                    file_path = audio_path
                else:
                    m['transcription'] = None
                    print("  → [Audio extraction failed]")
                    continue
            
            if method_info['type'] == 'local':
                m['transcription'] = transcribe_audio(file_path, method_info['name'], language=detected_language)
            elif method_info['provider'] == 'gemini':
                m['transcription'] = transcribe_with_gemini(file_path, detected_language, api_key)
            elif method_info['provider'] == 'openrouter':
                model_map = {
                    "claude-sonnet": "anthropic/claude-3.5-sonnet",
                    "claude-opus": "anthropic/claude-3-opus",
                }
                model = model_map.get(method_info['name'], "anthropic/claude-3.5-sonnet")
                m['transcription'] = transcribe_with_openrouter(file_path, detected_language, model, api_key)
            
            if m['type'] == 'video':
                try:
                    os.remove(file_path)
                except:
                    pass
            
            if m['transcription']:
                existing_transcriptions[m['filename']] = m['transcription']
                text_preview = m['transcription'][:100] + ('...' if len(m['transcription']) > 100 else '')
                print(f"  → {text_preview}")
                
                with open(transcriptions_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_transcriptions, f, ensure_ascii=False, indent=2)
            else:
                print("  → [Transcription failed]")
            
            print()
        
        print("  Transcription complete!")
    else:
        print("  All transcriptions already exist. Skipping...")
    
    for msg in messages:
        if msg.get('media') and msg['media']['type'] in ('voice', 'video'):
            if msg['media']['filename'] in existing_transcriptions:
                msg['media']['transcription'] = existing_transcriptions[msg['media']['filename']]

def describe_images(messages: List[Dict[str, Any]], output_dir: str, language: Optional[str] = None) -> None:
    print(f"\n{'='*60}")
    print("PHASE 2b: Describing images")
    print(f"{'='*60}")
    
    media_dir = os.path.join(output_dir, MEDIA_DIR)
    descriptions_file = os.path.join(output_dir, "descriptions.json")
    
    existing_descriptions = {}
    if os.path.exists(descriptions_file):
        try:
            with open(descriptions_file, 'r', encoding='utf-8') as f:
                existing_descriptions = json.load(f)
            print(f"  Loaded {len(existing_descriptions)} existing descriptions")
        except:
            pass
    
    images_to_describe = []
    for msg in messages:
        if msg.get('media') and msg['media']['type'] == 'photo':
            if msg['media']['filename'] in existing_descriptions:
                msg['media']['description'] = existing_descriptions[msg['media']['filename']]
            else:
                images_to_describe.append(msg['media'])
    
    if not images_to_describe and not existing_descriptions:
        print("  No images to describe.")
        return
    
    if images_to_describe:
        print(f"  Found {len(images_to_describe)} images to describe\n")
        
        for i, img in enumerate(images_to_describe, 1):
            print(f"[{i}/{len(images_to_describe)}] {img['filename']}")
            
            description = describe_image(img['path'], language)
            
            if description:
                img['description'] = description
                existing_descriptions[img['filename']] = description
                print(f"  → {description[:80]}{'...' if len(description) > 80 else ''}")
                
                with open(descriptions_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_descriptions, f, ensure_ascii=False, indent=2)
            else:
                print("  → [Description failed]")
            
            print()
        
        print("  Image description complete!")
    else:
        print("  All image descriptions already exist. Skipping...")
    
    for msg in messages:
        if msg.get('media') and msg['media']['type'] == 'photo':
            if msg['media']['filename'] in existing_descriptions:
                msg['media']['description'] = existing_descriptions[msg['media']['filename']]

def get_sender_name(sender) -> str:
    if hasattr(sender, 'first_name'):
        parts = [sender.first_name or ""]
        if hasattr(sender, 'last_name') and sender.last_name:
            parts.append(sender.last_name)
        return " ".join(parts).strip() or str(sender.id)
    return str(sender.id)

def generate_html(messages: List[Dict], participants: Dict[int, str], output_path: str, chat_name: str):
    print(f"\n{'='*60}")
    print("PHASE 3: Generating HTML output")
    print(f"{'='*60}")
    
    html_template = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram Chat Archive - {chat_name}</title>
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
        sender_name = participants.get(msg['sender_id'], f"User {msg['sender_id']}")
        is_outgoing = msg['sender_id'] > 0 and msg['sender_id'] < 1000000000
        
        avatar_char = sender_name[0].upper() if sender_name else "?"
        
        media_html = ""
        if msg.get('media'):
            m = msg['media']
            if m['type'] == 'photo':
                rel_path = os.path.join(MEDIA_DIR, m['filename'])
                media_html = f'''<div class="media">
                    <img src="{rel_path}" onclick="openLightbox('{rel_path}')" alt="Photo">
                </div>'''
                if m.get('description'):
                    media_html += f'''<div class="description">
                        <span class="description-label">📷</span> {m['description']}
                    </div>'''
            elif m['type'] == 'video':
                rel_path = os.path.join(MEDIA_DIR, m['filename'])
                media_html = f'''<div class="media">
                    <video controls><source src="{rel_path}" type="video/mp4"></video>
                </div>'''
            elif m['type'] == 'voice':
                rel_path = os.path.join(MEDIA_DIR, m['filename'])
                media_html = f'''<div class="media">
                    <audio controls><source src="{rel_path}" type="audio/ogg"></audio>
                </div>'''
            elif m['type'] == 'document':
                rel_path = os.path.join(MEDIA_DIR, m['filename'])
                media_html = f'''<div class="media">
                    <a href="{rel_path}" target="_blank">📄 {m['filename']}</a>
                </div>'''
            
            if m.get('transcription'):
                media_html += f'''<div class="transcription">
                    <div class="transcription-label">📝 Transcription</div>
                    {m['transcription']}
                </div>'''
        
        timestamp = msg['date'].split('T')[0] if msg['date'] else ''
        
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
        chat_name=chat_name,
        export_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        messages_html='\n'.join(messages_html)
    )
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"  Output: {output_path}")

async def list_chats(client: TelegramClient):
    print("\nFetching your chats...")
    print("-" * 50)
    
    dialogs = await client.get_dialogs(limit=50)
    
    for i, dialog in enumerate(dialogs, 1):
        entity = dialog.entity
        name = getattr(entity, 'title', None) or getattr(entity, 'first_name', None) or getattr(entity, 'username', 'Unknown')
        if hasattr(entity, 'last_name') and entity.last_name:
            name += f" {entity.last_name}"
        
        chat_type = "Group" if hasattr(entity, 'participants_count') else "Channel" if hasattr(entity, 'broadcast') else "User"
        print(f"{i:3}. [{chat_type:7}] {name}")
    
    return dialogs

async def select_chat(client: TelegramClient):
    dialogs = await list_chats(client)
    
    print("\n" + "-" * 50)
    choice = input("Enter chat number (or paste username/phone/ID): ").strip()
    
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(dialogs):
            return dialogs[idx].entity
        print("Invalid number!")
        return None
    
    try:
        entity = await client.get_entity(choice)
        return entity
    except Exception as e:
        print(f"Error: {e}")
        return None

async def main():
    print("=" * 60)
    print("  Telegram Chat Archive Tool")
    print("  Exports chats with voice/video transcription")
    print("=" * 60)
    
    sessions_dir = Path(SESSIONS_DIR)
    sessions_dir.mkdir(exist_ok=True)
    
    config = load_config()
    
    session_files = list(sessions_dir.glob("*.session"))
    
    if session_files:
        print("\nFound existing sessions:")
        for i, sf in enumerate(session_files, 1):
            print(f"  {i}. {sf.stem}")
        print(f"  {len(session_files) + 1}. Create new session")
        
        choice = input("\nSelect session: ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(session_files):
                session_name = session_files[idx].stem
            else:
                session_name = None
        else:
            session_name = None
    else:
        session_name = None
    
    if not session_name:
        print("\n--- Create New Session ---")
        print("Get API credentials from: https://my.telegram.org/apps")
        api_id = input("API ID: ").strip()
        api_hash = input("API Hash: ").strip()
        phone = input("Phone number (with country code): ").strip()
        session_name = input("Session name (e.g., 'my_account'): ").strip()
        
        session_path = sessions_dir / session_name
        client = TelegramClient(str(session_path), int(api_id), api_hash)
        await client.start(phone)
        
        creds_file = session_path.with_suffix('.json')
        with open(creds_file, 'w') as f:
            json.dump({'api_id': int(api_id), 'api_hash': api_hash}, f)
        
        print("Session created successfully!")
    else:
        session_path = sessions_dir / session_name
        creds_file = session_path.with_suffix('.json')
        
        if not creds_file.exists():
            print(f"Error: Credentials file not found for session '{session_name}'")
            print("Please create a new session or provide credentials file.")
            return
        
        with open(creds_file, 'r') as f:
            creds = json.load(f)
        
        client = TelegramClient(str(session_path.with_suffix('')), creds['api_id'], creds['api_hash'])
        await client.start()
    
    try:
        select_transcription_method(config)
        
        entity = await select_chat(client)
        if not entity:
            print("No chat selected. Exiting.")
            return
        
        chat_name = getattr(entity, 'title', None) or getattr(entity, 'first_name', 'Unknown')
        if hasattr(entity, 'last_name') and entity.last_name:
            chat_name += f" {entity.last_name}"
        
        output_dir = Path("exports") / chat_name.replace('/', '_').replace('\\', '_')
        output_dir.mkdir(parents=True, exist_ok=True)
        media_dir = output_dir / MEDIA_DIR
        media_dir.mkdir(exist_ok=True)
        
        print(f"\nExporting chat: {chat_name}")
        print(f"Output directory: {output_dir}")
        
        print("\nHow would you like to filter messages?")
        print("  1. Export all messages")
        print("  2. Set message limit")
        print("  3. Set date range")
        filter_choice = input("Select option (1-3): ").strip()
        
        limit = None
        start_date = None
        end_date = None
        
        if filter_choice == "2":
            limit_input = input("Message limit: ").strip()
            limit = int(limit_input) if limit_input.isdigit() else None
        elif filter_choice == "3":
            start_input = input("Start date (YYYY-MM-DD, or press Enter to skip): ").strip()
            end_input = input(f"End date (YYYY-MM-DD, default: {datetime.now().strftime('%Y-%m-%d')}): ").strip()
            
            if start_input:
                try:
                    start_date = datetime.strptime(start_input, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    print("Invalid start date format, ignoring...")
            
            if end_input:
                try:
                    end_date = datetime.strptime(end_input, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
                except ValueError:
                    print("Invalid end date format, using today...")
                    end_date = datetime.now(timezone.utc)
            else:
                end_date = datetime.now(timezone.utc)
        
        messages = await download_messages(client, entity, str(output_dir), limit=limit, start_date=start_date, end_date=end_date)
        
        transcribe_media(messages, str(output_dir), config)
        
        # Load detected language from transcriptions or detect from first image
        descriptions_file = output_dir / "descriptions.json"
        detected_language = None
        transcriptions_file = output_dir / "transcriptions.json"
        if transcriptions_file.exists():
            try:
                with open(transcriptions_file, 'r') as f:
                    trans_data = json.load(f)
                    # Language was used for transcription, we'll use same for descriptions
            except:
                pass
        
        describe_images(messages, str(output_dir), language=detected_language)
        
        participants = {}
        async for msg in client.iter_messages(entity, limit=min(len(messages), 100)):
            try:
                sender = await msg.get_sender()
                if sender:
                    participants[msg.sender_id] = get_sender_name(sender)
            except:
                pass
        
        output_file = output_dir / OUTPUT_FILE
        generate_html(messages, participants, str(output_file), chat_name)
        
        print(f"\n{'='*60}")
        print("EXPORT COMPLETE!")
        print(f"{'='*60}")
        print(f"\nOpen {output_file} in your browser to view the archive.")
        
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())