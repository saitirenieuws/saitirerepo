import os, json, random, datetime
from pathlib import Path
import feedparser
from slugify import slugify
from PIL import Image, ImageDraw, ImageFont

# ====== INSTELLINGEN ======
SITE_TITLE = "Saitire"
SITE_DESC = "100% AI-gegenereerde satire. Niet echt nieuws."
SITE_URL = os.environ.get("SITE_URL", "https://saitire.nl")  # zet later in GitHub Secrets of laat zo

PICKS_PER_RUN = int(os.environ.get("PICKS_PER_RUN", "3"))

FEEDS = [
    "https://www.nu.nl/rss/Algemeen",
    "https://nos.nl/rss/nieuws",
    "https://www.bnr.nl/podcast/nieuws.rss",
]

# Writer mode:
# - "free" = simpele generator zonder API (gratis, prima voor MVP)
# - "openai" = gebruikt OpenAI API (betere kwaliteit, kleine kosten)
WRITER_MODE = os.environ.get("WRITER_MODE", "free")

# OpenAI (alleen nodig als WRITER_MODE=openai)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# ====== HULPFUNCTIES ======
def normalize_title(t: str) -> str:
    return " ".join(t.lower().strip().split())

def fetch_headlines():
    items = []
    for url in FEEDS:
        feed = feedparser.parse(url)
        for e in feed.entries[:10]:
            title = getattr(e, "title", "").strip()
            link = getattr(e, "link", "").strip()
            if title and link:
                items.append({"title": title, "link": link})
    # dedup
    seen = set()
    out = []
    for it in items:
        key = normalize_title(it["title"])
        if key not in seen:
            seen.add(key)
            out.append(it)
    random.shuffle(out)
    return out

def guess_category(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["kabinet","minister","regering","kamer","partij","coalitie","wet"]): return "Politiek"
    if any(k in t for k in ["inflatie","prijzen","economie","belasting","loon","bbp"]): return "Economie"
    if any(k in t for k in ["ai","kunstmatige intelligentie","tech","app","data","software","chip"]): return "Tech & AI"
    if any(k in t for k in ["zorg","onderwijs","woning","klimaat","ov","verkeer"]): return "Maatschappij"
    if any(k in t for k in ["voetbal","sport","wk","ek","olympisch"]): return "Sport"
    return "Algemeen"

def free_write_article(headline, link):
    # “De Speld x late night”-achtige stijl, zonder kwetsen, punch-up
    bits_pool = [
        "Bron: een woordvoerder uit een parallel universum.",
        "Het plan is tijdelijk, tenzij het per ongeluk werkt.",
        "Experts noemen het ‘complex’, het publiek noemt het ‘weer zoiets’.",
        "De oplossing wordt onderzocht door een werkgroep die vooral goed is in onderzoeken.",
        "Volgens ingewijden is het vooral belangrijk dat iedereen ‘het verhaal kan uitleggen’."
    ]
    random.shuffle(bits_pool)
    chapeau = "De werkelijkheid houdt een spiegel voor, wij zetten er confetti op."
    title = headline.rstrip(".")
    paras = [
        f"In een ontwikkeling die door niemand werd gevraagd maar door iedereen wordt gescand, draait het nieuws vandaag om: <em>{headline}</em>.",
        "Betrokkenen benadrukken dat er ‘goed is geluisterd’, wat doorgaans betekent dat er vooral veel is genoteerd en weinig is gedaan.",
        "Critici noemen het een klassiek afleidingsmanoeuvre; voorstanders spreken van daadkracht, vooral in de communicatie daarover.",
        bits_pool[0],
        bits_pool[1],
        "Ondertussen blijven de feiten onverstoorbaar feiten. Daarom hieronder een kader met wat er wél echt speelt."
    ]
    body_html = "\n".join(f"<p>{p}</p>" for p in paras)
    facts = f"Wat is er echt gebeurd? Dit stuk is satire op basis van een actuele headline: {headline}. Bron: {link}"
    return {
        "title": title,
        "chapeau": chapeau,
        "body_html": body_html,
        "facts_box": facts,
        "summary": f"Satire over: {headline}"
    }

def openai_write_article(headline, link):
    # Kleine, simpele OpenAI call via HTTP (geen extra libs)
    import urllib.request

    system = (
        "Je schrijft Nederlandstalige satirische nieuwsartikelen. "
        "Stijl: De Speld meets late night talkshows. "
        "Regels: duidelijk satire, niet kwetsend, punch up (beleid/bedrijven/instanties), "
        "geen privépersonen targeten, geen stereotypering. "
        "Geen echte citaten toeschrijven; gebruik eventueel 'aldus een woordvoerder uit een parallel universum'. "
        "Structuur: titel, chapeau, 4-6 korte alinea's met 3-5 punchlines, "
        "en eindig met een kader 'Wat is er echt gebeurd?' (2 zinnen neutraal) inclusief link."
    )
    user = f"Nieuws: {headline}\nLink: {link}\nLengte: 300-450 woorden.\nOutput als JSON met keys: title, chapeau, body_html, facts_box, summary."

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role":"system","content":system},{"role":"user","content":user}],
        "temperature": 0.9
    }

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type":"application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    txt = data["choices"][0]["message"]["content"]

    # verwacht JSON terug; als het niet lukt: fallback naar free
    try:
        obj = json.loads(txt)
        # minimale velden check
        if all(k in obj for k in ["title","chapeau","body_html","facts_box","summary"]):
            return obj
    except Exception:
        pass
    return free_write_article(headline, link)

def load_font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()

def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, line = [], ""
    for w in words:
        test = (line + " " + w).strip()
        if draw.textlength(test, font=font) <= max_width:
            line = test
        else:
            lines.append(line)
            line = w
    if line: lines.append(line)
    return lines[:4]

def make_meme_card(title, out_path):
    # 1200x630 “neppe persfoto/meme kaart”
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), (245, 248, 255))
    d = ImageDraw.Draw(img)

    # neppe abstracte vormen
    for i, col in enumerate([(230,240,255),(210,225,255),(255,230,240)]):
        d.rounded_rectangle([30+i*15, 30+i*12, W-30-i*12, H-30-i*15], radius=24, fill=col)

    # witte titelplaat
    band_h = int(H*0.42)
    d.rectangle([0, H-band_h, W, H], fill=(255,255,255))

    # titel
    font_title = load_font(54)
    lines = wrap_text(d, title, font_title, W-120)
    y = H-band_h + 40
    for line in lines:
        d.text((60, y), line, fill=(20,20,20), font=font_title)
        y += 66

    # klein watermerk onderin rechts
    wm = "SATIRE / AI"
    font_wm = load_font(22)
    w = d.textlength(wm, font=font_wm)
    d.text((W - w - 24, H - 34), wm, fill=(120,120,120), font=font_wm)

    img.save(out_path, "PNG")

def render_article_page(site_title, label, date, category, article, img_rel):
    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{article["title"]} • {site_title}</title>
<meta name="description" content="{article["summary"]}">
</head>
<body style="font-family:Arial,sans-serif;max-width:800px;margin:auto;padding:20px;">
<nav><a href="/index.html">← Home</a></nav>
<h1>{site_title}</h1>
<p style="color:#ef4444;font-weight:700">{label}</p>
<div style="display:flex;gap:8px;align-items:center;color:#6b7280;font-size:14px;">
  <span style="background:#eef2ff;color:#3730a3;border-radius:999px;padding:4px 10px;font-weight:700">{category}</span>
  <span>•</span>
  <time datetime="{date}">{date}</time>
</div>
<h2 style="margin:10px 0 6px">{article["title"]}</h2>
<p><em>{article["chapeau"]}</em></p>
<img src="/{img_rel}" alt="Satire/AI: {article["summary"]}" style="max-width:100%;height:auto;margin:10px 0;">
{article["body_html"]}
<div style="background:#f7f7f7;padding:10px;border-left:4px solid #ddd;font-size:0.95em;margin-top:14px">{article["facts_box"]}</div>

<!-- Giscus: plak hier later je snippet (optioneel) -->
</body>
</html>
"""

def build_index(cards_html):
    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{SITE_TITLE}</title>
<link rel="alternate" type="application/rss+xml" title="{SITE_TITLE} RSS" href="/feed.xml" />
<style>
  :root{{--fg:#141415;--muted:#6b7280;--bg:#f8fafc;--card:#fff;--badge:#eef2ff;--badgefg:#3730a3;--accent:#ef4444;}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;}}
  header{{max-width:1000px;margin:24px auto 8px;padding:0 16px}}
  h1{{margin:0 0 4px;font-size:28px}}
  .label{{color:var(--accent);font-weight:700}}
  .meta{{display:flex;gap:12px;align-items:center;color:var(--muted);font-size:14px;margin-top:6px}}
  .grid{{max-width:1000px;margin:12px auto;padding:16px;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}}
  .card{{background:var(--card);border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);overflow:hidden;display:flex;flex-direction:column}}
  .thumb{{aspect-ratio:16/9;width:100%;object-fit:cover;background:#e5e7eb}}
  .card-body{{padding:14px}}
  .badges{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}}
  .badge{{background:var(--badge);color:var(--badgefg);border-radius:999px;padding:4px 10px;font-size:12px;font-weight:700}}
  .card h2{{margin:0 0 8px;font-size:18px;line-height:1.25}}
  .card p{{margin:0;color:var(--muted);font-size:14px}}
  .card a{{text-decoration:none;color:inherit}}
  footer{{max-width:1000px;margin:24px auto 40px;padding:0 16px;color:var(--muted);font-size:14px}}
</style>
</head>
<body>
<header>
  <h1>{SITE_TITLE}</h1>
  <div class="label">100% AI-gegenereerde satire</div>
  <div class="meta">
    <div>Dit is satire, niet echt nieuws.</div>
    <div>•</div>
    <div><a href="/feed.xml">RSS feed</a></div>
  </div>
</header>

<div class="grid" id="content">
{cards_html}
</div>

<footer>© {datetime.date.today().year} {SITE_TITLE}</footer>
</body>
</html>
"""

def generate_feed(items):
    # simpele RSS 2.0
    from xml.sax.saxutils import escape
    def item_xml(it):
        link = f"{SITE_URL}/{it['path']}"
        pubdate = datetime.datetime.fromisoformat(it["date"]).strftime("%a, %d %b %Y 00:00:00 +0000")
        return f"""  <item>
    <title>{escape(it["title"])}</title>
    <link>{link}</link>
    <guid>{link}</guid>
    <pubDate>{pubdate}</pubDate>
    <description>{escape(it["summary"])}</description>
  </item>"""
    items_sorted = sorted(items, key=lambda x: x["date"], reverse=True)[:30]
    body = "\n".join(item_xml(i) for i in items_sorted)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>{SITE_TITLE}</title>
  <link>{SITE_URL}</link>
  <description>{SITE_DESC}</description>
  <language>nl</language>
{body}
</channel>
</rss>
"""

def main():
    Path("content").mkdir(exist_ok=True)
    Path("public/images").mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    headlines = fetch_headlines()
    picks = headlines[:PICKS_PER_RUN]

    today = datetime.date.today().isoformat()
    cards = []
    feed_items = []

    # laad bestaande feed_items zodat je feed niet elke run “vergeet”
    old_path = Path("data/feed_items.json")
    if old_path.exists():
        try:
            feed_items = json.loads(old_path.read_text(encoding="utf-8"))
        except:
            feed_items = []

    for it in picks:
        headline, link = it["title"], it["link"]
        category = guess_category(headline)
        slug = slugify(headline)[:80]
        img_rel = f"public/images/{slug}.png"
        page_rel = f"content/{today}-{slug}.html"

        # schrijf artikel
        if WRITER_MODE == "openai" and OPENAI_API_KEY:
            article = openai_write_article(headline, link)
        else:
            article = free_write_article(headline, link)

        # maak beeld als het nog niet bestaat
        img_path = Path(img_rel)
        if not img_path.exists():
            make_meme_card(article["title"], img_path)

        # schrijf pagina
        html = render_article_page(SITE_TITLE, "100% AI-gegenereerde satire", today, category, article, img_rel)
        Path(page_rel).write_text(html, encoding="utf-8")

        # kaart voor homepage
        card = f"""
<div class="card">
  <a href="/{page_rel}">
    <img class="thumb" src="/{img_rel}" alt="Satire/AI: {article['summary']}">
    <div class="card-body">
      <div class="badges">
        <span class="badge">{category}</span>
        <span class="badge">{today}</span>
      </div>
      <h2>{article["title"]}</h2>
      <p>{article["chapeau"]}</p>
    </div>
  </a>
</div>
"""
        cards.append(card)

        # feed item
        feed_items.append({
            "title": article["title"],
            "summary": article["summary"],
            "path": page_rel,
            "date": today
        })

    # homepage updaten
    cards_html = "\n".join(cards)
    Path("index.html").write_text(build_index(cards_html), encoding="utf-8")

    # feed updaten
    Path("feed.xml").write_text(generate_feed(feed_items), encoding="utf-8")
    old_path.write_text(json.dumps(feed_items, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Site gegenereerd:", len(picks), "artikelen.")

if __name__ == "__main__":
    main()
