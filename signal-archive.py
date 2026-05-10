#!/usr/bin/env python3
"""
Signal Chat Archive Tool
Processes signal-export output with voice transcription and image descriptions.

Prerequisites:
  pip install signal-export

The script runs sigexport automatically before processing.
Use --skip-export to skip if you already have a fresh export.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import (
    add_transcription_arg,
    describe_images,
    generate_html,
    load_config,
    resolve_transcription,
    transcribe_media,
)

OUTPUT_FILE = "signal_archive.html"

# "Me" gets sender_id=1 (satisfies 0 < id < 1_000_000_000 → outgoing in generate_html).
# All other senders get ids starting at 1_000_000_001 (→ incoming).
ME_SENDER_ID = 1
OTHER_SENDER_ID_START = 1_000_000_001


def detect_media_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("png", "jpg", "jpeg", "gif", "tif", "tiff", "webp"):
        return "photo"
    elif ext in ("m4a", "aac", "ogg", "oga", "mp3", "wav"):
        return "voice"
    elif ext in ("mp4", "mov", "avi", "mkv"):
        return "video"
    return "document"


def load_signal_export(
    chat_dir: Path,
) -> Tuple[List[Dict[str, Any]], Dict[int, str]]:
    """
    Read signal-export's data.json (one JSON object per line) and return
    (messages, participants) in the shared pipeline format.
    """
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

            # Build display text: optional quoted reply + body + sticker + reactions
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

            # Use the first attachment (multiple per message are rare)
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

            messages.append(
                {
                    "id": i,
                    "date": raw.get("date", ""),
                    "text": text,
                    "sender_id": sid,
                    "media": media,
                }
            )

    participants: Dict[int, str] = {ME_SENDER_ID: "Me"}
    for name, sid in sender_name_to_id.items():
        participants[sid] = name

    return messages, participants


def run_sigexport(export_dir: Path) -> None:
    if not shutil.which("sigexport"):
        print("Error: sigexport not found. Install with:  pip install signal-export")
        sys.exit(1)
    export_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nRunning sigexport → {export_dir}")
    result = subprocess.run(
        ["sigexport", "--overwrite", str(export_dir)],
        check=False,
    )
    if result.returncode != 0:
        print(f"Error: sigexport failed (exit {result.returncode}).")
        sys.exit(1)


def list_chats(export_dir: Path) -> List[Path]:
    return sorted(
        d for d in export_dir.iterdir()
        if d.is_dir() and (d / "data.json").exists()
    )


def count_lines(path: Path) -> int:
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Signal Chat Archive Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Interactive mode:
    python signal-archive.py

  Non-interactive:
    python signal-archive.py --export-dir ~/signal-export --chat "Jane Doe"
    python signal-archive.py -e ~/signal-export -c "Jane Doe" -t 4
        """,
    )
    parser.add_argument(
        "--export-dir", "-e",
        help="Path to signal-export output directory (default: ~/signal-export)",
    )
    parser.add_argument(
        "--chat", "-c",
        help="Chat name (directory name inside export-dir)",
    )
    parser.add_argument(
        "--skip-export", "-s",
        action="store_true",
        help="Skip running sigexport (use existing export directory as-is)",
    )
    add_transcription_arg(parser)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("=" * 60)
    print("  Signal Chat Archive Tool")
    print("  Processes signal-export output")
    print("=" * 60)

    config = load_config()

    # --- Export dir ---
    if args.export_dir:
        export_dir = Path(args.export_dir).expanduser()
    else:
        default_export = Path.home() / "signal-export"
        raw_input = input(f"\nPath to signal-export output directory [{default_export}]: ").strip()
        export_dir = Path(raw_input).expanduser() if raw_input else default_export

    if args.skip_export:
        if not export_dir.exists():
            print(f"Error: directory not found: {export_dir}")
            sys.exit(1)
    else:
        run_sigexport(export_dir)

    chats = list_chats(export_dir)
    if not chats:
        print(f"No signal-export chat directories found in {export_dir}")
        print("Run:  sigexport ~/signal-export-output")
        sys.exit(1)

    # --- Chat selection ---
    if args.chat:
        matches = [d for d in chats if d.name == args.chat]
        if not matches:
            print(f"Error: chat '{args.chat}' not found in {export_dir}")
            print("Available chats:", ", ".join(d.name for d in chats))
            sys.exit(1)
        chat_dir = matches[0]
    else:
        print("\nAvailable chats:")
        for i, chat_dir in enumerate(chats, 1):
            count = count_lines(chat_dir / "data.json")
            print(f"  {i:3}. {chat_dir.name}  ({count} messages)")

        choice = input("\nSelect chat number: ").strip()
        if not choice.isdigit() or not (1 <= int(choice) <= len(chats)):
            print("Invalid choice.")
            sys.exit(1)
        chat_dir = chats[int(choice) - 1]

    chat_name = chat_dir.name
    print(f"\nProcessing: {chat_name}")

    # Output goes to archive/signal/<chatname>/ inside the project directory
    project_root = Path(__file__).parent
    output_dir = project_root / "archive" / "signal" / chat_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Symlink media/ into the output dir so HTML relative paths work without copying files
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

    # Phase 2: transcribe audio/video — transcriptions.json saved in output_dir
    transcribe_media(messages, str(output_dir), config)

    # Phase 2b: describe images — descriptions.json saved in output_dir
    describe_images(messages, str(output_dir))

    # Phase 3: generate HTML
    output_file = output_dir / OUTPUT_FILE
    generate_html(messages, participants, str(output_file), chat_name, app_name="Signal")

    print(f"\n{'='*60}")
    print("EXPORT COMPLETE!")
    print(f"{'='*60}")
    print(f"\nOpen {output_file} in your browser to view the archive.")


if __name__ == "__main__":
    main()
