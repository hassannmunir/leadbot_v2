"""HTML templates for the local LeadBot web console."""

from ..discovery.sources import load_niche_map


def niche_options_html() -> str:
    niches = sorted(load_niche_map().keys())
    return "".join(f'<option value="{n}">{n.replace("_", " ")}</option>' for n in niches)


def page_html() -> str:
  return f"""<!doctype html><html><head><meta charset="utf-8"><title>LeadBot Console</title>
<style>body{{margin:0;background:#101b1d;color:#eef4e8;font:16px Georgia,serif}}
main{{max-width:900px;margin:50px auto;padding:36px;background:#172729;border:1px solid #3d625b;border-radius:18px;box-shadow:0 20px 60px #081011}}
.eyebrow{{color:#d6ae59;letter-spacing:3px;text-transform:uppercase;font:12px Arial}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
label{{display:block;color:#a9c2b7;font:13px Arial;margin:18px 0 7px}}
input,select{{width:100%;box-sizing:border-box;padding:13px;background:#0e181a;color:#fff;border:1px solid #40645b;border-radius:8px;font-size:15px}}
button{{margin-top:25px;padding:14px 22px;background:#d6ae59;border:0;border-radius:8px;font-weight:bold;cursor:pointer}}
.hint{{color:#9bb3a8;font:13px Arial;line-height:1.5}}
.progress-wrap{{background:#0e181a;border-radius:6px;overflow:hidden;height:8px;margin-top:12px}}
.progress-bar{{background:#d6ae59;height:100%;width:0%;transition:width .3s}}
.result{{margin-top:15px;padding:15px;background:#0e181a;border-left:3px solid #d6ae59;font-family:Arial;font-size:13px;white-space:pre-wrap;max-height:260px;overflow:auto}}
</style></head>
<body><main>
<div class="eyebrow">Lead operations / local console</div>
<h1>Find businesses in your territory.</h1>
<p class="hint">Pick a country, region (city or state), and niche. LeadBot geocodes the region, tiles it if it's large, queries OpenStreetMap, checks each business's own website, and adds only new leads to your Google Sheet.</p>
<div id="status-line" style="font-family:Arial">Ready &middot; 0%</div>
<div class="progress-wrap"><div class="progress-bar" id="progress-bar"></div></div>
<div class="result" id="log"></div>
<form method="post">
<div class="grid">
<div><label>Country</label><input name="country" value="United States" required></div>
<div><label>Region (city or state)</label><input name="region" value="Texas" required></div>
</div>
<label>Niche</label>
<select name="niche">{niche_options_html()}</select>
<button type="submit">Run lead collection</button>
</form>
<div class="hint" style="margin-top:20px">Don't see your niche? Add it to <b>leadbot/discovery/niche_map.json</b> and restart this page.</div>
<script>
setInterval(() => fetch('/status').then(r => r.json()).then(x => {{
  document.getElementById('status-line').textContent = x.message + ' \\u00b7 ' + x.progress + '%';
  document.getElementById('progress-bar').style.width = x.progress + '%';
  document.getElementById('log').textContent = x.log.join('\\n');
  document.getElementById('log').scrollTop = document.getElementById('log').scrollHeight;
}}), 1000)
</script>
</main></body></html>"""
