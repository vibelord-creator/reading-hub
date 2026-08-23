#!/usr/bin/env python3
"""Fetch today's Notion reading digest (and the prior two days) as plain text.

Requires a Notion *internal integration* token in NOTION_TOKEN -- the OAuth
connector used inside Cowork will not work from a CI runner. The integration
must have been explicitly shared on the "Daily News Digest" parent page.

Usage:  python fetch_digest.py <YYYY-MM-DD> <out.json>

Writes {"today": "...", "prior": ["...", "..."], "dates": {...}} and exits 0.
Exits 3 if today's digest cannot be found (caller decides whether to fall back).
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
TOKEN = os.environ.get("NOTION_TOKEN", "")


def _req(path, payload=None, method="POST"):
    url = f"{API}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Notion-Version": VERSION,
        "Content-Type": "application/json",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(r, timeout=45) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode(errors="replace")
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f"Notion {method} {path} -> {e.code}: {body}") from e
        except urllib.error.URLError:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def search_pages(query):
    res = _req("/search", {
        "query": query,
        "filter": {"value": "page", "property": "object"},
        "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        "page_size": 25,
    })
    out = []
    for r in res.get("results", []):
        title = ""
        for prop in (r.get("properties") or {}).values():
            if prop.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in prop.get("title", []))
                break
        out.append({"id": r["id"], "title": title, "edited": r.get("last_edited_time", "")})
    return out


def rich(arr):
    return "".join(t.get("plain_text", "") for t in (arr or []))


def blocks_to_text(block_id, depth=0, budget=None):
    """Flatten a Notion page to markdown-ish text, following child blocks."""
    if budget is None:
        budget = [140]  # max API calls, guards against runaway nesting
    if depth > 3 or budget[0] <= 0:
        return ""
    lines, cursor = [], None
    while True:
        budget[0] -= 1
        if budget[0] <= 0:
            break
        q = f"/blocks/{block_id}/children?page_size=100"
        if cursor:
            q += f"&start_cursor={cursor}"
        res = _req(q, method="GET")
        for b in res.get("results", []):
            t = b.get("type", "")
            body = b.get(t, {}) or {}
            txt = rich(body.get("rich_text"))
            pad = "  " * depth
            if t.startswith("heading_"):
                lines.append(f"\n{'#' * int(t[-1])} {txt}")
            elif t in ("bulleted_list_item", "numbered_list_item"):
                lines.append(f"{pad}- {txt}")
            elif t == "to_do":
                lines.append(f"{pad}- [ ] {txt}")
            elif t == "toggle":
                lines.append(f"{pad}> {txt}")
            elif t == "quote":
                lines.append(f"{pad}> {txt}")
            elif t == "code":
                lines.append(f"{pad}    {txt}")
            elif t == "divider":
                lines.append("---")
            elif txt:
                lines.append(f"{pad}{txt}")
            if b.get("has_children") and t != "child_page":
                sub = blocks_to_text(b["id"], depth + 1, budget)
                if sub:
                    lines.append(sub)
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return "\n".join(lines)


def find_for_date(d: dt.date):
    """Match the reading page for a date across the naming variants used so far."""
    human = d.strftime("%B %-d, %Y") if os.name != "nt" else d.strftime("%B %d, %Y")
    weekday = d.strftime("%A")
    short = d.strftime("%b %-d, %Y") if os.name != "nt" else d.strftime("%b %d, %Y")
    needles = [
        f"today's reads — {weekday.lower()}, {human.lower()}",
        f"today's reads — {human.lower()}",
        f"{weekday[:3].lower()} {short.lower()}",
        d.isoformat(),
    ]
    seen, cands = set(), []
    for q in (f"Today's Reads {human}", f"Daily News Digest {short}", d.isoformat()):
        for p in search_pages(q):
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            cands.append(p)
    # Prefer the richer "Today's Reads" page, then any page whose title matches.
    def score(p):
        t = p["title"].lower()
        s = 0
        if any(n in t for n in needles):
            s += 10
        if "today's reads" in t:
            s += 5
        if "digest" in t:
            s += 3
        return s
    cands = [c for c in cands if score(c) > 0]
    cands.sort(key=score, reverse=True)
    return cands[0] if cands else None


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 1
    if not TOKEN:
        print("NOTION_TOKEN is not set", file=sys.stderr)
        return 2
    today = dt.date.fromisoformat(sys.argv[1])
    out = {"today": None, "prior": [], "dates": {}}

    page = find_for_date(today)
    if not page:
        print(f"No digest page found for {today}", file=sys.stderr)
        return 3
    print(f"today  -> {page['title']}", file=sys.stderr)
    out["today"] = blocks_to_text(page["id"])
    out["dates"]["today"] = page["title"]

    for back in (1, 2):
        d = today - dt.timedelta(days=back)
        p = find_for_date(d)
        if not p:
            continue
        print(f"prior  -> {p['title']}", file=sys.stderr)
        txt = blocks_to_text(p["id"])
        out["prior"].append(txt[:24000])
        out["dates"][d.isoformat()] = p["title"]

    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(out, f)
    print(f"wrote {sys.argv[2]}: today={len(out['today'])} chars, "
          f"prior={[len(p) for p in out['prior']]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
