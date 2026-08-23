#!/usr/bin/env python3
"""Render quiz.json into Quiz_YYYY-MM-DD.html.

Reuses the CSS and grading JavaScript from the canonical template verbatim, so
the styling and grader behaviour can never drift from the original.

Usage:
    python build_quiz.py <quiz.json> <YYYY-MM-DD> <template.html> <out.html>
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 5:
        print(__doc__, file=sys.stderr)
        return 1
    quiz_path, date_s, template_path, out_path = (Path(p) for p in sys.argv[1:5])
    date = dt.date.fromisoformat(str(date_s))
    quiz = json.loads(quiz_path.read_text(encoding="utf-8"))
    tpl = template_path.read_text(encoding="utf-8")

    style = re.search(r"<style>.*?</style>", tpl, re.S).group(0)
    js_tail = re.search(r"(function normalize\(str\).*?)\n</script>", tpl, re.S).group(1)

    # Preserve first-appearance order of sections.
    order, grouped = [], {}
    for q in quiz:
        s = q["section"]
        if s not in grouped:
            grouped[s] = []
            order.append(s)
        grouped[s].append(q)

    n, idx, body, answers = len(quiz), 0, [], {}
    for section in order:
        body.append(f"  <h2>{section}</h2>\n")
        for q in grouped[section]:
            idx += 1
            answers[idx] = q["answer"]
            body.append(
                f'  <div class="q" data-id="{idx}" data-keys="{q["keys"]}" '
                f'data-threshold="{q["threshold"]}">\n'
                f'    <div class="q-text"><span class="q-num">{idx}.</span> {q["q"]}</div>\n'
                f'    <textarea placeholder="Your answer"></textarea>\n'
                f'    <div class="feedback"></div>\n'
                f'  </div>\n\n'
            )

    b1, b2, b3 = int(n * 0.78), int(n * 0.56), int(n * 0.35)
    answers_js = ",\n  ".join(f"{k}: {json.dumps(v)}" for k, v in answers.items())
    pretty = date.strftime("%A, %B %-d, %Y")

    # Retarget the template's hardcoded 23-question buckets onto today's count.
    js_tail = re.sub(r"if \(correct >= \d+\)", f"if (correct >= {b1})", js_tail, count=1)
    js_tail = re.sub(r"\} else if \(correct >= 13\)", f"}} else if (correct >= {b2})", js_tail)
    js_tail = re.sub(r"\} else if \(correct >= 8\)", f"}} else if (correct >= {b3})", js_tail)
    js_tail = (js_tail
               .replace("Bucket: 18–23 —", f"Bucket: {b1}–{n} —")
               .replace("Bucket: 13–17 —", f"Bucket: {b2}–{b1 - 1} —")
               .replace("Bucket: 8–12 —", f"Bucket: {b3}–{b2 - 1} —")
               .replace("Bucket: Below 8 —", f"Bucket: Below {b3} —")
               .replace("re-listen to the cross-article connections (Section C).",
                        "re-listen to the cross-temporal connections (Section C).")
               .replace("Quiz again Tuesday.", "Quiz again tomorrow."))

    out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Daily Reading Quiz — {date.strftime('%B %-d, %Y')}</title>
{style}
</head>
<body>
<div class="container">
  <header>
    <h1>Daily Reading Comprehension Quiz</h1>
    <div class="sub">{pretty} — Episode Daily_Reading_{date_s}.mp3</div>
    <div class="meta">
      <span>{n} questions</span>
      <span>{len(order)} sections</span>
      <span>Suggested time: {max(8, n // 2)}–{max(10, n // 2 + 3)} min</span>
    </div>
  </header>

  <p style="color: var(--muted); font-size: .92rem;">
    Type what you remember. Click <strong>Grade</strong> when done. Feedback is keyword-based:
    <span style="color: var(--green);">green</span> = hit the key terms,
    <span style="color: var(--amber);">amber</span> = partial,
    <span style="color: var(--red);">red</span> = missed. You'll see the full answer either way.
  </p>

{''.join(body)}  <div class="score-panel" id="scorePanel">
    <div class="score-big"><span id="scoreCorrect">0</span> / {n}</div>
    <div class="score-detail" id="scoreDetail"></div>
    <div class="bucket" id="scoreBucket"></div>
    <div class="score-detail" style="margin-top:.5rem;">Partial credit: <span id="scorePartial">0</span></div>
  </div>

  <div class="actions">
    <button id="gradeBtn">Grade my quiz</button>
    <button id="resetBtn" class="secondary">Reset</button>
    <span class="score-detail" id="progressText" style="margin-left:auto;"></span>
  </div>

  <div class="scoring-guide">
    <h3>Self-scoring buckets</h3>
    <ul>
      <li><strong>{b1}–{n} correct:</strong> You internalized the material. You could brief a partner tomorrow morning.</li>
      <li><strong>{b2}–{b1 - 1} correct:</strong> Solid recall but the cross-temporal connections need another pass.</li>
      <li><strong>{b3}–{b2 - 1} correct:</strong> Skim the script transcript before re-listening.</li>
      <li><strong>Below {b3}:</strong> Re-listen at 0.9x with the script open.</li>
    </ul>
  </div>
</div>

<script>
// Full answers keyed by question id
const ANSWERS = {{
  {answers_js}
}};

{js_tail}
</script>
</body>
</html>
"""
    out_path.write_text(out, encoding="utf-8")
    print(f"wrote {out_path} ({len(out):,} bytes, {n} questions, {len(order)} sections)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
