"""
Local web form at http://127.0.0.1:8080

WHY THIS FILE EXISTS (vs the old ui.py):
The old form made the user type an exact OSM tag value themselves ("Use
an exact OSM value such as restaurant, clinic, hotel") AND never computed
a bbox -- so it always hit the buggy no-tags OSM query path. This version:
  - shows a dropdown of plain-English niches (from niche_map.json)
  - always geocodes to a bbox before querying (via main.py's pipeline)
  - shows the run's console output (including tile counts, quota
    warnings, and the final "N new leads added" line) once it finishes
"""

import json
import subprocess
import sys
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

from .sources import load_niche_map

JOB = {"status": "idle", "progress": 0, "message": "Ready"}


def _niche_options_html() -> str:
    niches = sorted(load_niche_map().keys())
    return "".join(f'<option value="{n}">{n.replace("_", " ")}</option>' for n in niches)


def _page_html() -> str:
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>LeadBot Console</title>
<style>body{{margin:0;background:#101b1d;color:#eef4e8;font:16px Georgia,serif}}
main{{max-width:900px;margin:50px auto;padding:36px;background:#172729;border:1px solid #3d625b;border-radius:18px;box-shadow:0 20px 60px #081011}}
.eyebrow{{color:#d6ae59;letter-spacing:3px;text-transform:uppercase;font:12px Arial}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
label{{display:block;color:#a9c2b7;font:13px Arial;margin:18px 0 7px}}
input,select{{width:100%;box-sizing:border-box;padding:13px;background:#0e181a;color:#fff;border:1px solid #40645b;border-radius:8px;font-size:15px}}
button{{margin-top:25px;padding:14px 22px;background:#d6ae59;border:0;border-radius:8px;font-weight:bold;cursor:pointer}}
.hint{{color:#9bb3a8;font:13px Arial;line-height:1.5}}
.result{{margin-top:25px;padding:15px;background:#0e181a;border-left:3px solid #d6ae59;font-family:Arial;white-space:pre-wrap;max-height:300px;overflow:auto}}
</style></head>
<body><main>
<div class="eyebrow">Lead operations / local console</div>
<h1>Find businesses in your territory.</h1>
<p class="hint">Pick a country, region (city or state), and niche. LeadBot geocodes the region, tiles it if it's large, queries OpenStreetMap, checks each business's own website, and adds only new leads to your Google Sheet.</p>
<div class="result" id="status">Ready · 0%</div>
<form method="post">
<div class="grid">
<div><label>Country</label><input name="country" value="United States" required></div>
<div><label>Region (city or state)</label><input name="region" value="Texas" required></div>
</div>
<label>Niche</label>
<select name="niche">{_niche_options_html()}</select>
<button type="submit">Run lead collection</button>
</form>
<div class="hint" style="margin-top:20px">Don't see your niche? Add it to <b>leadbot/niche_map.json</b> and restart this page.</div>
<script>setInterval(()=>fetch('/status').then(r=>r.json()).then(x=>document.getElementById('status').textContent=x.message+' · '+x.progress+'%'),1000)</script>
</main></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def _send_html(self, body: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        if self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(JOB).encode())
            return
        self._send_html(_page_html())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = parse_qs(self.rfile.read(length).decode())
        try:
            base_config = json.loads(Path("config.json").read_text(encoding="utf-8")) if Path("config.json").exists() else {}
            base_config["queries"] = [{
                "country": data["country"][0],
                "region": data["region"][0],
                "niche": data["niche"][0],
            }]
            Path("config.json").write_text(json.dumps(base_config, indent=2), encoding="utf-8")

            venv_python = Path(".venv/Scripts/python.exe")
            if not venv_python.exists():
                venv_python = Path(".venv/bin/python")  # macOS/Linux venv layout
            runner = str(venv_python) if venv_python.exists() else sys.executable

            def run_job():
                JOB.update(status="running", progress=10, message="Collecting businesses...")
                result = subprocess.run(
                    [runner, "-m", "leadbot.main", "--config", "config.json"],
                    capture_output=True, text=True, timeout=600, cwd=str(Path.cwd()),
                )
                output = (result.stdout or "") + (result.stderr or "")
                if result.returncode == 0:
                    JOB.update(status="complete", progress=100, message=output.strip()[-800:] or "Collection complete")
                else:
                    JOB.update(status="error", progress=100, message=output.strip()[-800:] or "Collection failed")

            threading.Thread(target=run_job, daemon=True).start()
            self._send_html(_page_html())
        except Exception as e:
            self._send_html(_page_html().replace(
                '<div class="result" id="status">Ready · 0%</div>',
                f'<div class="result" id="status">Could not start: {e}</div>',
            ))


if __name__ == "__main__":
    print("LeadBot UI: http://127.0.0.1:8080")
    HTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
