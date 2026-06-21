#!/usr/bin/env python3
"""Vidcribe — a small, organized transcription system.

Workflow
--------
1. Create a project:           ./transcribe.py new <project> [-d "description"]
2. Add media to it:            ./transcribe.py add <project> path/to/video.mp4 ...
3. Transcribe everything:      ./transcribe.py run <project> [--model base]
4. See what's there:           ./transcribe.py status [<project>]

Each project lives under projects/<name>/ with this layout:

    projects/<name>/
        media/          # source audio/video (git-ignored — large/binary)
        transcripts/    # one .txt, .json and .md per media file
        project.json    # manifest: every item, its status and metadata

Transcription is performed locally with openai-whisper (no data leaves the
machine). Run ./setup.sh once to install whisper + ffmpeg.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths & constants
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent
PROJECTS_DIR = ROOT / "projects"

# Extensions whisper/ffmpeg can handle. Used to validate `add` input.
MEDIA_EXTS = {
    # audio
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma",
    # video
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv",
}

OUTPUT_FORMATS = ("txt", "json", "md")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _now() -> str:
    """UTC timestamp, ISO-8601, second precision."""
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\-]+", "-", name.strip().lower()).strip("-")
    return slug or "untitled"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fmt_ts(seconds: float) -> str:
    """Seconds -> HH:MM:SS.mmm (used for readable timestamps)."""
    if seconds is None:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def _die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def _info(msg: str):
    print(msg, file=sys.stderr)


# --------------------------------------------------------------------------- #
# Manifest (project.json) read/write
# --------------------------------------------------------------------------- #

def _project_dir(name: str) -> Path:
    return PROJECTS_DIR / _slugify(name)


def _load_manifest(proj: Path) -> dict:
    mpath = proj / "project.json"
    if not mpath.exists():
        _die(f"no project at {proj} (run: transcribe.py new {proj.name})")
    with mpath.open() as fh:
        return json.load(fh)


def _save_manifest(proj: Path, manifest: dict):
    manifest["updated"] = _now()
    with (proj / "project.json").open("w") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _find_item(manifest: dict, media_name: str):
    for item in manifest["items"]:
        if Path(item["media"]).name == media_name:
            return item
    return None


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_new(args):
    name = _slugify(args.name)
    proj = PROJECTS_DIR / name
    if (proj / "project.json").exists():
        _die(f"project '{name}' already exists")

    (proj / "media").mkdir(parents=True, exist_ok=True)
    (proj / "transcripts").mkdir(parents=True, exist_ok=True)
    # keep empty media dir in git
    (proj / "media" / ".gitkeep").touch()

    manifest = {
        "name": name,
        "description": args.description or "",
        "created": _now(),
        "updated": _now(),
        "model": args.model,
        "items": [],
    }
    _save_manifest(proj, manifest)
    print(f"created project '{name}' at {proj.relative_to(ROOT)}")


def cmd_add(args):
    proj = _project_dir(args.name)
    manifest = _load_manifest(proj)
    media_dir = proj / "media"

    added = 0
    for src_str in args.files:
        src = Path(src_str).expanduser()
        if not src.exists():
            _info(f"skip (not found): {src}")
            continue
        if src.suffix.lower() not in MEDIA_EXTS:
            _info(f"skip (unsupported type '{src.suffix}'): {src.name}")
            continue

        dest = media_dir / src.name
        if dest.exists() and not args.force:
            _info(f"skip (already added, use --force): {src.name}")
            continue

        shutil.copy2(src, dest)
        digest = _sha256(dest)

        existing = _find_item(manifest, dest.name)
        record = {
            "media": f"media/{dest.name}",
            "added": _now(),
            "status": "pending",
            "sha256": digest,
            "size_bytes": dest.stat().st_size,
            "transcribed_at": None,
            "language": None,
            "duration_seconds": None,
            "outputs": {},
        }
        if existing:
            existing.update(record)
        else:
            manifest["items"].append(record)
        added += 1
        print(f"added {src.name}")

    _save_manifest(proj, manifest)
    print(f"{added} file(s) added to '{manifest['name']}'")


def _load_whisper():
    """Import whisper lazily so non-transcription commands need no deps."""
    try:
        import whisper  # noqa: F401
    except ImportError:
        _die(
            "openai-whisper is not installed. Run ./setup.sh "
            "(or: pip install -U openai-whisper) and ensure ffmpeg is on PATH."
        )
    if shutil.which("ffmpeg") is None:
        _die(
            "ffmpeg not found on PATH. Install it (e.g. apt-get install ffmpeg) "
            "or run ./setup.sh — whisper needs ffmpeg to decode media."
        )
    import whisper
    return whisper


def _write_outputs(proj: Path, item: dict, result: dict, model_name: str) -> dict:
    """Write .txt, .json and .md for one transcription result."""
    stem = Path(item["media"]).stem
    tdir = proj / "transcripts"
    tdir.mkdir(exist_ok=True)

    segments = result.get("segments", []) or []
    language = result.get("language")
    text = (result.get("text") or "").strip()
    duration = segments[-1]["end"] if segments else 0.0

    # --- plain text ---
    txt_path = tdir / f"{stem}.txt"
    txt_path.write_text(text + "\n", encoding="utf-8")

    # --- json (segments + word-ish timing + metadata) ---
    json_path = tdir / f"{stem}.json"
    json_payload = {
        "media": Path(item["media"]).name,
        "language": language,
        "model": model_name,
        "transcribed_at": _now(),
        "duration_seconds": round(duration, 3),
        "text": text,
        "segments": [
            {
                "id": s.get("id"),
                "start": round(s.get("start", 0.0), 3),
                "end": round(s.get("end", 0.0), 3),
                "text": (s.get("text") or "").strip(),
            }
            for s in segments
        ],
    }
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(json_payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    # --- markdown document ---
    md_path = tdir / f"{stem}.md"
    word_count = len(text.split())
    lines = [
        f"# {stem}",
        "",
        f"- **Source:** `{Path(item['media']).name}`",
        f"- **Language:** {language or 'unknown'}",
        f"- **Duration:** {_fmt_duration(duration)}",
        f"- **Words:** {word_count:,}",
        f"- **Model:** whisper `{model_name}`",
        f"- **Transcribed:** {_now()}",
        "",
        "## Summary",
        "",
        "<!-- Add a summary here (or generate one with an LLM over the transcript). -->",
        "",
        "## Transcript",
        "",
    ]
    for s in segments:
        ts = _fmt_ts(s.get("start", 0.0))
        seg_text = (s.get("text") or "").strip()
        if seg_text:
            lines.append(f"**[{ts}]** {seg_text}")
            lines.append("")
    if not segments:
        lines.append(text)
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "txt": str(txt_path.relative_to(proj)),
        "json": str(json_path.relative_to(proj)),
        "md": str(md_path.relative_to(proj)),
        "language": language,
        "duration": duration,
    }


def cmd_run(args):
    proj = _project_dir(args.name)
    manifest = _load_manifest(proj)
    model_name = args.model or manifest.get("model", "base")

    pending = [
        it for it in manifest["items"]
        if args.all or it["status"] != "transcribed"
    ]
    if args.only:
        pending = [it for it in pending if Path(it["media"]).name in set(args.only)]

    if not pending:
        print("nothing to transcribe (use --all to re-run everything)")
        return

    whisper = _load_whisper()
    _info(f"loading whisper model '{model_name}' ...")
    model = whisper.load_model(model_name)

    ok = 0
    for item in pending:
        media_path = proj / item["media"]
        if not media_path.exists():
            _info(f"skip (media missing): {item['media']}")
            item["status"] = "missing"
            continue

        print(f"transcribing {Path(item['media']).name} ...")
        try:
            result = model.transcribe(
                str(media_path),
                language=args.language,
                verbose=False,
            )
        except Exception as exc:  # noqa: BLE001
            _info(f"  failed: {exc}")
            item["status"] = "error"
            item["error"] = str(exc)
            _save_manifest(proj, manifest)
            continue

        out = _write_outputs(proj, item, result, model_name)
        item.update(
            status="transcribed",
            transcribed_at=_now(),
            language=out["language"],
            duration_seconds=round(out["duration"], 3),
            model=model_name,
            outputs={k: out[k] for k in OUTPUT_FORMATS},
        )
        item.pop("error", None)
        _save_manifest(proj, manifest)
        ok += 1
        print(f"  -> {out['txt']}, {out['json']}, {out['md']}")

    print(f"done: {ok}/{len(pending)} transcribed")


def cmd_status(args):
    if not PROJECTS_DIR.exists():
        print("no projects yet — create one with: transcribe.py new <name>")
        return

    names = [args.name] if args.name else sorted(
        p.name for p in PROJECTS_DIR.iterdir()
        if (p / "project.json").exists()
    )
    if not names:
        print("no projects yet — create one with: transcribe.py new <name>")
        return

    for name in names:
        proj = _project_dir(name)
        manifest = _load_manifest(proj)
        items = manifest["items"]
        by_status: dict[str, int] = {}
        total_dur = 0.0
        for it in items:
            by_status[it["status"]] = by_status.get(it["status"], 0) + 1
            total_dur += it.get("duration_seconds") or 0.0

        print(f"\n■ {manifest['name']}  (model: {manifest.get('model', 'base')})")
        if manifest.get("description"):
            print(f"  {manifest['description']}")
        counts = ", ".join(f"{k}: {v}" for k, v in sorted(by_status.items())) or "empty"
        print(f"  {len(items)} item(s) — {counts} — {_fmt_duration(total_dur)} audio")
        for it in items:
            mark = {"transcribed": "✓", "pending": "·", "error": "✗",
                    "missing": "?"}.get(it["status"], "·")
            dur = _fmt_duration(it["duration_seconds"]) if it.get("duration_seconds") else "-"
            print(f"    {mark} {Path(it['media']).name}  [{it['status']}, {dur}]")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="transcribe.py",
        description="Vidcribe — organized local transcription with whisper.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="create a new project")
    p_new.add_argument("name")
    p_new.add_argument("-d", "--description", default="")
    p_new.add_argument("-m", "--model", default="base",
                       help="default whisper model for this project (default: base)")
    p_new.set_defaults(func=cmd_new)

    p_add = sub.add_parser("add", help="copy media file(s) into a project")
    p_add.add_argument("name")
    p_add.add_argument("files", nargs="+")
    p_add.add_argument("--force", action="store_true",
                       help="overwrite media already added")
    p_add.set_defaults(func=cmd_add)

    p_run = sub.add_parser("run", help="transcribe pending media in a project")
    p_run.add_argument("name")
    p_run.add_argument("-m", "--model", default=None,
                       help="override whisper model (tiny/base/small/medium/large)")
    p_run.add_argument("-l", "--language", default=None,
                       help="force language code (e.g. en); default: auto-detect")
    p_run.add_argument("--all", action="store_true",
                       help="re-transcribe everything, not just pending")
    p_run.add_argument("--only", nargs="+", metavar="FILE",
                       help="limit to specific media filename(s)")
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="show project(s) and item status")
    p_status.add_argument("name", nargs="?", default=None)
    p_status.set_defaults(func=cmd_status)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    PROJECTS_DIR.mkdir(exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
