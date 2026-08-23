#!/usr/bin/env python3
"""
Daily Reading Podcast — two-voice dialogue TTS pipeline.

Script format: paragraphs prefixed with a speaker tag:
    ANDREW: text...
    AVA: text...
A line containing only "---" inserts a 1.2s pause (section break).
Untagged paragraphs inherit the previous speaker.

Resumable: per-turn MP3s are cached in a work dir and skipped if present.

Usage:
    python build_dialogue.py <script_path> <output_mp3_path>

Exit codes: 0 success, 1 input error, 2 TTS failure, 3 concat failure.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

VOICES = {
    "ANDREW": "en-US-AndrewMultilingualNeural",
    "AVA": "en-US-AvaMultilingualNeural",
}
RATE = "-10%"
MAX_RETRIES = 3
RETRY_DELAY_SEC = 5
PAUSE_SEC = 1.2


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def parse_turns(text: str):
    """Return list of ("PAUSE", None) or (speaker, text) turns.
    Consecutive same-speaker paragraphs are merged."""
    turns = []
    speaker = "ANDREW"
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if para == "---":
            turns.append(("PAUSE", None))
            continue
        m = re.match(r"^(ANDREW|AVA):\s*(.*)$", para, re.DOTALL)
        if m:
            speaker = m.group(1)
            body = m.group(2).strip()
        else:
            body = para
        if turns and turns[-1][0] == speaker:
            turns[-1] = (speaker, turns[-1][1] + "\n\n" + body)
        else:
            turns.append((speaker, body))
    return turns


def make_silence(path: Path) -> bool:
    if path.exists() and path.stat().st_size > 200:
        return True
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", str(PAUSE_SEC), "-c:a", "libmp3lame", "-b:a", "48k", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    return r.returncode == 0 and path.exists()


def synthesize(text_path: Path, mp3_path: Path, voice: str) -> bool:
    if mp3_path.exists() and mp3_path.stat().st_size > 1000:
        log(f"  skip {mp3_path.name} (cached)")
        return True
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = subprocess.run(
                ["edge-tts", "--voice", voice, f"--rate={RATE}",
                 "--file", str(text_path), "--write-media", str(mp3_path)],
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode == 0 and mp3_path.exists() and mp3_path.stat().st_size > 1000:
                log(f"  ok {mp3_path.name} ({mp3_path.stat().st_size} bytes)")
                return True
            log(f"  attempt {attempt} failed: rc={r.returncode} {r.stderr[:200]}")
        except subprocess.TimeoutExpired:
            log(f"  attempt {attempt} timed out")
        except Exception as e:
            log(f"  attempt {attempt} exception: {e}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY_SEC * attempt)
    return False


def concat(paths, final_path: Path) -> bool:
    list_file = final_path.parent / f".{final_path.stem}_concat.txt"
    with open(list_file, "w") as f:
        for p in paths:
            f.write(f"file '{p.resolve()}'\n")
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-c", "copy", str(final_path)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            log(f"ffmpeg concat failed: {r.stderr[:400]}")
            return False
        return True
    finally:
        list_file.unlink(missing_ok=True)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 1
    script_path, output_path = Path(sys.argv[1]), Path(sys.argv[2])
    if not script_path.exists():
        log(f"Script not found: {script_path}")
        return 1

    turns = parse_turns(script_path.read_text())
    n_words = sum(len(t.split()) for s, t in turns if s != "PAUSE")
    log(f"{n_words} words, {len(turns)} turns")

    work_dir = output_path.parent / f".{output_path.stem}_turns"
    work_dir.mkdir(exist_ok=True)

    silence = work_dir / "silence.mp3"
    if not make_silence(silence):
        log("FAILED to build silence gap")
        return 2

    pieces = []
    for i, (speaker, body) in enumerate(turns):
        if speaker == "PAUSE":
            pieces.append(silence)
            continue
        txt = work_dir / f"turn_{i:03d}_{speaker}.txt"
        mp3 = work_dir / f"turn_{i:03d}_{speaker}.mp3"
        txt.write_text(body)
        log(f"turn {i} [{speaker}] {len(body.split())} words")
        if not synthesize(txt, mp3, VOICES[speaker]):
            log(f"FAILED turn {i} after {MAX_RETRIES} attempts")
            return 2
        pieces.append(mp3)

    log(f"Concatenating {len(pieces)} pieces -> {output_path}")
    if not concat(pieces, output_path):
        return 3
    size = output_path.stat().st_size
    log(f"DONE {output_path.name}: {size:,} bytes (~{size/6000/60:.1f} min)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
