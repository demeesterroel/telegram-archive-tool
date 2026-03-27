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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from telethon import TelegramClient, sync
from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument
import whisper

MEDIA_DIR = "media"
OUTPUT_FILE = "chat_export.html"
SESSIONS_DIR = "sessions"

model_cache = {}

def load_whisper_model(model_size: str = "base"):
    if model_size not in model_cache:
        print(f"Loading Whisper model ({model_size})...")
        model_cache[model_size] = whisper.load_model(model_size)
    return model_cache[model_size]

def transcribe_audio(file_path: str, model_size: str = "base") -> Optional[str]:
    try:
        model = load_whisper_model(model_size)
        print(f"  Transcribing: {os.path.basename(file_path)}")
        result = model.transcribe(file_path)
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

def transcribe_media(messages: List[Dict[str, Any]], output_dir: str) -> None:
    print(f"\n{'='*60}")
    print("PHASE 2: Transcribing voice and video messages")
    print(f"{'='*60}")
    
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
        print(f"  Found {len(media_to_transcribe)} voice/video messages to transcribe\n")
        
        for i, m in enumerate(media_to_transcribe, 1):
            print(f"[{i}/{len(media_to_transcribe)}] {m['filename']}")
            
            if m['type'] == 'video':
                audio_path = m['path'].rsplit('.', 1)[0] + "_audio.wav"
                if extract_audio_from_video(m['path'], audio_path):
                    m['transcription'] = transcribe_audio(audio_path, "base")
                    try:
                        os.remove(audio_path)
                    except:
                        pass
                else:
                    m['transcription'] = None
            else:
                m['transcription'] = transcribe_audio(m['path'], "base")
            
            if m['transcription']:
                existing_transcriptions[m['filename']] = m['transcription']
                print(f"  → {m['transcription'][:100]}{'...' if len(m['transcription']) > 100 else ''}")
            else:
                print("  → [Transcription failed]")
            
            print()
        
        with open(transcriptions_file, 'w', encoding='utf-8') as f:
            json.dump(existing_transcriptions, f, ensure_ascii=False, indent=2)
        
        print("  Transcription complete!")
    else:
        print("  All transcriptions already exist. Skipping...")
    
    for msg in messages:
        if msg.get('media') and msg['media']['type'] in ('voice', 'video'):
            if msg['media']['filename'] in existing_transcriptions:
                msg['media']['transcription'] = existing_transcriptions[msg['media']['filename']]

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
            background: #0e1621;
            color: #fff;
            line-height: 1.5;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            padding: 20px 0;
            border-bottom: 1px solid #2b5278;
            margin-bottom: 20px;
        }}
        .header h1 {{
            font-size: 24px;
            color: #fff;
        }}
        .header .info {{
            color: #8e9ba7;
            font-size: 14px;
            margin-top: 5px;
        }}
        .message {{
            display: flex;
            margin-bottom: 15px;
            padding: 10px 0;
        }}
        .message.outgoing {{
            flex-direction: row-reverse;
        }}
        .avatar {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: #2b5278;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            flex-shrink: 0;
        }}
        .message.outgoing .avatar {{
            background: #4fae4e;
        }}
        .message-content {{
            max-width: 70%;
            margin: 0 10px;
        }}
        .sender {{
            font-size: 13px;
            color: #54a3da;
            margin-bottom: 4px;
        }}
        .message.outgoing .sender {{
            color: #4fae4e;
            text-align: right;
        }}
        .bubble {{
            background: #182533;
            padding: 10px 15px;
            border-radius: 15px;
            display: inline-block;
        }}
        .message.outgoing .bubble {{
            background: #2b5278;
        }}
        .timestamp {{
            font-size: 11px;
            color: #8e9ba7;
            margin-top: 5px;
        }}
        .message.outgoing .timestamp {{
            text-align: right;
        }}
        .text {{
            white-space: pre-wrap;
            word-break: break-word;
        }}
        .media {{
            margin-top: 10px;
            max-width: 100%;
        }}
        .media img {{
            max-width: 300px;
            border-radius: 10px;
            cursor: pointer;
        }}
        .media video {{
            max-width: 300px;
            border-radius: 10px;
        }}
        .media a {{
            color: #54a3da;
            text-decoration: none;
        }}
        .media a:hover {{
            text-decoration: underline;
        }}
        .transcription {{
            background: rgba(255,255,255,0.05);
            padding: 8px 12px;
            border-radius: 8px;
            margin-top: 8px;
            font-style: italic;
            font-size: 13px;
            color: #a7b5c3;
            border-left: 3px solid #54a3da;
        }}
        .transcription-label {{
            font-weight: bold;
            color: #54a3da;
            font-size: 11px;
            text-transform: uppercase;
            margin-bottom: 4px;
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
            max-width: 90%;
            max-height: 90%;
        }}
        .lightbox.active {{
            display: flex;
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
        
        transcribe_media(messages, str(output_dir))
        
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