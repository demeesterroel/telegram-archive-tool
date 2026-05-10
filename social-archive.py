#!/usr/bin/env python3
"""
Chat Archive Tool
Archive Telegram and Signal chats with voice transcription and image descriptions.

Usage:
  python social-archive.py signal   [--chat NAME] [--export-dir DIR] [--skip-export]
  python social-archive.py telegram [--chat NAME] [--session NAME] [--start-date DATE] [--end-date DATE] [--limit N]
  python social-archive.py          # fully interactive
"""

import argparse
import asyncio
import json
import mimetypes
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

# ─── Signal constants ────────────────────────────────────────────────────────

SIGNAL_OUTPUT_FILE = "signal_archive.html"
ME_SENDER_ID = 1
OTHER_SENDER_ID_START = 1_000_000_001


# ─── Signal helpers ──────────────────────────────────────────────────────────

def detect_media_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("png", "jpg", "jpeg", "gif", "tif", "tiff", "webp"):
        return "photo"
    elif ext in ("m4a", "aac", "ogg", "oga", "mp3", "wav"):
        return "voice"
    elif ext in ("mp4", "mov", "avi", "mkv"):
        return "video"
    return "document"


def load_signal_export(chat_dir: Path) -> Tuple[List[Dict[str, Any]], Dict[int, str]]:
    data_json = chat_dir / "data.json"
    if not data_json.exists():
        print(f"Error: {data_json} not found.")
        sys.exit(1)

    sender_name_to_id: Dict[str, int] = {}
    next_other_id = OTHER_SENDER_ID_START
    messages = []

    with open(data_json, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue

            raw = json.loads(line)
            sender: str = raw.get("sender") or "Unknown"

            if sender == "Me":
                sid = ME_SENDER_ID
            else:
                if sender not in sender_name_to_id:
                    sender_name_to_id[sender] = next_other_id
                    next_other_id += 1
                sid = sender_name_to_id[sender]

            text_parts = []
            quote = (raw.get("quote") or "").strip()
            if quote:
                text_parts.append(f"> {quote}")
            body = (raw.get("body") or "").strip()
            if body:
                text_parts.append(body)
            sticker = (raw.get("sticker") or "").strip()
            if sticker:
                text_parts.append(f"[Sticker: {sticker}]")
            reactions = raw.get("reactions") or []
            if reactions:
                parts = []
                for r in reactions:
                    if isinstance(r, list) and len(r) >= 2:
                        parts.append(f"{r[0]}: {r[1]}")
                    elif isinstance(r, dict) and r.get("name") and r.get("emoji"):
                        parts.append(f'{r["name"]}: {r["emoji"]}')
                if parts:
                    text_parts.append("(" + ", ".join(parts) + ")")
            text = "\n".join(text_parts)

            media: Optional[Dict[str, Any]] = None
            for att in raw.get("attachments") or []:
                att_path_str = (att.get("path") or "").replace("%20", " ")
                if not att_path_str:
                    continue
                abs_path = chat_dir / att_path_str
                if not abs_path.exists():
                    continue
                filename = abs_path.name
                media = {
                    "type": detect_media_type(filename),
                    "path": str(abs_path),
                    "filename": filename,
                }
                break

            messages.append({
                "id": i,
                "date": raw.get("date", ""),
                "text": text,
                "sender_id": sid,
                "media": media,
            })

    participants: Dict[int, str] = {ME_SENDER_ID: "Me"}
    for name, sid in sender_name_to_id.items():
        participants[sid] = name

    return messages, participants


def run_sigexport(export_dir: Path) -> None:
    if not shutil.which("sigexport"):
        print("Error: sigexport not found. Run:  pip install signal-export")
        sys.exit(1)
    export_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nRunning sigexport → {export_dir}")
    result = subprocess.run(["sigexport", "--overwrite", str(export_dir)], check=False)
    if result.returncode != 0:
        print(f"Error: sigexport failed (exit {result.returncode}).")
        sys.exit(1)


def list_signal_chats(export_dir: Path) -> List[Path]:
    return sorted(d for d in export_dir.iterdir() if d.is_dir() and (d / "data.json").exists())


def count_lines(path: Path) -> int:
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


# ─── Signal main ─────────────────────────────────────────────────────────────

def run_signal(args) -> None:
    print("=" * 60)
    print("  Signal Chat Archive Tool")
    print("=" * 60)

    config = load_config()

    if args.export_dir:
        export_dir = Path(args.export_dir).expanduser()
    else:
        default_export = Path.home() / "signal-export"
        raw = input(f"\nPath to signal-export output [{default_export}]: ").strip()
        export_dir = Path(raw).expanduser() if raw else default_export

    if args.skip_export:
        if not export_dir.exists():
            print(f"Error: directory not found: {export_dir}")
            sys.exit(1)
    else:
        run_sigexport(export_dir)

    chats = list_signal_chats(export_dir)
    if not chats:
        print(f"No signal-export chat directories found in {export_dir}")
        sys.exit(1)

    if args.chat:
        matches = [d for d in chats if d.name == args.chat]
        if not matches:
            print(f"Error: chat '{args.chat}' not found in {export_dir}")
            print("Available:", ", ".join(d.name for d in chats))
            sys.exit(1)
        chat_dir = matches[0]
    else:
        print("\nAvailable chats:")
        for i, d in enumerate(chats, 1):
            count = count_lines(d / "data.json")
            print(f"  {i:3}. {d.name}  ({count} messages)")
        choice = input("\nSelect chat number: ").strip()
        if not choice.isdigit() or not (1 <= int(choice) <= len(chats)):
            print("Invalid choice.")
            sys.exit(1)
        chat_dir = chats[int(choice) - 1]

    chat_name = chat_dir.name
    print(f"\nProcessing: {chat_name}")

    project_root = Path(__file__).parent
    output_dir = project_root / "archive" / "signal" / chat_name
    output_dir.mkdir(parents=True, exist_ok=True)

    media_link = output_dir / "media"
    media_source = chat_dir / "media"
    if media_source.exists() and not media_link.exists():
        os.symlink(media_source.resolve(), media_link)

    resolve_transcription(config, args.transcription)

    print(f"\n{'='*60}")
    print("PHASE 1: Loading messages from signal-export")
    print(f"{'='*60}")
    messages, participants = load_signal_export(chat_dir)
    print(f"  Loaded {len(messages)} messages")

    transcribe_media(messages, str(output_dir), config)
    describe_images(messages, str(output_dir))

    output_file = output_dir / SIGNAL_OUTPUT_FILE
    generate_html(messages, participants, str(output_file), chat_name, app_name="Signal")

    print(f"\n{'='*60}")
    print("EXPORT COMPLETE!")
    print(f"{'='*60}")
    print(f"\nOpen {output_file} in your browser.")


# ─── Telegram helpers ─────────────────────────────────────────────────────────

def get_sender_name(sender) -> str:
    if hasattr(sender, "first_name"):
        parts = [sender.first_name or ""]
        if hasattr(sender, "last_name") and sender.last_name:
            parts.append(sender.last_name)
        return " ".join(parts).strip() or str(sender.id)
    return str(sender.id)


async def download_media_tg(client, message, media_dir: str) -> Optional[Dict[str, Any]]:
    from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto
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


async def download_messages_tg(client, entity, output_dir: str, limit=None, start_date=None, end_date=None):
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
            media_info = await download_media_tg(client, message, media_dir)
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


async def list_telegram_chats(client):
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


async def select_telegram_chat(client):
    dialogs = await list_telegram_chats(client)
    print("\n" + "-" * 50)
    choice = input("Enter chat number (or paste username/phone/ID): ").strip()
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(dialogs):
            return dialogs[idx].entity
        print("Invalid number.")
        return None
    try:
        return await client.get_entity(choice)
    except Exception as e:
        print(f"Error: {e}")
        return None


# ─── Telegram main ────────────────────────────────────────────────────────────

async def run_telegram(args) -> None:
    from telethon import TelegramClient

    print("=" * 60)
    print("  Telegram Chat Archive Tool")
    print("=" * 60)

    sessions_dir = Path(SESSIONS_DIR)
    sessions_dir.mkdir(exist_ok=True)

    config = load_config()
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
        session_name = input("Session name (e.g. 'my_account'): ").strip()

        session_path = sessions_dir / session_name
        client = TelegramClient(str(session_path), int(api_id), api_hash)
        await client.start(phone)

        creds_file = session_path.with_suffix(".json")
        with open(creds_file, "w") as f:
            json.dump({"api_id": int(api_id), "api_hash": api_hash}, f)
        print("Session created.")
    else:
        session_path = sessions_dir / session_name
        creds_file = session_path.with_suffix(".json")
        if not creds_file.exists():
            print(f"Error: credentials not found for session '{session_name}'")
            return
        with open(creds_file, "r") as f:
            creds = json.load(f)
        client = TelegramClient(str(session_path.with_suffix("")), creds["api_id"], creds["api_hash"])
        await client.start()

    try:
        resolve_transcription(config, args.transcription)

        if args.chat:
            try:
                entity = await client.get_entity(args.chat)
            except Exception as e:
                print(f"Error finding chat '{args.chat}': {e}")
                return
        else:
            entity = await select_telegram_chat(client)

        if not entity:
            print("No chat selected.")
            return

        chat_name = getattr(entity, "title", None) or getattr(entity, "first_name", "Unknown")
        if hasattr(entity, "last_name") and entity.last_name:
            chat_name += f" {entity.last_name}"

        output_dir = Path("archive") / "telegram" / chat_name.replace("/", "_").replace("\\", "_")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / MEDIA_DIR).mkdir(exist_ok=True)

        print(f"\nExporting: {chat_name}")
        print(f"Output: {output_dir}")

        limit = args.limit
        start_date = None
        end_date = None

        if args.start_date or args.end_date:
            if args.start_date:
                try:
                    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    print(f"Invalid --start-date, ignoring.")
            end_str = args.end_date
            if end_str:
                try:
                    end_date = datetime.strptime(end_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
                except ValueError:
                    end_date = datetime.now(timezone.utc)
            else:
                end_date = datetime.now(timezone.utc)
        elif not args.limit and not args.chat:
            print("\nFilter messages?")
            print("  1. Export all")
            print("  2. Message limit")
            print("  3. Date range")
            filter_choice = input("Select (1-3): ").strip()
            if filter_choice == "2":
                raw = input("Limit: ").strip()
                limit = int(raw) if raw.isdigit() else None
            elif filter_choice == "3":
                start_input = input("Start date (YYYY-MM-DD, or Enter to skip): ").strip()
                end_input = input(f"End date (YYYY-MM-DD, default today): ").strip()
                if start_input:
                    try:
                        start_date = datetime.strptime(start_input, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    except ValueError:
                        print("Invalid start date, ignoring.")
                end_date = datetime.now(timezone.utc)
                if end_input:
                    try:
                        end_date = datetime.strptime(end_input, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
                    except ValueError:
                        print("Invalid end date, using today.")

        messages = await download_messages_tg(
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
        print(f"\nOpen {output_file} in your browser.")

    finally:
        await client.disconnect()


# ─── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chat Archive Tool — archive Telegram and Signal chats",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python social-archive.py signal --chat "Jane Doe"
  python social-archive.py signal --skip-export --chat "Jane Doe"
  python social-archive.py telegram --session my_account --chat "Jane Doe"
  python social-archive.py telegram --session my_account --start-date 2024-01-01
  python social-archive.py          # fully interactive
        """,
    )

    subparsers = parser.add_subparsers(dest="platform")

    # Signal subcommand
    sp = subparsers.add_parser("signal", help="Archive a Signal chat")
    sp.add_argument("--export-dir", "-e", help="Path to sigexport output (default: ~/signal-export)")
    sp.add_argument("--chat", "-c", help="Chat name (directory name in export-dir)")
    sp.add_argument("--skip-export", "-s", action="store_true", help="Skip running sigexport")
    add_transcription_arg(sp)

    # Telegram subcommand
    tp = subparsers.add_parser("telegram", help="Archive a Telegram chat")
    tp.add_argument("--session", "-s", help="Session name")
    tp.add_argument("--chat", "-c", help="Chat name, username, phone, or ID")
    tp.add_argument("--start-date", help="Start date YYYY-MM-DD (inclusive)")
    tp.add_argument("--end-date", help="End date YYYY-MM-DD (inclusive, default: today)")
    tp.add_argument("--limit", type=int, help="Max messages to fetch")
    add_transcription_arg(tp)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.platform:
        print("Select platform:")
        print("  1. Signal")
        print("  2. Telegram")
        choice = input("Select (1-2): ").strip()
        if choice == "1":
            args.platform = "signal"
            args.export_dir = None
            args.chat = None
            args.skip_export = False
            args.transcription = None
        elif choice == "2":
            args.platform = "telegram"
            args.session = None
            args.chat = None
            args.start_date = None
            args.end_date = None
            args.limit = None
            args.transcription = None
        else:
            print("Invalid choice.")
            sys.exit(1)

    if args.platform == "signal":
        run_signal(args)
    elif args.platform == "telegram":
        asyncio.run(run_telegram(args))


if __name__ == "__main__":
    main()
