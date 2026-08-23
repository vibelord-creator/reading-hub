# Daily Reading — automated pipeline

The episode is built and published by GitHub Actions. No local machine is
involved once the three secrets below are set.

## What runs, and when

`.github/workflows/daily-podcast.yml` fires on cron at **09:10 UTC** daily
(~05:10 ET in summer, ~04:10 ET in winter) and can be triggered by hand from the
Actions tab with an optional date and a `force` rebuild flag.

```
Notion digest  ->  Anthropic API  ->  edge-tts  ->  quiz HTML  ->  feed/index  ->  push
fetch_digest      write_episode      build_dialogue  build_quiz    generate_site
```

Publishing uses the workflow's built-in `GITHUB_TOKEN`. **No personal access
token is needed anymore** — the old `.credentials` file is only required if you
still run the pipeline manually from a laptop.

## Required secrets

Set under *Settings -> Secrets and variables -> Actions*:

| Name | What it is |
|---|---|
| `ANTHROPIC_API_KEY` | From console.anthropic.com. Pays for script + quiz generation. |
| `NOTION_TOKEN` | An **internal integration** token, not the OAuth connector. |

Optional repository *variable* `EPISODE_MODEL` overrides the default
`claude-opus-5` (set it to a Sonnet model to cut cost roughly 5x).

### The Notion step you have to do by hand

Create an internal integration at notion.so/my-integrations, copy its secret,
then **share the "Daily News Digest" parent page with that integration** in
Notion (Share -> Add connections). The runner has no other way in. This is the
same manual re-share that the Reading List DB (`9ddad44b`) has been waiting on
since 2026-08-01 — if that one is still broken, this one will fail the same way.

## Repository layout

```
pipeline/fetch_digest.py     Notion REST -> flattened digest text
pipeline/write_episode.py    digest -> Script_DATE.txt + quiz.json
pipeline/prompt.md           persona, format rules, length ceiling, quiz spec
pipeline/build_dialogue.py   two-voice edge-tts (Andrew + Ava), resumable
pipeline/build_quiz.py       quiz.json -> Quiz_DATE.html
pipeline/quiz_template.html  canonical CSS + grading JS, reused verbatim
generate_site.py             feed.xml, index.html, quiz.html
scripts/Script_*.txt         episode transcripts
Daily_Reading_*.mp3          published audio
Quiz_*.html                  published quizzes
```

## Why old MP3s no longer need to exist locally

`generate_site.py` used to glob the source directory and `stat()` every episode,
purely to fill the RSS `<enclosure length="...">` attribute. It now reads those
byte lengths back out of the previously published `feed.xml` and only stats
files actually present on disk. Verified 2026-08-22: building with a single
MP3 present produces byte-identical `feed.xml` and `index.html` to building with
all 49.

Consequence: both the workflow and any manual run can use a blobless sparse
checkout that skips `Daily_Reading_*.mp3`, so a build clones a few megabytes
instead of ~350 MB.

## Failure behaviour

Any failed step opens a GitHub issue titled `[Daily Reading] Build failed <date>`
with a link to the run log. Nothing is pushed on failure, so the feed always
holds the last good episode and Apple Podcasts never sees a broken entry.

The audio is verified before publishing: minimum file size, minimum duration,
and a words-per-second check that catches silently truncated edge-tts turns
(anything above 3.5 w/s is truncation, not fast speech).

## Known risks

1. **edge-tts from CI IPs.** Microsoft's endpoint is undocumented and has been
   known to rate-limit or block datacenter address ranges. This is the single
   most likely cause of a recurring failure, and it cannot be tested without a
   real run. If it proves unreliable, the fallback is a paid TTS API
   (ElevenLabs / OpenAI / Google) — `build_dialogue.py` isolates the synthesis
   call, so swapping it is a contained change.
2. **Cron drift.** GitHub's scheduled triggers are best-effort and frequently
   run 5–30 minutes late. Do not treat the publish time as precise.
3. **Repository growth.** Each episode adds ~8 MB. At roughly 260 MB/year the
   repo will get unwieldy within a couple of years. The eventual fix is to move
   audio to GitHub Releases or object storage, which changes enclosure URLs and
   should be done deliberately rather than under pressure.
4. **Digest timing.** The workflow reads whatever Notion page exists at 09:10
   UTC. If the upstream reading-list job has not yet run, the build fails
   cleanly rather than publishing a thin episode.
