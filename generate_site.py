#!/usr/bin/env python3
"""
Generate feed.xml (podcast RSS) + index.html (landing page) from the set of
Daily_Reading_YYYY-MM-DD.mp3 and Quiz_YYYY-MM-DD.html files present.

Usage:
    python generate_site.py <source_dir> <output_dir> <base_url>
"""
import os
import re
import sys
import html
import datetime
from email.utils import format_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

EPISODE_RE = re.compile(r"^Daily_Reading_(\d{4}-\d{2}-\d{2})(_v\d+)?\.mp3$")
QUIZ_RE = re.compile(r"^Quiz_(\d{4}-\d{2}-\d{2})\.html$")


ENCLOSURE_RE = re.compile(
    r'<enclosure\s+url="[^"]*/(Daily_Reading_(\d{4}-\d{2}-\d{2})(?:_v\d+)?\.mp3)"\s+length="(\d+)"'
)


def sizes_from_feed(feed_path: Path):
    """Recover {date: (mp3_name, size)} from a previously published feed.xml.

    Lets the generator run without a local archive of every episode: the RSS
    <enclosure length=...> attribute is the only thing old MP3s were ever
    needed for. Missing or malformed feed is not an error -- we just fall back
    to whatever is on disk.
    """
    if not feed_path or not feed_path.exists():
        return {}
    try:
        text = feed_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return {d: (name, int(size)) for name, d, size in ENCLOSURE_RE.findall(text)}


def collect_episodes(src: Path, feed_path: Path = None, extra_dirs=()):
    """Union of episodes found on disk and episodes recorded in the prior feed.

    A locally present MP3 always wins (it is authoritative and may be new or
    rebuilt); the feed only supplies episodes whose files are not on disk.
    """
    by_date = {}
    for p in src.glob("Daily_Reading_*.mp3"):
        m = EPISODE_RE.match(p.name)
        if not m:
            continue
        d = m.group(1)
        existing = by_date.get(d)
        if existing is None or len(p.name) > len(existing.name):
            by_date[d] = p

    # Quizzes may live in the source dir, the output clone, or both.
    quizzes = {}
    for folder in (src, *extra_dirs):
        if not folder or not Path(folder).is_dir():
            continue
        for p in Path(folder).glob("Quiz_*.html"):
            if m := QUIZ_RE.match(p.name):
                quizzes[m.group(1)] = p.name

    cached = sizes_from_feed(feed_path)

    eps = []
    for d in sorted(set(by_date) | set(cached), reverse=True):
        if d in by_date:
            mp3 = by_date[d]
            name, size = mp3.name, mp3.stat().st_size
        else:
            name, size = cached[d]
        eps.append({
            "date": d,
            "mp3_name": name,
            "size": size,
            "quiz_name": quizzes.get(d),
        })
    return eps


def est_duration_sec(size_bytes):
    return int(size_bytes / 6000)


def fmt_duration(sec):
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def build_feed(eps, base_url, meta):
    tz = ZoneInfo("America/New_York")
    now_rfc = format_datetime(datetime.datetime.now(tz))
    cover_url = f"{base_url}/cover.jpg"

    items_xml = []
    for ep in eps:
        pub_dt = datetime.datetime.fromisoformat(ep["date"] + "T05:30:00").replace(tzinfo=tz)
        pub_rfc = format_datetime(pub_dt)
        dur = fmt_duration(est_duration_sec(ep["size"]))
        mp3_url = f"{base_url}/{ep['mp3_name']}"
        title = f"Daily Reading - {ep['date']}"
        desc_parts = [f"Daily digest for {ep['date']}."]
        if ep["quiz_name"]:
            desc_parts.append(f"Quiz: {base_url}/{ep['quiz_name']}")
        desc = " ".join(desc_parts)
        items_xml.append(
            f"    <item>\n"
            f"      <title>{html.escape(title)}</title>\n"
            f"      <link>{html.escape((base_url + '/' + ep['quiz_name']) if ep['quiz_name'] else (base_url + '/'))}</link>\n"
            f"      <description>{html.escape(desc)}</description>\n"
            f"      <pubDate>{pub_rfc}</pubDate>\n"
            f"      <guid isPermaLink=\"false\">{ep['date']}-{ep['mp3_name']}</guid>\n"
            f"      <enclosure url=\"{html.escape(mp3_url)}\" length=\"{ep['size']}\" type=\"audio/mpeg\"/>\n"
            f"      <itunes:duration>{dur}</itunes:duration>\n"
            f"      <itunes:author>{html.escape(meta['author'])}</itunes:author>\n"
            f"      <itunes:summary>{html.escape(desc)}</itunes:summary>\n"
            f"      <itunes:image href=\"{html.escape(cover_url)}\"/>\n"
            f"      <itunes:explicit>false</itunes:explicit>\n"
            f"    </item>"
        )

    return (
        f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        f"<rss version=\"2.0\" xmlns:itunes=\"http://www.itunes.com/dtds/podcast-1.0.dtd\" xmlns:content=\"http://purl.org/rss/1.0/modules/content/\">\n"
        f"  <channel>\n"
        f"    <title>{html.escape(meta['title'])}</title>\n"
        f"    <link>{base_url}/</link>\n"
        f"    <language>en-us</language>\n"
        f"    <description>{html.escape(meta['desc'])}</description>\n"
        f"    <lastBuildDate>{now_rfc}</lastBuildDate>\n"
        f"    <itunes:author>{html.escape(meta['author'])}</itunes:author>\n"
        f"    <itunes:summary>{html.escape(meta['desc'])}</itunes:summary>\n"
        f"    <itunes:type>episodic</itunes:type>\n"
        f"    <itunes:owner>\n"
        f"      <itunes:name>{html.escape(meta['author'])}</itunes:name>\n"
        f"      <itunes:email>{html.escape(meta['email'])}</itunes:email>\n"
        f"    </itunes:owner>\n"
        f"    <itunes:image href=\"{html.escape(cover_url)}\"/>\n"
        f"    <image>\n"
        f"      <url>{html.escape(cover_url)}</url>\n"
        f"      <title>{html.escape(meta['title'])}</title>\n"
        f"      <link>{base_url}/</link>\n"
        f"    </image>\n"
        f"    <itunes:explicit>false</itunes:explicit>\n"
        f"    <itunes:category text=\"News\">\n"
        f"      <itunes:category text=\"Daily News\"/>\n"
        f"    </itunes:category>\n"
        f"    <itunes:category text=\"Business\">\n"
        f"      <itunes:category text=\"Entrepreneurship\"/>\n"
        f"    </itunes:category>\n"
        + "\n".join(items_xml) + "\n"
        f"  </channel>\n"
        f"</rss>\n"
    )


def build_index(eps, base_url, meta):
    rows = []
    for ep in eps:
        dur = fmt_duration(est_duration_sec(ep["size"]))
        mp3_link = f'<a href="{ep["mp3_name"]}">MP3</a>'
        quiz_link = f'<a href="{ep["quiz_name"]}">Quiz</a>' if ep["quiz_name"] else "<span class='muted'>-</span>"
        rows.append(
            f"      <tr><td>{ep['date']}</td><td>{dur}</td><td>{mp3_link}</td><td>{quiz_link}</td></tr>"
        )

    today_quiz = eps[0]["quiz_name"] if (eps and eps[0]["quiz_name"]) else None
    today_mp3 = eps[0]["mp3_name"] if eps else None
    now_str = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M %Z")
    today_block = ""
    if today_mp3:
        today_block = f'<div class="cta">Today: <a href="{today_mp3}">Listen</a>'
        if today_quiz:
            today_block += f' &middot; <a href="{today_quiz}">Take the quiz</a>'
        today_block += "</div>"

    css = (
        ":root{color-scheme:dark;}"
        "body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:#0d1117;color:#e6edf3;max-width:720px;margin:0 auto;padding:24px;}"
        "h1{font-size:22px;margin-top:0;}"
        "p.sub{color:#8b949e;margin-top:-8px;}"
        ".cta{background:#1f2937;border-radius:12px;padding:16px;margin:16px 0;}"
        ".cta a{color:#60a5fa;text-decoration:none;font-weight:600;}"
        ".cta a:hover{text-decoration:underline;}"
        "table{width:100%;border-collapse:collapse;margin-top:16px;font-size:15px;}"
        "th,td{text-align:left;padding:10px 8px;border-bottom:1px solid #21262d;}"
        "th{color:#8b949e;font-weight:500;font-size:13px;}"
        "a{color:#60a5fa;text-decoration:none;} a:hover{text-decoration:underline;}"
        ".muted{color:#484f58;}"
        "footer{margin-top:32px;font-size:13px;color:#8b949e;}"
        "code{background:#161b22;padding:2px 6px;border-radius:4px;font-size:13px;}"
    )

    return (
        f"<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"/>"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>"
        f"<title>{html.escape(meta['title'])}</title><style>{css}</style></head><body>"
        f"<h1>{html.escape(meta['title'])}</h1>"
        f"<p class=\"sub\">{html.escape(meta['desc'])}</p>"
        f"{today_block}"
        f"<div class=\"cta\">Apple Podcasts: copy <code>{base_url}/feed.xml</code> into Library &rarr; ... &rarr; Add a Show by URL</div>"
        f"<h2 style=\"font-size:16px;margin-top:32px;color:#8b949e;\">Archive</h2>"
        f"<table><thead><tr><th>Date</th><th>Length</th><th>Audio</th><th>Quiz</th></tr></thead><tbody>"
        + "\n".join(rows) +
        f"</tbody></table><footer>Built nightly. Last updated {now_str}.</footer></body></html>\n"
    )


def main():
    if len(sys.argv) != 4:
        print("Usage: python generate_site.py <source_dir> <output_dir> <base_url>", file=sys.stderr)
        return 1
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    base_url = sys.argv[3].rstrip("/")
    if not src.is_dir():
        print(f"source dir not found: {src}", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)

    meta = {
        "title": os.environ.get("PODCAST_TITLE", "Anurag Daily Reading"),
        "desc": os.environ.get("PODCAST_DESC", "Daily audio digest."),
        "author": os.environ.get("PODCAST_AUTHOR", "Anurag Maken"),
        "email": os.environ.get("PODCAST_EMAIL", "anuragmaken@gmail.com"),
    }

    # The output dir is normally a clone of the live site, so its existing
    # feed.xml carries the byte length of every past episode. That is the only
    # reason old MP3s ever had to be kept locally. Read it before overwriting.
    prior_feed = out / "feed.xml"
    eps = collect_episodes(src, feed_path=prior_feed, extra_dirs=(out,))
    on_disk = sum(1 for e in eps if (src / e["mp3_name"]).exists())
    print(f"Found {len(eps)} episodes ({on_disk} local, {len(eps) - on_disk} from prior feed)")

    (out / "feed.xml").write_text(build_feed(eps, base_url, meta))
    (out / "index.html").write_text(build_index(eps, base_url, meta))

    if eps and eps[0]["quiz_name"]:
        for folder in (src, out):
            latest_quiz = folder / eps[0]["quiz_name"]
            if latest_quiz.exists():
                (out / "quiz.html").write_text(latest_quiz.read_text())
                break
        else:
            print(f"WARNING: quiz {eps[0]['quiz_name']} not found", file=sys.stderr)

    print(f"Wrote feed.xml, index.html, quiz.html to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
