"""
events_fetch.py
Fetches Quad Cities events from:
  1. Visit QC (rss.app RSS feed)
  2. Eventbrite (HTML scrape, JSON-LD + __SERVER_DATA__)
Writes combined events.json for GitHub Pages.
"""

import json, re, hashlib, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

VISITQC_RSS_URL = "https://rss.app/feeds/0uJSRhvj2HVUSPBw.xml"
EVENTBRITE_URL  = "https://www.eventbrite.com/d/united-states--iowa/quad-cities/"
OUT_FILE = Path(__file__).parent / "events.json"
MAX_DAYS = 90

MONTH_MAP = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}

QC_CITIES = {"davenport","bettendorf","rock island","moline","east moline","milan","silvis","carbon cliff","hampton","coal valley","port byron","muscatine"}

def parse_title(title):
    m = re.match(r'^([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})\s+(\d{1,2}:\d{2})\s+(AM|PM)\s+(.+?)(?:\s*Read\s*More)?$', title.strip(), re.IGNORECASE)
    if not m: return title.strip().replace("Read More","").strip(), ""
    mon_str,day,year,time_str,ampm,name = m.groups()
    mon = MONTH_MAP.get(mon_str.lower(), 0)
    if not mon: return name.strip(), ""
    try:
        dt = datetime.strptime(f"{year}-{mon:02d}-{int(day):02d} {time_str} {ampm}", "%Y-%m-%d %I:%M %p")
        return name.strip(), dt.strftime("%Y-%m-%dT%H:%M:00")
    except ValueError:
        return name.strip(), ""

def fetch_url(url, html=False):
    headers = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36","Accept":"text/html,application/xhtml+xml,*/*;q=0.9","Accept-Language":"en-US,en;q=0.9"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return raw.decode("utf-8", errors="replace") if html else raw
    except Exception as e:
        print(f"  ERROR: {e}"); return None

def is_future(start_str):
    now = datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    try:
        s = start_str[:10] if len(start_str) > 10 else start_str
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        return 0 <= (dt - now).days <= MAX_DAYS
    except: return False

# ── Visit QC ──────────────────────────────────────────────────────────────────

def fetch_visitqc():
    xml = fetch_url(VISITQC_RSS_URL)
    if not xml: return []
    root = ET.fromstring(xml)
    events = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link  = (item.findtext("link")  or "").strip()
        guid  = (item.findtext("guid")  or link or title).strip()
        name, start = parse_title(title)
        if not name or name.lower() in ("read more","") or not start or not is_future(start): continue
        events.append({"id":"vqc_"+hashlib.md5(guid.encode()).hexdigest()[:12],"name":name,"start":start[:10],"end":"","venue":"","address":"","city":"Quad Cities","state":"","category":"Events","description":"","url":link,"image":"","is_free":False,"source":"visitquadcities.com"})
    return events

# ── Eventbrite ────────────────────────────────────────────────────────────────

def parse_eb_json_ld(e):
    loc = e.get("location", {}); addr = loc.get("address", {})
    image = e.get("image","")
    if isinstance(image, list): image = image[0] if image else ""
    return {"id":"eb_"+hashlib.md5((e.get("url","")).encode()).hexdigest()[:12],"name":e.get("name",""),"start":(e.get("startDate","") or "")[:10],"end":(e.get("endDate","") or "")[:10],"venue":loc.get("name",""),"address":addr.get("streetAddress","") if isinstance(addr,dict) else "","city":addr.get("addressLocality","") if isinstance(addr,dict) else "","state":addr.get("addressRegion","") if isinstance(addr,dict) else "","category":"","description":(e.get("description","") or "")[:200],"url":e.get("url",""),"image":image if isinstance(image,str) else "","is_free":False,"source":"eventbrite.com"}

def parse_eb_server(e):
    venue = e.get("primary_venue", e.get("venue",{})) or {}; addr = venue.get("address",{}) or {}
    start = e.get("start_date","") or e.get("start",{})
    if isinstance(start,dict): start = start.get("local","")
    name = e.get("name","")
    if isinstance(name,dict): name = name.get("text","")
    image = e.get("image", e.get("logo",{})) or {}
    if isinstance(image,dict): image = image.get("url", image.get("original",{}).get("url",""))
    return {"id":"eb_"+hashlib.md5(str(e.get("id","")).encode()).hexdigest()[:12],"name":name,"start":(str(start) or "")[:10],"end":"","venue":venue.get("name",""),"address":addr.get("localized_address_display",addr.get("address_1","")),"city":addr.get("city",""),"state":addr.get("region",""),"category":"","description":"","url":e.get("url",e.get("event_url","")),"image":image if isinstance(image,str) else "","is_free":e.get("is_free",False),"source":"eventbrite.com"}

def fetch_eventbrite():
    html = fetch_url(EVENTBRITE_URL, html=True)
    if not html: return []
    events = []

    # Strategy 1: JSON-LD
    for match in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
        try:
            data = json.loads(match.strip())
            if isinstance(data, list): data = data[0] if data else {}
            if isinstance(data,dict) and data.get("@type") == "ItemList":
                for li in data.get("itemListElement",[]):
                    item = li.get("item",{})
                    if item.get("@type") == "Event":
                        events.append(parse_eb_json_ld(item))
            elif isinstance(data,dict) and data.get("@type") == "Event":
                events.append(parse_eb_json_ld(data))
        except: continue

    # Strategy 2: __SERVER_DATA__
    if not events:
        m = re.search(r'window\.__SERVER_DATA__\s*=\s*({.*?});\s*</script>', html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                for e in data.get("search_data",{}).get("events",{}).get("results",[]):
                    events.append(parse_eb_server(e))
            except: pass

    # Filter to QC cities + future dates
    filtered = []
    for e in events:
        if e["city"].lower() in QC_CITIES and is_future(e["start"]):
            filtered.append(e)
    return filtered

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    all_events, seen = [], set()

    print("Fetching Visit QC events RSS...")
    for e in fetch_visitqc():
        if e["id"] not in seen: all_events.append(e); seen.add(e["id"])
    print(f"  {len(all_events)} events from visitquadcities.com")

    print("Scraping Eventbrite events...")
    eb = fetch_eventbrite()
    added = 0
    for e in eb:
        if e["id"] not in seen: all_events.append(e); seen.add(e["id"]); added += 1
    print(f"  {added} events from eventbrite.com")

    all_events.sort(key=lambda e: e["start"])
    print(f"  Total: {len(all_events)} combined.")

    if not all_events: print("  No events — keeping existing."); return

    OUT_FILE.write_text(json.dumps({"generated":datetime.now(timezone.utc).isoformat(),"total":len(all_events),"events":all_events}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Wrote {len(all_events)} events -> {OUT_FILE}")

if __name__ == "__main__":
    main()
