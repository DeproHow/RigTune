"""History of scores + HTML report export."""
import html
import os
import time

from . import APP_NAME, APP_VERSION, checks, sysinfo
from .win import load_json, save_json

HISTORY = "history.json"
COLORS = {"good": "#22c55e", "warn": "#f59e0b", "bad": "#ef4444", "info": "#3b82f6", "skip": "#6b7280"}
LABELS = {"good": "OK", "warn": "Improve", "bad": "Problem", "info": "Info", "skip": "Skipped"}


def add_history(score, results):
    h = load_json(HISTORY, [])
    h.append({"time": time.strftime("%Y-%m-%d %H:%M"), "score": score,
              "bad": sum(r.status == "bad" for r in results),
              "warn": sum(r.status == "warn" for r in results)})
    save_json(HISTORY, h[-100:])
    return h


def history():
    return load_json(HISTORY, [])


def export_html(info, results, score, path=None):
    if path is None:
        docs = os.path.join(os.path.expanduser("~"), "Documents")
        os.makedirs(docs, exist_ok=True)
        path = os.path.join(docs, f"RigTune report {time.strftime('%Y-%m-%d %H-%M')}.html")
    g, color = checks.grade(score)
    e = html.escape
    rows = []
    for r in checks.ordered(results):
        steps = "".join(f"<li>{e(s)}</li>" for s in r.steps)
        links = " ".join(f'<a href="{e(u)}">{e(lbl)}</a>' for lbl, u in r.links)
        rows.append(f"""
        <div class="card" style="border-left:5px solid {COLORS[r.status]}">
          <div class="top"><span class="badge" style="background:{COLORS[r.status]}">{LABELS[r.status]}</span>
          <span class="cat">{e(r.category)}</span></div>
          <h3>{e(r.title)}</h3><p class="sum">{e(r.summary)}</p>
          {'<p>' + e(r.detail).replace(chr(10), '<br>') + '</p>' if r.detail else ''}
          {'<ol>' + steps + '</ol>' if steps else ''}{'<p>' + links + '</p>' if links else ''}
        </div>""")
    specs = "<br>".join(e(l) for l in sysinfo.summary_lines(info))
    doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{APP_NAME} report</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#0f1115;color:#e5e7eb;max-width:900px;margin:30px auto;padding:0 16px}}
.score{{font-size:64px;font-weight:800;color:{color}}} .grade{{font-size:22px;color:{color}}}
.card{{background:#181b22;border-radius:10px;padding:14px 18px;margin:12px 0}}
.badge{{color:#000;font-weight:700;padding:2px 8px;border-radius:6px;font-size:12px}}
.cat{{color:#9ca3af;font-size:12px;margin-left:8px}} h3{{margin:8px 0 4px}} .sum{{font-weight:600}}
a{{color:#60a5fa}} .specs{{background:#181b22;border-radius:10px;padding:14px 18px;font-family:Consolas,monospace;font-size:13px}}
</style></head><body>
<h1>{APP_NAME} PC report</h1><p>{time.strftime('%Y-%m-%d %H:%M')} - {APP_NAME} v{APP_VERSION}</p>
<div class="score">{score}/100</div><div class="grade">{e(g)}</div>
<h2>System</h2><div class="specs">{specs}</div>
<h2>Results</h2>{''.join(rows)}
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path
