#!/usr/bin/env python3
"""Read a pre-written episode from a Notion "Podcast Script" page.

This is the claude.ai handoff path: a cloud scheduled task writes the script and
quiz into Notion, and this pulls them out so the runner never has to call the
Anthropic API. If the page is absent or malformed we exit 3 and the caller falls
back to generating the episode itself.

Expected page shape (see cloud-podcast-task-prompt.md):

    ## SCRIPT
    ANDREW: ...
    AVA: ...
    ---
    ## QUIZ
    <code block containing a JSON array>

Usage:
    python fetch_script.py <YYYY-MM-DD> <script_out.txt> <quiz_out.json>

Exit codes: 0 ok, 1 usage, 2 no token, 3 page missing/unusable.
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_digest import _req, rich, search_pages  # noqa: E402

MIN_WORDS = 1200


def find_script_page(date: dt.date):
    iso = date.isoformat()
    pretty = date.strftime("%B %-d, %Y")
    seen, best = set(), None
    for q in (f"Podcast Script {iso}", f"Podcast Script {pretty}", f"Podcast Script"):
        for p in search_pages(q):
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            t = p["title"].lower()
            if "podcast script" not in t:
                continue
            if iso not in t and pretty.lower() not in t:
                continue
            # Most recently edited match wins.
            if best is None or p["edited"] > best["edited"]:
                best = p
    return best


def top_level_blocks(page_id):
    out, cursor = [], None
    while True:
        q = f"/blocks/{page_id}/children?page_size=100"
        if cursor:
            q += f"&start_cursor={cursor}"
        res = _req(q, method="GET")
        out.extend(res.get("results", []))
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return out


def parse(blocks):
    """Split the page into script paragraphs and the quiz JSON code block."""
    script_parts, quiz_json, in_quiz = [], None, False
    for b in blocks:
        t = b.get("type", "")
        body = b.get(t, {}) or {}
        # Notion splits long text across multiple rich_text runs; rich() rejoins
        # them, which is what keeps a >2000 char JSON code block intact.
        txt = rich(body.get("rich_text"))

        if t == "code":
            if quiz_json is None:
                quiz_json = txt
            continue
        if t.startswith("heading_"):
            if re.search(r"\bquiz\b", txt, re.I):
                in_quiz = True
                continue
            if re.search(r"\bscript\b", txt, re.I):
                in_quiz = False
                continue
            continue
        if in_quiz:
            continue
        if t == "divider":
            script_parts.append("---")
        elif t == "paragraph" and txt.strip():
            script_parts.append(txt.strip())

    # Collapse the leading/trailing blank noise Notion tends to add.
    script = "\n\n".join(p for p in script_parts if p)
    script = re.sub(r"\n{3,}", "\n\n", script).strip()
    return script, quiz_json


def main():
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        return 1
    if not os.environ.get("NOTION_TOKEN"):
        print("NOTION_TOKEN is not set", file=sys.stderr)
        return 2

    date = dt.date.fromisoformat(sys.argv[1])
    script_out, quiz_out = sys.argv[2], sys.argv[3]

    page = find_script_page(date)
    if not page:
        print(f"No 'Podcast Script' page for {date}", file=sys.stderr)
        return 3
    print(f"found -> {page['title']}", file=sys.stderr)

    script, quiz_raw = parse(top_level_blocks(page["id"]))

    words = len(re.sub(r"^(ANDREW|AVA):", "", script, flags=re.M).split())
    if words < MIN_WORDS:
        print(f"Script only {words} words; treating page as unusable", file=sys.stderr)
        return 3
    if not re.search(r"^ANDREW:", script, re.M) or not re.search(r"^AVA:", script, re.M):
        print("Script has no ANDREW/AVA speaker tags", file=sys.stderr)
        return 3
    if not quiz_raw:
        print("No quiz code block on the page", file=sys.stderr)
        return 3

    quiz_raw = re.sub(r"^```(?:json)?|```$", "", quiz_raw.strip(), flags=re.M).strip()
    try:
        quiz = json.loads(quiz_raw)
    except json.JSONDecodeError as e:
        print(f"Quiz JSON did not parse: {e}", file=sys.stderr)
        return 3

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
        return 3

    open(script_out, "w", encoding="utf-8").write(script + "\n")
    json.dump(clean, open(quiz_out, "w", encoding="utf-8"))
    print(f"script: {words} spoken words (~{words / 153:.1f} min), "
          f"quiz: {len(clean)} questions", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
