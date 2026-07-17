"""
news_fetch.py
Fetches OurQuadCities RSS feed and writes news.json
to the pages/ folder for publishing to GitHub Pages.

Usage:
    python news_fetch.py
"""

import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

FEEDS = [
    { "source": "WHBF / OurQuadCities", "badge": "QC",  "color": "brick",
      "url": "https://www.ourquadcities.com/feed" },
    { "source": "QC Times",             "badge": "QCT", "color": "brand",
      "url": "https://qctimes.com/search/?f=rss&t=article&l=10&s=start_time&sd=desc" },
]
OUT_FILE  = Path(__file__).parent / "news.json"
MAX_ITEMS = 8

def fetch_rss(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")

def relative_time(pub_date_str):
    """Convert RSS pubDate string to a relative label."""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(pub_date_str)
        now = datetime.now(timezone.utc)
        mins = int((now - dt).total_seconds() / 60)
        if mins < 60:   return f"{mins} min ago"
        if mins < 1440: return f"{mins // 60} h ago"
        return f"{mins // 1440}d ago"
    except Exception:
        return ""

def parse_items(xml_str, feed):
    root = ET.fromstring(xml_str)
    ns   = {"media": "http://search.yahoo.com/mrss/"}
    items = []
    for item in root.iter("item"):
        title   = (item.findtext("title") or "").strip()
        link    = (item.findtext("link")  or "").strip()
        desc    = (item.findtext("description") or "").strip()
        pub     = (item.findtext("pubDate") or "").strip()

        # Strip HTML from description
        import re
        desc = re.sub(r"<[^>]+>", "", desc).strip()

        # Image: try enclosure, then media:content, then media:thumbnail
        image = ""
        enc = item.find("enclosure")
        if enc is not None:
            image = enc.get("url", "")
        if not image:
            mc = item.find("media:content", ns)
            if mc is not None:
                image = mc.get("url", "")
        if not image:
            mt = item.find("media:thumbnail", ns)
            if mt is not None:
                image = mt.get("url", "")

        # Category
        cat_el = item.find("category")
        cat    = (cat_el.text or "").strip() if cat_el is not None else ""

        items.append({
            "source":   feed["source"],
            "badge":    feed["badge"],
            "color":    feed["color"],
            "headline": title,
            "summary":  desc[:160] + ("…" if len(desc) > 160 else ""),
            "url":      link,
            "time":     relative_time(pub),
            "image":    image,
            "category": cat,
        })

    return items[:MAX_ITEMS]

def main():
    all_items = []
    for feed in FEEDS:
        print(f"  Fetching {feed['source']}...")
        try:
            xml = fetch_rss(feed["url"])
            items = parse_items(xml, feed)
            print(f"    {len(items)} articles.")
            all_items.append(items)
        except Exception as e:
            print(f"    ERROR: {e}")
            all_items.append([])

    # Interleave sources, cap at MAX_ITEMS
    interleaved = []
    max_len = max(len(x) for x in all_items) if all_items else 0
    for i in range(max_len):
        for feed_items in all_items:
            if i < len(feed_items):
                interleaved.append(feed_items[i])
    interleaved = interleaved[:MAX_ITEMS]

    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "items":   interleaved,
    }
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Wrote {len(interleaved)} articles -> {OUT_FILE}")

if __name__ == "__main__":
    main()
