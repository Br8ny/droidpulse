#!/usr/bin/env python3
"""Generate the droidpulse leaderboard from F-Droid + GitHub metadata.

No third-party dependencies. Reads F-Droid's public index, discovers GitHub
star counts via the Search API, scores momentum, and writes a README, a JSON
dataset and a self-contained static site into docs/ for GitHub Pages.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"

FDROID_INDEX = "https://f-droid.org/repo/index.xml"
SEARCH_QUERIES = (
    "topic:android stars:>100",
    "topic:android-app stars:>20",
    "topic:fdroid stars:>10",
    "android in:name,description stars:>300 language:Kotlin",
    "android in:name,description stars:>300 language:Java",
)
SEARCH_PAGES = 5

GH_RE = re.compile(r"github\.com[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.I)

CATEGORY_ORDER = (
    "Games", "Tools & System", "Privacy & Security", "Internet & Network",
    "Media & Music", "Reading & Writing", "Health & Fitness", "Finance",
    "Education", "Navigation & Travel", "Other",
)

CATEGORY_MAP = {
    "Games": "Games",
    "Action Game": "Games", "Adventure Game": "Games", "Arcade Game": "Games",
    "Board Game": "Games", "Card Game": "Games", "Casual Game": "Games",
    "Dice Game": "Games", "Educational Game": "Games", "Puzzle Game": "Games",
    "Racing Game": "Games", "Role Playing Game": "Games", "Simulation Game": "Games",
    "Sports Game": "Games", "Strategy Game": "Games", "Trivia Game": "Games",
    "Word Game": "Games", "Game Helper": "Games", "Emulator": "Games",
    "System": "Tools & System", "Development": "Tools & System",
    "File Manager": "Tools & System", "App Manager": "Tools & System",
    "App Store & Updater": "Tools & System", "Battery": "Tools & System",
    "Launcher": "Tools & System", "Keyboard & IME": "Tools & System",
    "Code & Forge": "Tools & System", "Clock": "Tools & System",
    "Alarm Clock": "Tools & System", "Calendar & Agenda": "Tools & System",
    "Theming": "Tools & System", "Widget": "Tools & System",
    "Security": "Privacy & Security", "Password & 2FA": "Privacy & Security",
    "File Encryption & Vault": "Privacy & Security", "Firewall": "Privacy & Security",
    "Internet": "Internet & Network", "Connectivity": "Internet & Network",
    "Browser": "Internet & Network", "Email": "Internet & Network",
    "DNS & Hosts": "Internet & Network", "Cloud Storage & File Sync": "Internet & Network",
    "Download": "Internet & Network", "File Transfer": "Internet & Network",
    "Cast": "Internet & Network", "Server": "Internet & Network",
    "Multimedia": "Media & Music", "Local Media Player": "Media & Music",
    "Music": "Media & Music", "Video": "Media & Music", "Camera": "Media & Music",
    "Gallery": "Media & Music", "Audiobook": "Media & Music",
    "Podcast": "Media & Music", "Draw": "Media & Music", "Photo & Image": "Media & Music",
    "Reading": "Reading & Writing", "Ebook Reader": "Reading & Writing",
    "Note": "Reading & Writing", "Writing": "Reading & Writing",
    "Bookmark": "Reading & Writing", "Dictionary": "Reading & Writing",
    "Sports & Health": "Health & Fitness", "Diet": "Health & Fitness",
    "Sleep": "Health & Fitness", "Digital Wellbeing": "Health & Fitness",
    "Finance Manager": "Finance", "Money": "Finance", "Business": "Finance",
    "Science & Education": "Education", "Education": "Education",
    "Reference": "Education", "Science": "Education",
    "Navigation": "Navigation & Travel", "Map": "Navigation & Travel",
    "Travel": "Navigation & Travel", "Transport": "Navigation & Travel",
}

CATEGORY_RULES = (
    ("game", "Games"), ("security", "Privacy & Security"),
    ("password", "Privacy & Security"), ("encrypt", "Privacy & Security"),
    ("privacy", "Privacy & Security"), ("vpn", "Privacy & Security"),
    ("internet", "Internet & Network"), ("network", "Internet & Network"),
    ("browser", "Internet & Network"), ("email", "Internet & Network"),
    ("sync", "Internet & Network"), ("download", "Internet & Network"),
    ("music", "Media & Music"), ("video", "Media & Music"),
    ("media", "Media & Music"), ("audio", "Media & Music"),
    ("camera", "Media & Music"), ("photo", "Media & Music"),
    ("read", "Reading & Writing"), ("note", "Reading & Writing"),
    ("write", "Reading & Writing"), ("book", "Reading & Writing"),
    ("health", "Health & Fitness"), ("sport", "Health & Fitness"),
    ("fitness", "Health & Fitness"), ("finance", "Finance"),
    ("money", "Finance"), ("educat", "Education"),
    ("science", "Education"), ("learn", "Education"),
    ("navigat", "Navigation & Travel"), ("map", "Navigation & Travel"),
    ("travel", "Navigation & Travel"),
    ("system", "Tools & System"), ("development", "Tools & System"),
    ("file", "Tools & System"), ("launcher", "Tools & System"),
    ("keyboard", "Tools & System"), ("tool", "Tools & System"),
)


def normalize_slug(text: str) -> str:
    """Return a lowercase owner/repo slug from a source-code URL."""
    match = GH_RE.search(text or "")
    if not match:
        return ""
    return f"{match.group(1)}/{match.group(2).removesuffix('.git')}".lower()


def categorize(raw: str) -> str:
    """Map a fine-grained F-Droid category into one of our buckets."""
    if not raw:
        return "Other"
    if raw in CATEGORY_MAP:
        return CATEGORY_MAP[raw]
    lowered = raw.lower()
    for needle, category in CATEGORY_RULES:
        if needle in lowered:
            return category
    return "Other"


def pulse_score(stars: int, pushed_at: str, last_updated: str, now: dt.datetime) -> float:
    """Activity-weighted popularity score (a momentum proxy, not a star delta)."""
    def days(iso: str) -> int:
        if not iso:
            return 365
        try:
            stamp = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).replace(tzinfo=None)
            return max(0, (now - stamp).days)
        except ValueError:
            return 365
    activity = max(0.0, 20.0 - days(pushed_at) / 3.0)
    freshness = max(0.0, 10.0 - days(last_updated) / 10.0)
    return round(10.0 * math.log2(stars + 1) + activity + freshness, 1)


def api_get(url: str, token: str, attempts: int = 3):
    """GET a GitHub API URL with a bearer token and simple backoff."""
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "droidpulse-generator",
        },
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429) and attempt < attempts - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"GitHub API {exc.code} for {url}") from exc
        except urllib.error.URLError as exc:
            if attempt < attempts - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"GitHub network error for {url}: {exc}") from exc
    raise RuntimeError("unreachable")


def fetch_fdroid() -> dict[str, dict]:
    """Parse F-Droid's index into apps keyed by GitHub slug."""
    with urllib.request.urlopen(FDROID_INDEX, timeout=90) as response:
        root = ET.fromstring(response.read())
    apps: dict[str, dict] = {}
    for entry in root.findall("application"):
        slug = normalize_slug(entry.findtext("source") or "")
        if not slug:
            continue
        apps[slug] = {
            "id": entry.findtext("id") or "",
            "name": entry.findtext("name") or "",
            "summary": entry.findtext("summary") or "",
            "category": categorize(entry.findtext("category") or ""),
            "raw_category": entry.findtext("category") or "",
            "license": entry.findtext("license") or "",
            "last_updated": entry.findtext("lastupdated") or "",
            "website": entry.findtext("web") or "",
        }
    return apps


def fetch_github(token: str) -> dict[str, dict]:
    """Discover popular Android repos through the GitHub Search API."""
    found: dict[str, dict] = {}
    for query in SEARCH_QUERIES:
        for page in range(1, SEARCH_PAGES + 1):
            params = urllib.parse.urlencode(
                {"q": query, "sort": "stars", "order": "desc", "per_page": 100, "page": page}
            )
            result = api_get(f"https://api.github.com/search/repositories?{params}", token)
            items = result.get("items", [])
            for item in items:
                found[item["full_name"].lower()] = {
                    "slug": item["full_name"],
                    "stars": int(item["stargazers_count"]),
                    "pushed_at": item.get("pushed_at") or "",
                    "description": item.get("description") or "",
                    "topics": item.get("topics") or [],
                }
            print(f"  {query} page {page}: {len(items)} repos ({len(found)} total)")
            if len(items) < 100:
                break
            time.sleep(1)
    return found


def load_extra() -> list[str]:
    """Optional manually curated slugs for apps the automation misses."""
    path = DATA_DIR / "extra-apps.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [normalize_slug(item) if "/" in item else item.lower() for item in payload.get("repos", [])]


def build_apps(now: dt.datetime) -> tuple[list[dict], int]:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to query GitHub")
    fdroid = fetch_fdroid()
    print(f"F-Droid: {len(fdroid)} GitHub-linked apps")
    github = fetch_github(token)
    print(f"GitHub: {len(github)} candidate repos")

    # Optional extra slugs get looked up directly so they can appear too.
    for slug in load_extra():
        if slug not in github:
            try:
                item = api_get(f"https://api.github.com/repos/{slug}", token)
                github[slug] = {
                    "slug": item["full_name"], "stars": int(item["stargazers_count"]),
                    "pushed_at": item.get("pushed_at") or "",
                    "description": item.get("description") or "", "topics": item.get("topics") or [],
                }
            except RuntimeError as exc:
                print(f"  warning: extra repo {slug} skipped ({exc})")

    apps: list[dict] = []
    for slug, info in github.items():
        meta = fdroid.get(slug)
        if not meta or info["stars"] < 10:
            continue
        owner, repo = slug.split("/", 1)
        apps.append({
            "name": meta["name"],
            "summary": meta["summary"] or info["description"],
            "category": meta["category"],
            "raw_category": meta["raw_category"],
            "owner": owner,
            "repo": repo,
            "slug": slug,
            "repo_url": f"https://github.com/{owner}/{repo}",
            "release_url": f"https://github.com/{owner}/{repo}/releases/latest",
            "stars": info["stars"],
            "pushed_at": info["pushed_at"],
            "last_updated": meta["last_updated"],
            "license": meta["license"],
            "website": meta["website"],
            "score": pulse_score(info["stars"], info["pushed_at"], meta["last_updated"], now),
        })
    apps.sort(key=lambda a: (-a["score"], -a["stars"], a["name"].lower()))
    return apps, len(fdroid)


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def write_dataset(apps: list[dict], fdroid_count: int, now: dt.datetime) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": now.isoformat(timespec="seconds") + "Z",
        "methodology": (
            "Pulse score = 10*log2(stars+1) + GitHub push recency bonus + F-Droid update recency "
            "bonus. It is an activity-weighted popularity proxy, not an exact star-delta count."
        ),
        "sources": ["F-Droid public index", "GitHub Search API"],
        "fdroid_github_apps": fdroid_count,
        "apps": apps,
    }
    (DATA_DIR / "apps.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def write_readme(apps: list[dict], payload: dict, now: dt.datetime) -> None:
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# droidpulse",
        "",
        "![droidpulse launch card](docs/launch.png)",
        "",
        "**Trending open-source Android apps, ranked by momentum — one click to the official release.**",
        "",
        "Auto-generated daily from the [F-Droid index](https://f-droid.org) and GitHub. "
        "No APKs are hosted here: every entry redirects to the project's own latest release page.",
        "",
        f"_Last updated {stamp} · {len(apps)} ranked apps · "
        f"{payload['fdroid_github_apps']} F-Droid apps with GitHub source_",
        "",
        "## Overall top 25",
        "",
        "| # | App | Category | Stars | Pulse | Release |",
        "|---:|---|---|---:|---:|---|",
    ]
    for rank, app in enumerate(apps[:25], 1):
        lines.append(
            f"| {rank} | [{esc(app['name'])}]({esc(app['repo_url'])}) | {esc(app['category'])} "
            f"| {app['stars']:,} | {app['score']} | [Download]({esc(app['release_url'])}) |"
        )
    lines.extend(["", "## By category", ""])
    for category in CATEGORY_ORDER:
        group = [a for a in apps if a["category"] == category][:10]
        if not group:
            continue
        lines.extend([f"### {category}", "", "| App | Stars | Pulse | Release |", "|---|---:|---:|---|"])
        for app in group:
            lines.append(
                f"| [{esc(app['name'])}]({esc(app['repo_url'])}) | {app['stars']:,} "
                f"| {app['score']} | [Download]({esc(app['release_url'])}) |"
            )
        lines.append("")
    lines.extend([
        "## How ranking works",
        "",
        payload["methodology"],
        "",
        "Apps must appear in F-Droid with a GitHub source URL and be discovered by the GitHub "
        "Search API with at least 10 stars. Discovery is automated; `data/extra-apps.json` can "
        "hold slugs that need a manual nudge.",
        "",
        "## Limitations",
        "",
        "- The pulse score is a momentum proxy, not an exact count of stars gained this week.",
        "- GitHub Search API results are capped and query-dependent, so coverage is not exhaustive.",
        "- Release links point to GitHub's `releases/latest`; projects without a tagged release "
        "will land on their releases page instead.",
        "- F-Droid metadata can lag behind upstream repositories.",
        "",
        "## Site",
        "",
        "The browsable leaderboard is published at "
        "https://br8ny.github.io/droidpulse/ and refreshes daily via GitHub Actions.",
        "",
        "## License",
        "",
        "MIT — see [LICENSE](LICENSE). App names and marks belong to their respective owners.",
    ])
    (ROOT / "README.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_site(apps: list[dict], payload: dict, now: dt.datetime) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    counts = {c: sum(1 for a in apps if a["category"] == c) for c in CATEGORY_ORDER}
    chips = "".join(
        f'<button class="chip" data-cat="{esc(c)}">{esc(c)} <span>{counts[c]}</span></button>'
        for c in CATEGORY_ORDER if counts[c]
    )
    data_json = json.dumps(apps, ensure_ascii=False).replace("</", "<\\/")
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>droidpulse — trending open-source Android apps</title>
<meta name="description" content="Trending open-source Android apps ranked by momentum, with one-click links to official releases.">
<style>
:root{{--bg:#0d0f14;--panel:#161a22;--line:#2a3040;--text:#eef1f7;--muted:#9aa3b5;--accent:#7c5cff;--accent2:#00d4b1}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
a{{color:inherit;text-decoration:none}}.wrap{{max-width:960px;margin:auto;padding:28px 18px 60px}}
header h1{{font-size:40px;margin:0 0 4px;letter-spacing:-1px}}header h1 b{{color:var(--accent)}}
.tagline{{color:var(--muted);font-size:17px;margin:0 0 6px}}
.meta{{color:var(--muted);font-size:13px;margin-bottom:22px}}
.stats{{display:flex;gap:14px;flex-wrap:wrap;margin:20px 0}}
.stat{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 18px}}
.stat b{{display:block;font-size:22px}}.stat span{{color:var(--muted);font-size:12px}}
.tools{{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}}
input{{flex:1;min-width:200px;background:var(--panel);border:1px solid var(--line);color:var(--text);border-radius:10px;padding:11px 14px;font-size:14px}}
.chip{{background:var(--panel);color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:8px 13px;cursor:pointer;font-size:13px}}
.chip:hover{{border-color:var(--accent)}}.chip.active{{background:var(--accent);color:#fff;border-color:var(--accent)}}
.chip span{{opacity:.7;margin-left:4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:8px}}
.card:hover{{border-color:var(--accent)}}.card h3{{margin:0;font-size:16px;overflow-wrap:anywhere}}
.card p{{margin:0;color:var(--muted);font-size:13px;flex:1}}
.badges{{display:flex;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--muted)}}
.pill{{background:#22283a;border-radius:999px;padding:2px 8px}}
.pill.hot{{background:rgba(0,212,177,.15);color:var(--accent2)}}
.release{{display:inline-block;text-align:center;background:var(--accent);color:#fff;border-radius:9px;padding:9px;font-weight:600;font-size:13px}}
.release:hover{{filter:brightness(1.15)}}
footer{{color:var(--muted);font-size:12px;margin-top:36px;border-top:1px solid var(--line);padding-top:16px}}
</style>
</head>
<body><div class="wrap">
<header>
<h1><b>droid</b>pulse</h1>
<p class="tagline">Trending open-source Android apps, ranked by momentum. One click to the official release.</p>
<p class="meta">Auto-generated from F-Droid + GitHub · updated {esc(now.strftime('%Y-%m-%d %H:%M UTC'))} · no APKs hosted here</p>
</header>
<div class="stats">
<div class="stat"><b>{len(apps)}</b><span>ranked apps</span></div>
<div class="stat"><b>{esc(f"{sum(a['stars'] for a in apps):,}")}</b><span>combined stars</span></div>
<div class="stat"><b>{sum(1 for c in CATEGORY_ORDER if counts[c])}</b><span>categories</span></div>
</div>
<div class="tools"><input id="q" placeholder="Search apps, authors or categories..."></div>
<div class="tools" id="chips"><button class="chip active" data-cat="All">All <span>{len(apps)}</span></button>{chips}</div>
<div class="grid" id="grid"></div>
<footer>Ranked by an activity-weighted pulse score (a momentum proxy, not an exact star delta).
App names belong to their owners. <a href="https://github.com/Br8ny/droidpulse">Source &amp; methodology</a>.</footer>
</div>
<script id="app-data" type="application/json">{data_json}</script>
<script>
const apps=JSON.parse(document.getElementById('app-data').textContent);
const grid=document.getElementById('grid'),q=document.getElementById('q');
let cat='All',term='';
function render(){{
  const list=apps.filter(a=>(cat==='All'||a.category===cat)&&
    (a.name+' '+a.summary+' '+a.slug+' '+a.category).toLowerCase().includes(term)).slice(0,120);
  grid.innerHTML=list.map(a=>`<article class="card">
    <h3><a href="${{a.repo_url}}" target="_blank" rel="noopener">${{escapeHtml(a.name)}}</a></h3>
    <p>${{escapeHtml(a.summary)}}</p>
    <div class="badges"><span class="pill">${{escapeHtml(a.category)}}</span>
      <span class="pill">★ ${{a.stars.toLocaleString()}}</span>
      <span class="pill hot">pulse ${{a.score}}</span></div>
    <a class="release" href="${{a.release_url}}" target="_blank" rel="noopener">Get latest release ↗</a>
  </article>`).join('')||'<p>No apps match that filter.</p>';
}}
function escapeHtml(s){{return String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]))}}
document.getElementById('chips').addEventListener('click',e=>{{
  const b=e.target.closest('.chip'); if(!b)return;
  cat=b.dataset.cat;
  document.querySelectorAll('.chip').forEach(c=>c.classList.toggle('active',c===b));
  render();
}});
q.addEventListener('input',()=>{{term=q.value.trim().toLowerCase();render();}});
render();
</script>
</body></html>
"""
    (DOCS_DIR / "index.html").write_text(html_doc, encoding="utf-8")
    (DOCS_DIR / "data.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> None:
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    apps, fdroid_count = build_apps(now)
    if not apps:
        raise RuntimeError("no apps matched — refusing to publish an empty leaderboard")
    payload = write_dataset(apps, fdroid_count, now)
    write_readme(apps, payload, now)
    write_site(apps, payload, now)
    print(f"Wrote {len(apps)} apps to README.md, data/apps.json and docs/")


if __name__ == "__main__":
    main()
