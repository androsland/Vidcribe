# Vidcribe

An organized, local-first transcription system. Drop in videos or audio,
group them into **projects**, and get back clean transcripts in three formats —
plain text, structured JSON (with timestamps), and a Markdown document.

Transcription runs **locally** with [openai-whisper](https://github.com/openai/whisper),
so nothing is uploaded anywhere.

## File structure

```
Vidcribe/
├── transcribe.py          # the CLI (new / add / run / status)
├── setup.sh               # one-time installer (ffmpeg + whisper)
├── requirements.txt
└── projects/
    └── <project-name>/
        ├── media/         # source audio/video  (git-ignored — large/binary)
        ├── transcripts/   # outputs, one set per media file
        │   ├── <file>.txt   # clean plain-text transcript
        │   ├── <file>.json  # segments + timestamps + metadata
        │   └── <file>.md    # readable doc: metadata, summary slot, timestamps
        └── project.json   # manifest: every item, its status & metadata
```

Media files themselves are **not** committed to git (they're large and binary).
The folder layout, manifests, and transcripts are versioned.

## Setup (once)

```bash
./setup.sh                  # installs ffmpeg + creates .venv with whisper
source .venv/bin/activate
```

`setup.sh` installs `ffmpeg` via your system package manager and the Python
deps into a local `.venv`.

## Usage

```bash
# 1. Create a project (optionally set a default model)
./transcribe.py new client-interviews -d "Q2 user interviews" -m small

# 2. Add one or more media files (they're copied into the project)
./transcribe.py add client-interviews ~/Downloads/interview-01.mp4 ~/Downloads/interview-02.m4a

# 3. Transcribe everything pending
./transcribe.py run client-interviews

# 4. Check status anytime
./transcribe.py status               # all projects
./transcribe.py status client-interviews
```

### Handy flags

| Command | Flag | Meaning |
|---------|------|---------|
| `run`   | `-m, --model` | Override whisper model: `tiny`, `base`, `small`, `medium`, `large` |
| `run`   | `-l, --language` | Force a language code (e.g. `en`); default is auto-detect |
| `run`   | `--all` | Re-transcribe everything, not just pending items |
| `run`   | `--only FILE...` | Transcribe specific filename(s) only |
| `add`   | `--force` | Re-copy media that's already in the project |

### Whisper models

Larger = more accurate but slower and heavier. `base` is a good default;
use `small`/`medium` for tougher audio, `tiny` for quick drafts.

## How to give me files

Since I'm working in a remote container, the easiest paths are:

- **Commit small media** into a project's `media/` folder on this branch (note:
  it's git-ignored by default — remove the ignore rule or use `git add -f`), or
- **Share a link** (cloud storage / direct URL) and I'll fetch and add it, or
- Tell me where files already live in the container and I'll `add` + `run` them.

## Supported formats

Audio: `mp3, wav, m4a, flac, ogg, opus, aac, wma`
Video: `mp4, mov, mkv, webm, avi, m4v, flv, wmv`

The `.md` file includes a **Summary** section left blank by design — fill it in
yourself, or ask me to generate a summary from the transcript.
