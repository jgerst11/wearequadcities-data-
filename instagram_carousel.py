"""
instagram_carousel.py: the QC Currents Instagram carousel (10/23/26).

Reads the latest SENT issue from wearequadcities.com (/wp-json/waqc/v1/qcc-latest, which mirrors Beehiiv) and writes
instagram/latest/: slide_1..7.jpg (1080x1350 portrait) + caption.txt + manifest.json. The WAQC Outreach Apps Script
checks manifest.json hourly and emails John the slides once per issue. Runs Thursdays from .github/workflows/instagram.yml;
does nothing if the latest issue already has slides (--force rebuilds).

Slides: 1 cover (issue hero photo) · 2-6 the QC Five (event photo, or the venue's directory photo when Visit QC only
has a stock city shot) · 7 subscribe call to action. Fonts: Gelasio (Georgia-like) and Arimo (Arial-like), both OFL, in fonts/.
"""
import html as htmlmod, io, json, os, re, sys, time, urllib.request
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "instagram", "latest")
LATEST = "https://www.wearequadcities.com/wp-json/waqc/v1/qcc-latest"
W, H, TOTAL = 1080, 1350, 7
NAVY, GOLD, CREAM, INK, MUTED, RULE = (29, 43, 69), (154, 106, 28), (246, 240, 229), (43, 43, 43), (107, 100, 87), (216, 204, 184)
UA = {"User-Agent": "Mozilla/5.0 (WeAreQuadCities carousel builder)"}


def font(family, size, weight="Regular"):
    f = ImageFont.truetype(os.path.join(ROOT, "fonts", family + ".ttf"), size)
    f.set_variation_by_name(weight)
    return f

SERIF = lambda s: font("Gelasio", s)
SERIF_B = lambda s: font("Gelasio", s, "Bold")
SANS = lambda s: font("Arimo", s)
SANS_B = lambda s: font("Arimo", s, "Bold")


def get(url, tries=5):
    for k in range(tries):   # the site's Cloudflare edge drops some requests; retry
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
        except Exception as ex:
            if k == tries - 1: raise
            time.sleep(5 + 5 * k)


def photo(src):
    if src.startswith("http"): return Image.open(io.BytesIO(get(src))).convert("RGB")
    return Image.open(os.path.join(ROOT, src.replace("\\", "/"))).convert("RGB")


def cover(img, w, h):
    s = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    l, t = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((l, t, l + w, t + h))


def text_block(d, x, y, text, f, fill, maxw, gap=1.3, max_lines=None):
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if d.textlength(t, font=f) <= maxw: cur = t
        else: lines.append(cur); cur = word
    if cur: lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]; lines[-1] = lines[-1].rstrip(".,;:") + "…"
    for ln in lines:
        d.text((x, y), ln, font=f, fill=fill); y += int(f.size * gap)
    return y


def brand_bar(d, page):
    d.line((60, H - 110, W - 60, H - 110), fill=RULE, width=2)
    d.text((60, H - 82), "QC CURRENTS", font=SANS_B(26), fill=NAVY)
    d.text((W // 2, H - 82), "wearequadcities.com", font=SANS(26), fill=MUTED, anchor="ma")
    d.text((W - 60, H - 82), f"{page}/{TOTAL}", font=SANS(26), fill=MUTED, anchor="ra")


# ── Read the issue ────────────────────────────────────────────────────────────

def parse(issue):
    h = issue["html"]
    lines = [htmlmod.unescape(l).strip() for l in re.sub(r"<[^>]+>", "\n", h).split("\n")]
    lines = [l for l in lines if l]
    out = {"hero": None, "hero_cap": "", "span": "", "five": []}
    m = re.search(r'<img[^>]+src="([^"]+)"', h)
    out["hero"] = htmlmod.unescape(m.group(1)) if m else issue.get("img")
    # Hero caption = the two lines after the date line: "Shady Knoll Farm" + "· East Moline, IL — A working…"
    k = next((i for i, l in enumerate(lines) if re.match(r"^[A-Z]+DAY, ", l)), None)
    if k is not None and k + 2 < len(lines):
        town = re.sub(r"^[·\s]+", "", lines[k + 2]).split(" — ")[0]
        out["hero_cap"] = lines[k + 1] + (" · " + re.sub(r",\s*(IA|IL)$", "", town) if town else "")
    q = next((i for i, l in enumerate(lines) if "QC FIVE" in l.upper()), None)
    if q is None: return out
    sm = re.search(r"getting out for (.+?)\.?$", lines[q + 1]) if q + 1 < len(lines) else None
    out["span"] = sm.group(1) if sm else ""
    urls = [htmlmod.unescape(u) for u in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(?:<[^>]+>)*\s*Event details', h)]
    i = q + 2
    while i + 3 < len(lines) and len(out["five"]) < 5:
        if re.fullmatch(r"\d", lines[i]):
            when, _, place = lines[i + 2].partition("·")
            out["five"].append({"n": int(lines[i]), "name": lines[i + 1], "when": when.strip(), "place": place.strip(),
                                "blurb": lines[i + 3] if lines[i + 3] != "Event details" else "",
                                "url": urls[len(out["five"])] if len(urls) > len(out["five"]) else ""})
            i += 4
        else:
            if lines[i].startswith("—") and out["five"]: break   # next section
            i += 1
    return out


def event_photo(e, events, ents, uses):
    ev = next((x for x in events if e["url"] and x.get("url") == e["url"]), None) \
        or next((x for x in events if x.get("name", "").lower() == e["name"].lower()), None) or {}
    img = ev.get("image")
    # Visit QC fills photo-less events with stock city shots (/images/made/.../_safe/); use the venue's own photo instead
    if not img or "/images/made/" in img or uses.get(img, 0) >= 3:
        venue = (ev.get("venue") or e["place"].split(",")[0]).lower()
        ent = next((x for x in ents if x.get("name", "").lower() == venue and (x.get("photos") or {}).get("primary")), None)
        if ent: img = ent["photos"]["primary"]
    return img


# ── Draw ──────────────────────────────────────────────────────────────────────

def slide_cover(p):
    im = Image.new("RGB", (W, H), CREAM); d = ImageDraw.Draw(im)
    if p["hero"]:
        im.paste(cover(photo(p["hero"]), W, 860), (0, 0))
        if p["hero_cap"]:
            d.text((W - 24, 836), p["hero_cap"], font=SANS(22), fill=(255, 255, 255), anchor="rs", stroke_width=2, stroke_fill=(0, 0, 0))
    d.text((60, 900), "THE QC FIVE", font=SANS_B(40), fill=GOLD)
    d.text((60, 960), "Five things worth", font=SERIF_B(78), fill=NAVY)
    d.text((60, 1050), "getting out for", font=SERIF_B(78), fill=NAVY)
    d.text((60, 1150), p["span"], font=SERIF(46), fill=INK)
    d.text((W - 60, 1158), "Swipe  ›", font=SANS_B(34), fill=GOLD, anchor="ra")
    brand_bar(d, 1)
    return im


def slide_event(e, img):
    im = Image.new("RGB", (W, H), CREAM); d = ImageDraw.Draw(im)
    if img:
        try:
            src = photo(img)
            im.paste(cover(src, W, 700).filter(ImageFilter.GaussianBlur(28)), (0, 0))   # soft fill behind framed photos
            # Show the whole image (event photos are often flyers with text); fill edge to edge only when its shape
            # already matches the 1080x700 band, so nothing important is cropped
            if abs(src.width / src.height - W / 700) < 0.12:
                fit = cover(src, W, 700)
            else:
                s = min(W * 0.92 / src.width, 650 / src.height)
                fit = src.resize((round(src.width * s), round(src.height * s)), Image.LANCZOS)
            im.paste(fit, ((W - fit.width) // 2, (700 - fit.height) // 2))
        except Exception as ex:
            print("  photo failed:", e["name"], ex)
            d.rectangle((0, 0, W, 700), fill=NAVY)
    else:
        d.rectangle((0, 0, W, 700), fill=NAVY)
    y = 740
    d.text((60, y), str(e["n"]), font=SERIF_B(72), fill=GOLD)
    y = text_block(d, 130, y + 8, e["name"], SERIF_B(54), NAVY, W - 190, 1.18, 2) + 10
    d.text((60, y), " · ".join(filter(None, [e["when"], e["place"]])).upper()[:60], font=SANS_B(28), fill=GOLD); y += 60
    text_block(d, 60, y, e["blurb"], SANS(34), INK, W - 120, 1.4, 6)
    brand_bar(d, e["n"] + 1)
    return im


def slide_cta():
    im = Image.new("RGB", (W, H), NAVY); d = ImageDraw.Draw(im)
    d.ellipse((W // 2 - 150, 170, W // 2 + 150, 470), outline=GOLD, width=4)        # the profile-photo mark
    d.text((W // 2, 262), "We Are", font=SERIF(46), fill=CREAM, anchor="mm")
    d.text((W // 2, 322), "Quad", font=SERIF_B(66), fill=GOLD, anchor="mm")
    d.text((W // 2, 392), "Cities", font=SERIF_B(66), fill=GOLD, anchor="mm")
    d.text((W // 2, 560), "Get five local picks", font=SERIF_B(70), fill=CREAM, anchor="ma")
    d.text((W // 2, 650), "every Thursday.", font=SERIF_B(70), fill=CREAM, anchor="ma")
    for k, ln in enumerate(["QC Currents is free, one email a week:", "events, local finds and stories from", "both sides of the river."]):
        d.text((W // 2, 790 + 50 * k), ln, font=SANS(36), fill=RULE, anchor="ma")
    d.rounded_rectangle((250, 990, 830, 1090), radius=50, fill=GOLD)
    d.text((W // 2, 1040), "Subscribe · link in bio", font=SANS_B(40), fill=(255, 255, 255), anchor="mm")
    d.text((W // 2, H - 82), "wearequadcities.com/qc-currents", font=SANS(28), fill=RULE, anchor="ma")
    return im


def caption(p):
    c = [f"The QC Five: five things worth getting out for, {p['span']}", ""]
    c += [f"{e['n']}. {e['name']} ({', '.join(filter(None, [e['when'], e['place']]))})" for e in p["five"]]
    c += ["", "Want these every Thursday? QC Currents is free. Link in bio.", "",
          "#QuadCities #QCA #Davenport #RockIsland #Moline #Bettendorf #EastMoline #QuadCitiesEvents #ThingsToDo #QCEvents"]
    return "\n".join(c)


def main():
    force = "--force" in sys.argv
    issue = json.loads(get(LATEST + "?t=" + str(int(time.time()))))
    if not issue.get("ok"): sys.exit("No issue yet.")
    man_path = os.path.join(OUT, "manifest.json")
    old = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else {}
    if old.get("slug") == issue["slug"] and not force:
        print("Slides already built for", issue["slug"]); return
    p = parse(issue)
    if len(p["five"]) < 5: sys.exit(f"Only found {len(p['five'])} QC Five events in {issue['slug']}; not building.")
    events = json.load(open(os.path.join(ROOT, "events.json"), encoding="utf-8")).get("events", [])
    ents = json.load(open(os.path.join(ROOT, "directory.json"), encoding="utf-8")).get("entities", [])
    uses = {}
    for x in events: uses[x.get("image")] = uses.get(x.get("image"), 0) + 1

    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT): os.remove(os.path.join(OUT, f))
    slides = [slide_cover(p)] + [slide_event(e, event_photo(e, events, ents, uses)) for e in p["five"]] + [slide_cta()]
    names = []
    for i, s in enumerate(slides, 1):
        names.append(f"slide_{i}.jpg"); s.save(os.path.join(OUT, names[-1]), quality=90)
    cap = caption(p)
    open(os.path.join(OUT, "caption.txt"), "w", encoding="utf-8").write(cap)
    json.dump({"slug": issue["slug"], "title": issue["title"], "issue_url": issue["url"], "date": issue["date"],
               "built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "slides": names, "caption": cap},
              open(man_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Built", len(names), "slides for", issue["slug"])


if __name__ == "__main__":
    main()
