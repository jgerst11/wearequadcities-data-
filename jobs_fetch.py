"""
jobs_fetch.py — QC Jobs pilot (10/15/26).

Pulls current openings from approved Quad Cities employer sources and writes jobs.json.
Every job links to the employer's own posting; we never collect applications or résumés.
Jobs a source stops listing simply drop out on the next run (no stale postings).

Sources: John Deere (SuccessFactors RSS), Workday public job feeds (Hy-Vee, KONE),
GovernmentJobs/NEOGOV agency listings (City of Davenport, Scott County, City of Rock Island).
Add employers to SOURCES; nothing else needs to change.
"""
import json, re, html, hashlib, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).parent / "jobs.json"
UA = "Mozilla/5.0 (compatible; WeAreQuadCities-jobs/1.0; +https://www.wearequadcities.com)"
QC_TOWNS = ["Davenport", "Bettendorf", "Moline", "East Moline", "Rock Island", "Milan", "Silvis", "Eldridge",
            "Coal Valley", "Le Claire", "LeClaire", "Blue Grass", "Colona", "Carbon Cliff", "Port Byron", "Walcott", "Scott County"]

SOURCES = [
    {"employer": "John Deere", "type": "rss", "careers": "https://jobs.deere.com/",
     "urls": [f"https://jobs.deere.com/services/rss/job/?locale=en_US&keywords={k}" for k in ("Moline", "Davenport", "Silvis", "Milan")]},
    {"employer": "Hy-Vee", "type": "workday", "careers": "https://hyvee.wd1.myworkdayjobs.com/HyVeeCareers",
     "tenant": "hyvee", "dc": "wd1", "site": "HyVeeCareers", "searches": ["Davenport", "Bettendorf", "Moline", "Rock Island", "East Moline", "Milan", "Eldridge"]},
    {"employer": "KONE", "type": "workday", "careers": "https://kone.wd3.myworkdayjobs.com/Careers",
     "tenant": "kone", "dc": "wd3", "site": "Careers", "searches": ["Moline"]},
    {"employer": "City of Davenport", "type": "neogov", "agency": "davenport", "town": "Davenport", "careers": "https://www.governmentjobs.com/careers/davenport"},
    {"employer": "Scott County", "type": "neogov", "agency": "scottco", "town": "Scott County", "careers": "https://www.governmentjobs.com/careers/scottco"},
    {"employer": "City of Rock Island", "type": "neogov", "agency": "rockisland", "town": "Rock Island", "careers": "https://www.governmentjobs.com/careers/rockisland"},
]


def get(url, data=None, headers=None, timeout=40):
    h = {"User-Agent": UA, **(headers or {})}
    body = json.dumps(data).encode() if data is not None else None
    if body is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def town_of(loc):
    """The QC town a location is in, or "" if it's elsewhere. Reads the town right before the state
    ("..., Bettendorf, IA"), so street names like "W Rock Island St, Knoxville, IA" don't count (10/16/26)."""
    loc = loc or ""
    m = re.findall(r"([A-Za-z .']+?),\s*(?:IA|IL|Iowa|Illinois)\b", loc)
    if m:
        town = m[-1].strip()
        for t in QC_TOWNS:
            if town.lower() == t.lower():
                return "Le Claire" if t == "LeClaire" else t
        return ""
    for t in sorted(QC_TOWNS, key=len, reverse=True):   # no state given (e.g. "Moline IL Main Office")
        if re.search(r"\b" + re.escape(t) + r"\b", loc, re.I):
            return "Le Claire" if t == "LeClaire" else t
    return ""


def jid(*parts):
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]


def fetch_rss(src):
    out = {}
    for u in src["urls"]:
        root = ET.fromstring(get(u))
        for it in root.findall(".//item"):
            title, link = it.findtext("title") or "", it.findtext("link") or ""
            m = re.match(r"(.*) \((.*)\)$", title)
            name, loc = (m.group(1), m.group(2)) if m else (title, "")
            loc = re.sub(r",\s*US.*$", "", loc)
            if not town_of(loc):
                continue
            posted = it.findtext("pubDate") or ""
            try:
                posted = datetime.strptime(posted[:16], "%a, %d %b %Y").date().isoformat()
            except ValueError:
                posted = ""
            out[link] = {"title": name.strip(), "location": loc.strip(), "url": link, "posted": posted}
    return list(out.values())


def fetch_workday(src):
    base = f"https://{src['tenant']}.{src['dc']}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{src['tenant']}/{src['site']}/jobs"
    out = {}
    for q in src["searches"]:
        offset = 0
        while offset < 200:
            j = json.loads(get(api, {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": q}))
            posts = j.get("jobPostings", [])
            for p in posts:
                loc = p.get("locationsText", "")
                multi = re.match(r"\d+ Locations", loc)
                if not town_of(loc) and not multi:   # outside the QC (e.g. Knoxville, IA): skip
                    continue
                url = f"{base}/{src['site']}{p.get('externalPath', '')}"
                out[url] = {"title": p.get("title", "").strip(), "location": f"{q} + other locations" if multi else loc,
                            "url": url, "posted": p.get("postedOn", "")}
            offset += 20
            if offset >= j.get("total", 0) or not posts:
                break
    return list(out.values())


def fetch_neogov(src):
    page = get(f"https://www.governmentjobs.com/careers/home/index?agency={src['agency']}&sort=PostingDate&isDescendingSort=true",
               headers={"X-Requested-With": "XMLHttpRequest"}).decode("utf-8", "replace")
    out = []
    for block in re.split(r'<li class="list-item" data-job-id="\d+">', page)[1:]:
        a = re.search(r'class="item-details-link"[^>]*href="([^"]+)"[^>]*>([^<]+)<', block)
        if not a:
            continue
        meta = re.search(r'<ul class="list-meta">(.*?)</ul>', block, re.S)
        metas = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m))).strip()
                 for m in re.findall(r"<li[^>]*>(.*?)</li>", meta.group(1) if meta else "", re.S)]
        loc = metas[0] if metas else ""
        detail = metas[1] if len(metas) > 1 else ""
        out.append({"title": html.unescape(a.group(2)).strip(), "location": loc,
                    "url": "https://www.governmentjobs.com" + a.group(1), "posted": "", "detail": detail.replace(" - ", " · ", 1).replace(" - ", "–")})
    return out


FETCH = {"rss": fetch_rss, "workday": fetch_workday, "neogov": fetch_neogov}


def main():
    now = datetime.now(timezone.utc)
    jobs, report = [], []
    for src in SOURCES:
        try:
            got = FETCH[src["type"]](src)
            ok = True
        except Exception as e:  # one broken source never empties the others
            got, ok = [], False
            print(f"  {src['employer']}: FAILED {e}")
        for j in got:
            if src.get("town") and not town_of(j["location"]):   # e.g. NEOGOV gives only "IL 61201"
                j["location"] = src["town"] + (", IL" if "IL" in j["location"] else ", IA" if "IA" in j["location"] else "")
            j.update(id=jid(src["employer"], j["url"]), employer=src["employer"], city=town_of(j["location"]) or src.get("town", ""),
                     source=src["type"], collected=now.date().isoformat())
            jobs.append(j)
        report.append({"employer": src["employer"], "careers": src["careers"], "count": len(got), "ok": ok})
        print(f"  {src['employer']}: {len(got)} jobs")
    # keep previous jobs for a source that failed this run, so a temporary outage doesn't blank it
    if OUT.exists():
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        failed = {r["employer"] for r in report if not r["ok"]}
        jobs += [j for j in prev.get("jobs", []) if j.get("employer") in failed]
    jobs.sort(key=lambda j: (j["employer"], j["title"]))
    OUT.write_text(json.dumps({"generated": now.isoformat(timespec="seconds"), "sources": report, "jobs": jobs},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {len(jobs)} jobs from {sum(r['ok'] for r in report)}/{len(report)} sources -> {OUT.name}")


if __name__ == "__main__":
    main()
