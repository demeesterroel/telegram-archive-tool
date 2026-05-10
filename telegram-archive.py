#!/usr/bin/env python3
"""
Telegram Chat Archive Tool
Exports Telegram chat history with transcribed voice/video messages and image descriptions.
"""

import argparse
import asyncio
import json
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from telethon import TelegramClient
from telethon.tl.types import Message, MessageMediaDocument, MessageMediaPhoto

from common import (
    MEDIA_DIR,
    OUTPUT_FILE,
    SESSIONS_DIR,
    add_transcription_arg,
    describe_images,
    generate_html,
    load_config,
    resolve_transcription,
    transcribe_media,
)


def get_sender_name(sender) -> str:
    if hasattr(sender, "first_name"):
        parts = [sender.first_name or ""]
        if hasattr(sender, "last_name") and sender.last_name:
            parts.append(sender.last_name)
        return " ".join(parts).strip() or str(sender.id)
    return str(sender.id)


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
            return {"type": "photo", "path": filepath, "filename": filename}

        elif isinstance(media, MessageMediaDocument):
            doc = media.document
            if not doc:
                return None
            mime_type = getattr(doc, "mime_type", "")
            is_voice = "audio/ogg" in mime_type or "audio/oga" in mime_type
            is_video = "video" in mime_type
            ext = mimetypes.guess_extension(mime_type) or ""
            if is_voice and ext == ".oga":
                ext = ".oga"
            media_type = "voice" if is_voice else ("video" if is_video else "file")
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
                "filename": filename,
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
    end_date: Optional[datetime] = None,
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
            "media": None,
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
    with open(messages_file, "w", encoding="utf-8") as f:
        json.dump(messages_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {messages_file}")

    return messages_data


async def list_chats(client: TelegramClient):
    print("\nFetching your chats...")
    print("-" * 50)
    dialogs = await client.get_dialogs(limit=50)
    for i, dialog in enumerate(dialogs, 1):
        entity = dialog.entity
        name = (
            getattr(entity, "title", None)
            or getattr(entity, "first_name", None)
            or getattr(entity, "username", "Unknown")
        )
        if hasattr(entity, "last_name") and entity.last_name:
            name += f" {entity.last_name}"
        chat_type = (
            "Group" if hasattr(entity, "participants_count")
            else "Channel" if hasattr(entity, "broadcast")
            else "User"
        )
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
        return await client.get_entity(choice)
    except Exception as e:
        print(f"Error: {e}")
        return None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Telegram Chat Archive Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Interactive mode:
    python telegram-archive.py

  Non-interactive (existing session):
    python telegram-archive.py --session my_account --chat "Jane Doe"
    python telegram-archive.py --session my_account --chat "Jane Doe" --start-date 2024-01-01
    python telegram-archive.py --session my_account --chat username123 --limit 100
        """,
    )
    parser.add_argument("--session", "-s", help="Session name (e.g. my_account)")
    parser.add_argument("--chat", "-c", help="Chat name, username, phone number, or ID")
    parser.add_argument("--start-date", help="Start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--end-date", help="End date YYYY-MM-DD (inclusive, default: today)")
    parser.add_argument("--limit", type=int, help="Max number of messages to fetch")
    add_transcription_arg(parser)
    return parser.parse_args()


async def main():
    args = parse_args()

    print("=" * 60)
    print("  Telegram Chat Archive Tool")
    print("  Exports chats with voice/video transcription")
    print("=" * 60)

    sessions_dir = Path(SESSIONS_DIR)
    sessions_dir.mkdir(exist_ok=True)

    config = load_config()

    # --- Session selection ---
    session_name = args.session

    if not session_name:
        session_files = list(sessions_dir.glob("*.session"))
        if session_files:
            print("\nFound existing sessions:")
            for i, sf in enumerate(session_files, 1):
                print(f"  {i}. {sf.stem}")
            print(f"  {len(session_files) + 1}. Create new session")

            choice = input("\nSelect session: ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                session_name = session_files[idx].stem if 0 <= idx < len(session_files) else None

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

        creds_file = session_path.with_suffix(".json")
        with open(creds_file, "w") as f:
            json.dump({"api_id": int(api_id), "api_hash": api_hash}, f)

        print("Session created successfully!")
    else:
        session_path = sessions_dir / session_name
        creds_file = session_path.with_suffix(".json")

        if not creds_file.exists():
            print(f"Error: Credentials file not found for session '{session_name}'")
            return

        with open(creds_file, "r") as f:
            creds = json.load(f)

        client = TelegramClient(str(session_path.with_suffix("")), creds["api_id"], creds["api_hash"])
        await client.start()

    try:
        # --- Transcription method ---
        resolve_transcription(config, args.transcription)

        # --- Chat selection ---
        if args.chat:
            try:
                entity = await client.get_entity(args.chat)
            except Exception as e:
                print(f"Error finding chat '{args.chat}': {e}")
                return
        else:
            entity = await select_chat(client)

        if not entity:
            print("No chat selected. Exiting.")
            return

        chat_name = getattr(entity, "title", None) or getattr(entity, "first_name", "Unknown")
        if hasattr(entity, "last_name") and entity.last_name:
            chat_name += f" {entity.last_name}"

        output_dir = Path("archive") / "telegram" / chat_name.replace("/", "_").replace("\\", "_")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / MEDIA_DIR).mkdir(exist_ok=True)

        print(f"\nExporting chat: {chat_name}")
        print(f"Output directory: {output_dir}")

        # --- Date/limit filter ---
        limit = args.limit
        start_date = None
        end_date = None

        if args.start_date or args.end_date:
            if args.start_date:
                try:
                    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    print(f"Invalid --start-date '{args.start_date}', ignoring...")
            if args.end_date:
                try:
                    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
                except ValueError:
                    print(f"Invalid --end-date '{args.end_date}', using today...")
                    end_date = datetime.now(timezone.utc)
            else:
                end_date = datetime.now(timezone.utc)
        elif not args.limit and not args.chat:
            print("\nHow would you like to filter messages?")
            print("  1. Export all messages")
            print("  2. Set message limit")
            print("  3. Set date range")
            filter_choice = input("Select option (1-3): ").strip()

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

        messages = await download_messages(
            client, entity, str(output_dir),
            limit=limit, start_date=start_date, end_date=end_date,
        )

        transcribe_media(messages, str(output_dir), config)
        describe_images(messages, str(output_dir))

        participants = {}
        async for msg in client.iter_messages(entity, limit=min(len(messages), 100)):
            try:
                sender = await msg.get_sender()
                if sender:
                    participants[msg.sender_id] = get_sender_name(sender)
            except Exception:
                pass

        output_file = output_dir / OUTPUT_FILE
        generate_html(messages, participants, str(output_file), chat_name, app_name="Telegram")

        print(f"\n{'='*60}")
        print("EXPORT COMPLETE!")
        print(f"{'='*60}")
        print(f"\nOpen {output_file} in your browser to view the archive.")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
