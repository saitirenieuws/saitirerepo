# scripts/generate_site.py
import os
import json
import random
import datetime
from pathlib import Path
import feedparser
from slugify import slugify
from PIL import Image, ImageDraw, ImageFont

# =========================
# INSTELLINGEN
# =========================
SITE_TITLE = "Saitire"
SITE_DESC = "100% AI-gegenereerde satire. Niet echt nieuws."
SITE_URL = os.environ.get("SITE_URL", "https://saitire.nl")

PICKS_PER_RUN = int(os.environ.get("PICKS_PER_RUN", "3"))
MAX_STORE = int(os.environ.get("MAX_STORE", "200"))  # max aantal items in data/articles.json

# Feeds (je kunt hier later “meest gelezen/populair” feeds aan toevoegen)
FEEDS = [
    "https://www.nu.nl/rss/Algemeen",
    "https://nos.nl/rss/nieuws",
    "https://www.bnr.nl/podcast/nieuws.rss",
]

# Writer mode:
# - free  = gratis template-satire (werkt zonder API)
# - openai = betere kwaliteit met OpenAI API (kleine kosten)
WRITER_MODE = os.environ.get("WRITER_MODE", "free")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

LABEL = "100% AI-gegenereerde satire"

# =========================
# HULPFUNCTIES: Nieuws
# =========================
def normalize_title(t: str) -> str:
    return " ".join(t.lower().strip().split())

def fetch_headlines():
    items = []
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:12]:
                title = getattr(e, "title", "").strip()
                link = getattr(e, "link", "").strip()
                if title and link:
                    items.append({"title": title, "link": link})
        except Exception:
            pass

    # dedup
    seen = set()
    out = []
    for it in items:
        k = normalize_title(it["title"])
        if k not in seen:
            seen.add(k)
            out.append(it)

    random.shuffle(out)
    return out

def guess_category(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["kabinet","minister","regering","kamer","partij","coalitie","wet"]): return "Politiek"
    if any(k in t for k in ["inflatie","prijzen","economie","belasting","loon","bbp"]): return "Economie"
    if any(k in t for k in ["ai","kunstmatige intelligentie","tech","app","data","software","chip"]): return "Tech & AI"
    if any(k in t for k in ["zorg","onderwijs","woning","klimaat","ov","verkeer"]): return "Maatschappij"
    if any(k in t for k in ["voetbal","sport","wk","ek","olympisch","ajax","psv","feyenoord"]): return "Sport"
    return "Algemeen"

# =========================
# HULPFUNCTIES: Satire (gratis)
# =========================
def free_write_article(headline, link):
    chapeau = "De werkelijkheid houdt een spiegel voor, wij zetten er confetti op."
    title = headline.rstrip(".")

    punch_signals = [
        "Bron: een woordvoerder uit een parallel universum.",
        "Het plan is tijdelijk, tenzij het per ongeluk werkt.",
        "Experts noemen het ‘complex’, het publiek noemt het ‘weer zoiets’.",
        "De oplossing wordt onderzocht door een werkgroep die vooral goed is in onderzoeken.",
        "Volgens ingewijden is het vooral belangrijk dat iedereen ‘het verhaal kan uitleggen’.",
        "Er komt een Taskforce ‘Even Rustig Aan’ om de snelheid van besluitvorming te monitoren.",
        "De communicatie is alvast klaar; de inhoud volgt zodra iemand de bijlage vindt.",
    ]
    random.shuffle(punch_signals)

    paras = [
        f"In een ontwikkeling die door niemand werd gevraagd maar door iedereen wordt gescand, draait het nieuws vandaag om: <em>{headline}</em>.",
        "Betrokkenen benadrukken dat er ‘goed is geluisterd’, wat doorgaans betekent dat er vooral veel is genoteerd en weinig is gedaan.",
        "Critici noemen het een klassiek afleidingsmanoeuvre; voorstanders spreken van daadkracht, vooral in de communicatie daarover.",
        punch_signals[0],
        punch_signals[1],
        "Ondertussen blijven de feiten onverstoorbaar feiten. Daarom hieronder een kader met wat er wél echt speelt."
    ]

    body_html = "\n".join(f"<p>{p}</p>" for p in paras)
    facts_box = f"Satire op basis van actuele headline: {headline}. Bron: {link}"
    summary = f"Satire over: {headline}"

    return {
        "title": title,
        "chapeau": chapeau,
        "body_html": body_html,
        "facts_box": facts_box,
        "summary": summary
    }

# =========================
# HULPFUNCTIES: Satire (OpenAI)
# =========================
def openai_write_article(headline, link):
    # Geen extra libs: alleen standaard urllib
    import urllib.request

    system = (
        "Je schrijft Nederlandstalige satirische nieuwsartikelen. "
        "Stijl: De Speld meets late night talkshows. "
        "Regels: duidelijk satire, niet kwetsend, punch up (beleid/bedrijven/instanties), "
        "geen privépersonen targeten, geen stereotypering. "
        "Geen echte citaten toeschrijven; gebruik eventueel 'aldus een woordvoerder uit een parallel universum'. "
        "Structuur: titel, chapeau, 4-6 korte alinea's, en eindig met een kader "
        "'Wat is er echt gebeurd?' (2 zinnen neutraal) inclusief link."
    )

    user = (
        f"Headline: {headline}\n"
        f"Link: {link}\n"
        "Lengte: 300-450 woorden.\n"
        "Output als JSON met keys: title, chapeau, body_html, facts_box, summary.\n"
        "body_html moet HTML <p>...</p> bevatten."
    )

    payload = {
        "model": OPENAI_MODEL,
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

    try:
        obj = json.loads(txt)
        if all(k in obj for k in ["title","chapeau","body_html","facts_box","summary"]):
            return obj
    except Exception:
        pass

    # fallback
    return free_write_article(headline, link)

# =========================
# HULPFUNCTIES: Beeld maken (meme-card, duidelijk nep)
# =========================
def load_font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
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
    if line:
        lines.append(line)
    return lines[:4]

def make_meme_card(title, out_path):
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), (245, 248, 255))
    d = ImageDraw.Draw(img)

    # abstracte “fake” achtergrond
    for i, col in enumerate([(230,240,255),(210,225,255),(255,230,240)]):
        d.rounded_rectangle(
            [30+i*15, 30+i*12, W-30-i*12, H-30-i*15],
            radius=24,
            fill=col
        )

    # witte titelband
    band_h = int(H * 0.42)
    d.rectangle([0, H-band_h, W, H], fill=(255,255,255))

    # titel
    font_title = load_font(54)
    lines = wrap_text(d, title, font_title, W - 120)
    y = H - band_h + 40
    for line in lines:
        d.text((60, y), line, fill=(20,20,20), font=font_title)
        y += 66

    # klein watermerk onderin rechts
    wm = "SATIRE / AI"
    font_wm = load_font(18)
    w = d.textlength(wm, font=font_wm)
    d.text((W - w - 22, H - 32), wm, fill=(120,120,120), font=font_wm)

    img.save(out_path, "PNG")

# =========================
# HULPFUNCTIES: Artikelpagina
# (Let op: layout/styling staat in de pagina zelf zodat het altijd goed blijft.)
# =========================
def render_article_page(site_title, label, date, category, article, img_rel):
    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{article["title"]} • {site_title}</title>
<meta name="description" content="{article["summary"]}">
<style>
  :root {{
    --bg:#0b1020; --panel:rgba(255,255,255,.06); --text:rgba(255,255,255,.92);
    --muted:rgba(255,255,255,.70); --ring:rgba(124,58,237,.35);
    --green:#22c55e; --danger:#ef4444;
  }}
  *{{box-sizing:border-box}}
  body{{
    margin:0;
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    color:var(--text);
    background:
      radial-gradient(900px 500px at 10% 10%, rgba(124,58,237,.25), transparent 60%),
      radial-gradient(800px 500px at 90% 20%, rgba(34,197,94,.18), transparent 55%),
      var(--bg);
  }}
  a{{color:inherit}}
  .wrap{{max-width:860px;margin:0 auto;padding:26px 18px 70px}}
  .top{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}}
  .home{{text-decoration:none;padding:10px 12px;border-radius:12px;background:var(--panel);border:1px solid rgba(255,255,255,.10)}}
  .home:hover{{outline:2px solid var(--ring)}}
  .label{{color:var(--danger);font-weight:900}}
  .meta{{display:flex;gap:10px;flex-wrap:wrap;align-items:center;color:var(--muted);font-size:13px;margin-top:10px}}
  .badge{{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.12)}}
  .badge.cat{{background:rgba(34,197,94,.15);border-color:rgba(34,197,94,.25);color:rgba(255,255,255,.86);font-weight:800}}
  h1{{margin:16px 0 6px;font-size:34px;letter-spacing:-0.02em;line-height:1.12}}
  .chapeau{{color:var(--muted);font-style:italic;margin:0 0 14px;line-height:1.5}}
  .card{{border-radius:18px;overflow:hidden;border:1px solid rgba(255,255,255,.12);background:linear-gradient(180deg, rgba(255,255,255,.08), rgba(255,255,255,.03));box-shadow:0 10px 30px rgba(0,0,0,.22)}}
  img{{width:100%;height:auto;display:block}}
  .content{{padding:18px}}
  .content p{{margin:0 0 12px;line-height:1.65}}
  .facts{{margin-top:16px;padding:14px;border-left:4px solid rgba(255,255,255,.22);background:rgba(255,255,255,.06);border-radius:12px;color:var(--muted)}}
  .facts b{{color:rgba(255,255,255,.9)}}
  .footer{{margin-top:18px;color:var(--muted);font-size:13px}}
</style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <a class="home" href="/index.html">← Home</a>
      <div class="label">{label}</div>
    </div>

    <div class="meta">
      <span class="badge cat">{category}</span>
      <span class="badge">{date}</span>
      <span class="badge">SATIRE</span>
    </div>

    <h1>{article["title"]}</h1>
    <p class="chapeau">{article["chapeau"]}</p>

    <div class="card">
      <img src="/{img_rel}" alt="Satire/AI: {article["summary"]}">
      <div class="content">
        {article["body_html"]}
        <div class="facts"><b>Wat is er echt gebeurd?</b><br>{article["facts_box"]}</div>
      </div>
    </div>

    <div class="footer">© {datetime.date.today().year} {site_title} • Dit is satire, niet echt nieuws.</div>
  </div>
</body>
</html>
"""

# =========================
# HULPFUNCTIES: Data opslag
# =========================
def load_articles():
    p = Path("data/articles.json")
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_articles(items):
    Path("data").mkdir(exist_ok=True)
    p = Path("data/articles.json")
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

def add_article(items, new_item):
    # nieuw bovenaan
    items.insert(0, new_item)
    # dedup op path
    seen = set()
    out = []
    for it in items:
        path = it.get("path")
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(it)
    return out[:MAX_STORE]

# =========================
# HULPFUNCTIES: RSS
# =========================
def generate_feed(items):
    from xml.sax.saxutils import escape

    def item_xml(it):
        link = f"{SITE_URL}/{it['path']}"
        # RFC822-ish datum
        pubdate = datetime.datetime.fromisoformat(it["date"]).strftime("%a, %d %b %Y 00:00:00 +0000")
        return f"""  <item>
    <title>{escape(it["title"])}</title>
    <link>{link}</link>
    <guid>{link}</guid>
    <pubDate>{pubdate}</pubDate>
    <description>{escape(it.get("summary",""))}</description>
  </item>"""

    items_sorted = sorted(items, key=lambda x: x["date"], reverse=True)[:30]
    body = "\n".join(item_xml(i) for i in items_sorted)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>{escape(SITE_TITLE)}</title>
  <link>{escape(SITE_URL)}</link>
  <description>{escape(SITE_DESC)}</description>
  <language>nl</language>
{body}
</channel>
</rss>
"""

# =========================
# MAIN
# =========================
def main():
    Path("content").mkdir(exist_ok=True)
    Path("public/images").mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    # haal headlines op
    headlines = fetch_headlines()
    if not headlines:
        print("Geen headlines gevonden.")
        return

    # kies picks
    picks = headlines[:PICKS_PER_RUN]

    today = datetime.date.today().isoformat()

    # laad bestaande artikelenlijst
    articles = load_articles()

    for it in picks:
        headline, link = it["title"], it["link"]
        category = guess_category(headline)

        slug = slugify(headline)[:80]
        page_rel = f"content/{today}-{slug}.html"
        img_rel = f"public/images/{slug}.png"

        # skip als deze pagina al bestaat (voorkomt dupes)
        if Path(page_rel).exists():
            continue

        # schrijf artikel
        if WRITER_MODE == "openai" and OPENAI_API_KEY:
            article = openai_write_article(headline, link)
        else:
            article = free_write_article(headline, link)

        # maak afbeelding als die nog niet bestaat
        img_path = Path(img_rel)
        if not img_path.exists():
            make_meme_card(article["title"], img_path)

        # schrijf artikelpagina
        html = render_article_page(SITE_TITLE, LABEL, today, category, article, img_rel)
        Path(page_rel).write_text(html, encoding="utf-8")

        # voeg toe aan data/articles.json (bron voor homepage)
        new_item = {
            "title": article["title"],
            "chapeau": article["chapeau"],
            "summary": article["summary"],
            "path": page_rel,
            "image": img_rel,
            "category": category,
            "date": today
        }
        articles = add_article(articles, new_item)

    # schrijf data + rss
    save_articles(articles)
    Path("feed.xml").write_text(generate_feed(articles), encoding="utf-8")

    print(f"Klaar. Artikelen in store: {len(articles)}")

if __name__ == "__main__":
    main()
