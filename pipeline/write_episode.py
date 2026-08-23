#!/usr/bin/env python3
"""Turn the fetched Notion digest into an episode script + quiz JSON.

Usage:
    python write_episode.py <digest.json> <YYYY-MM-DD> <script_out.txt> <quiz_out.json>

Env:
    ANTHROPIC_API_KEY   required
    EPISODE_MODEL       optional, defaults to claude-opus-5

Exit codes: 0 ok, 1 usage, 2 API failure, 4 unparseable/short response.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

MODEL = os.environ.get("EPISODE_MODEL", "claude-opus-5")
KEY = os.environ.get("ANTHROPIC_API_KEY", "")
HERE = os.path.dirname(os.path.abspath(__file__))
MIN_WORDS, MAX_WORDS = 2400, 4200


def spoken_words(script: str) -> int:
    return len(re.sub(r"^(ANDREW|AVA):", "", script, flags=re.M).split())


def call_api(system: str, user: str, max_tokens: int = 16000) -> str:
    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                body = json.loads(r.read())
            usage = body.get("usage", {})
            print(f"  tokens in={usage.get('input_tokens')} out={usage.get('output_tokens')}",
                  file=sys.stderr)
            return "".join(b.get("text", "") for b in body.get("content", []))
        except urllib.error.HTTPError as e:
            last = f"{e.code}: {e.read()[:400].decode(errors='replace')}"
            if e.code in (429, 500, 502, 503, 529) and attempt < 2:
                wait = 20 * (attempt + 1)
                print(f"  retry in {wait}s ({last[:80]})", file=sys.stderr)
                time.sleep(wait)
                continue
            break
        except Exception as e:  # noqa: BLE001 - surface anything as a build failure
            last = repr(e)
            if attempt < 2:
                time.sleep(20 * (attempt + 1))
                continue
    raise RuntimeError(f"Anthropic API failed: {last}")


def extract(tag: str, text: str):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
    return m.group(1).strip() if m else None


def main():
    if len(sys.argv) != 5:
        print(__doc__, file=sys.stderr)
        return 1
    if not KEY:
        print("ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2

    digest_path, date_s, script_out, quiz_out = sys.argv[1:5]
    date = dt.date.fromisoformat(date_s)
    with open(digest_path, encoding="utf-8") as f:
        digest = json.load(f)

    system = open(os.path.join(HERE, "prompt.md"), encoding="utf-8").read()

    parts = [f"Today is {date.strftime('%A, %B %-d, %Y')}.\n",
             "# TODAY'S DIGEST\n", digest["today"]]
    for i, p in enumerate(digest.get("prior", []), start=1):
        parts.append(f"\n\n# PRIOR DIGEST (T-{i}) — for cross-temporal threads only\n{p}")
    parts.append(
        "\n\n---\nWrite today's episode now. Return only the <script> and <quiz> "
        "blocks. Remember the 2,800-3,300 spoken-word ceiling and count before "
        "you finish."
    )
    user = "\n".join(parts)
    print(f"prompt: {len(user):,} chars, model={MODEL}", file=sys.stderr)

    raw = call_api(system, user)
    script, quiz_raw = extract("script", raw), extract("quiz", raw)

    if not script or not quiz_raw:
        open("/tmp/raw_response.txt", "w", encoding="utf-8").write(raw)
        print("Could not find <script>/<quiz> tags; raw saved to /tmp/raw_response.txt",
              file=sys.stderr)
        return 4

    words = spoken_words(script)
    print(f"script: {words} spoken words (~{words / 153:.1f} min)", file=sys.stderr)
    if not MIN_WORDS <= words <= MAX_WORDS:
        print(f"WARNING: {words} words is outside the sane band "
              f"{MIN_WORDS}-{MAX_WORDS}", file=sys.stderr)
    if words < 1200:
        print("Script is implausibly short; treating as a failure", file=sys.stderr)
        return 4
    if not re.search(r"^ANDREW:", script, re.M) or not re.search(r"^AVA:", script, re.M):
        print("Script is missing ANDREW/AVA speaker tags", file=sys.stderr)
        return 4

    quiz_raw = re.sub(r"^```(?:json)?|```$", "", quiz_raw.strip(), flags=re.M).strip()
    try:
        quiz = json.loads(quiz_raw)
    except json.JSONDecodeError as e:
        open("/tmp/raw_quiz.txt", "w", encoding="utf-8").write(quiz_raw)
        print(f"Quiz JSON did not parse ({e}); raw saved to /tmp/raw_quiz.txt",
              file=sys.stderr)
        return 4

    clean = []
    for q in quiz:
        if not all(k in q for k in ("section", "q", "keys", "answer")):
            continue
        keys = [k for k in str(q["keys"]).split(";") if k.strip()]
        if not keys:
            continue
        clean.append({
            "section": q["section"],
            "q": q["q"],
            "keys": ";".join(keys),
            "threshold": max(1, min(int(q.get("threshold", 1)), len(keys))),
            "answer": q["answer"],
        })
    if len(clean) < 12:
        print(f"Only {len(clean)} usable quiz questions", file=sys.stderr)
        return 4

    open(script_out, "w", encoding="utf-8").write(script + "\n")
    json.dump(clean, open(quiz_out, "w", encoding="utf-8"))
    print(f"wrote {script_out} and {quiz_out} ({len(clean)} questions)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
