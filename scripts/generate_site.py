# scripts/generate_site.py
import os
import json
import random
import datetime
import re
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
MAX_STORE = int(os.environ.get("MAX_STORE", "200"))

# OpenAI
WRITER_MODE = os.environ.get("WRITER_MODE", "free")  # free | openai
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

LABEL = "100% AI-gegenereerde satire"

# RSS-feeds
FEEDS = [
    "https://www.nu.nl/rss/Algemeen",
    "https://nos.nl/rss/nieuws",
    "https://www.bnr.nl/podcast/nieuws.rss",
]

# Clustering (lekentaal: hoeveel headlines per onderwerpcluster we max willen)
MAX_CLUSTERS = int(os.environ.get("MAX_CLUSTERS", "12"))

# =========================
# HELPERS: OpenAI call
# =========================
def call_openai(messages, temperature=0.9, timeout=90):
    """Return plain text from Chat Completions."""
    import urllib.request

    if not OPENAI_API_KEY:
        return ""

    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": temperature,
    }

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    return data["choices"][0]["message"]["content"].strip()

def safe_json_loads(text: str):
    """Try to parse JSON from text; if model wrapped it, extract first JSON object."""
    try:
        return json.loads(text)
    except Exception:
        pass
    # extract first {...} block
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None

# =========================
# HELPERS: Nieuws ophalen
# =========================
def normalize_title(t: str) -> str:
    return " ".join(t.lower().strip().split())

def fetch_headlines():
    items = []
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:15]:
                title = getattr(e, "title", "").strip()
                link = getattr(e, "link", "").strip()
                if title and link:
                    items.append({"title": title, "link": link, "feed": url})
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
# HELPERS: Clustering (simpel, werkt verrassend goed)
# =========================
STOPWORDS = set("""
de het een en of van voor op aan in met door naar bij over onder tegen
is zijn was waren wordt worden zal zullen heeft hebben had hadden
dit dat deze die daar hier
""".split())

def tokenize(s: str):
    s = re.sub(r"[^a-zA-Z0-9À-ÿ\s]", " ", s.lower())
    toks = [t for t in s.split() if len(t) > 2 and t not in STOPWORDS]
    return toks

def jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

def cluster_headlines(items, threshold=0.22):
    """
    Greedy clustering:
    - neem headline
    - stop bij bestaande cluster als token-overlap hoog genoeg is
    - anders nieuwe cluster
    """
    clusters = []
    for it in items:
        toks = tokenize(it["title"])
        placed = False
        for c in clusters:
            sim = jaccard(toks, c["tokens"])
            if sim >= threshold:
                c["items"].append(it)
                # tokens uitbreiden licht (representatie)
                c["tokens"] = list(set(c["tokens"] + toks))[:60]
                placed = True
                break
        if not placed:
            clusters.append({"tokens": toks[:60], "items": [it]})
    # sorteer clusters op grootte (meer headlines = waarschijnlijk groter onderwerp)
    clusters.sort(key=lambda c: len(c["items"]), reverse=True)
    return clusters[:MAX_CLUSTERS]

# =========================
# HELPERS: Humor-pipeline (invalshoeken -> keuze -> artikel)
# =========================
ANGLES_PROMPT = """Schrijf 5 satirische invalshoeken op dit nieuwscluster:
{cluster_summary}

Doel: punchy, non-kwetsend, “De Speld meets Late Night”.
Vermijd: privépersonen, haat, stereotypering. Focus op beleid/ideeën/instanties.

Elke invalshoek bevat EXACT deze onderdelen:
- premise
- twist
- doelgroep
- risico's (laster/haat/gevoelig) + hoe je dat ontwijkt
- 3 korte joke beats (beat 1 herkenning, beat 2 escalatie, beat 3 absurde consequentie)

Output als JSON:
{{
  "angles": [
    {{
      "premise": "...",
      "twist": "...",
      "doelgroep": "...",
      "risicos": "...",
      "beats": ["...", "...", "..."]
    }},
    ...
  ]
}}
"""

SELECT_PROMPT = """Hier zijn 5 satirische invalshoeken (JSON). Kies de grappigste voor een artikel.

Criteria:
- meest punchy
- beste escalatie (beat 1 -> 2 -> 3)
- punch up (instituties/beleid/systemen)
- laag risico (geen privépersonen, geen stereotypes)
- niet ‘samenvatten met grapje’, maar echt satirische logica

Antwoord als JSON:
{{
  "pick_index": 0,
  "reason": "1 zin waarom dit de beste is"
}}
JSON met invalshoeken:
{angles_json}
"""

ARTICLE_PROMPT = """Schrijf een satirisch nieuwsartikel op basis van deze invalshoek en cluster.

Cluster summary:
{cluster_summary}

Gekozen invalshoek:
Premise: {premise}
Twist: {twist}
Doelgroep: {doelgroep}
Risico's + ontwijking: {risicos}
Joke beats:
- {b1}
- {b2}
- {b3}

Regels:
- Stijl: De Speld × late night talkshows
- Punch up: instituties, beleid, systemen, ideeën
- Niet kwetsend, geen privépersonen
- Geen echte namen of citaten; gebruik evt. 'aldus een woordvoerder uit een parallel universum'
- 320–450 woorden
- Escalatie per alinea, beats moeten terugkomen
- Eindig met kader: 'Wat is er echt gebeurd?' (2 zinnen neutraal) + link

Output als JSON met keys:
{{
  "title": "...",
  "chapeau": "...",
  "body_html": "<p>...</p>...",
  "facts_box": "...",
  "summary": "..."
}}
Link voor facts: {link}
"""

def summarize_cluster_free(cluster_items):
    # simpele fallback summary (zonder AI)
    titles = [it["title"] for it in cluster_items[:6]]
    if len(titles) == 1:
        return f"Nieuws gaat over: {titles[0]}."
    return "Cluster over dit thema, met headlines zoals: " + " | ".join(titles[:4])

def build_cluster_summary(cluster_items):
    if WRITER_MODE != "openai" or not OPENAI_API_KEY:
        return summarize_cluster_free(cluster_items)

    titles = [f"- {it['title']}" for it in cluster_items[:10]]
    prompt = (
        "Vat dit nieuwscluster samen in 2-3 zinnen. "
        "Neutraal, feitelijk, geen mening. "
        "Gebruik geen namen van privépersonen; focus op onderwerp/beleid/instantie.\n\n"
        "Headlines:\n" + "\n".join(titles)
    )
    text = call_openai(
        [{"role":"system","content":"Je bent een nieuwsredacteur die neutraal samenvat."},
         {"role":"user","content":prompt}],
        temperature=0.2
    )
    return text.strip() if text else summarize_cluster_free(cluster_items)

def generate_angles(cluster_summary):
    if WRITER_MODE != "openai" or not OPENAI_API_KEY:
        # fallback: 2-3 “oké” invalshoeken i.p.v. 5 (gratis modus)
        return {
            "angles": [
                {
                    "premise":"De overheid kondigt iets groots aan, maar vooral de communicatie is klaar.",
                    "twist":"Er komt een werkgroep om te onderzoeken hoe je een werkgroep voorkomt.",
                    "doelgroep":"beleid, overheid, consultants",
                    "risicos":"Laag; geen personen, alleen systemen.",
                    "beats":["Iedereen is ‘blij met de duidelijkheid’.","Duidelijkheid blijkt een PDF met 94 pagina’s.","De enige harde deadline is de volgende deadline."]
                },
                {
                    "premise":"Instanties willen ‘strenger optreden’, maar beginnen met een evaluatie van streng optreden.",
                    "twist":"Handhaving wordt vervangen door een KPI over handhaving.",
                    "doelgroep":"toezichthouders, managers",
                    "risicos":"Laag; focus op instituties.",
                    "beats":["Er komt ‘zero tolerance’.","Zero tolerance wordt eerst getest in een pilot.","Pilot concludeert: tolerantie voor pilots is hoog."]
                }
            ]
        }

    prompt = ANGLES_PROMPT.format(cluster_summary=cluster_summary)
    raw = call_openai(
        [{"role":"system","content":"Je schrijft scherpe, niet-kwetsende satire-invalshoeken. Output strikt JSON."},
         {"role":"user","content":prompt}],
        temperature=0.9
    )
    obj = safe_json_loads(raw) or {}
    angles = obj.get("angles") or []
    # minimale sanity
    if len(angles) < 2:
        return generate_angles.__wrapped__(cluster_summary) if hasattr(generate_angles, "__wrapped__") else {"angles":[]}
    return {"angles": angles[:5]}

def pick_best_angle(angles_obj):
    angles = angles_obj.get("angles") or []
    if not angles:
        return None

    if WRITER_MODE != "openai" or not OPENAI_API_KEY:
        return angles[0]  # fallback: eerste

    angles_json = json.dumps(angles, ensure_ascii=False, indent=2)
    prompt = SELECT_PROMPT.format(angles_json=angles_json)
    raw = call_openai(
        [{"role":"system","content":"Je kiest de beste satirische invalshoek. Output strikt JSON."},
         {"role":"user","content":prompt}],
        temperature=0.3
    )
    obj = safe_json_loads(raw) or {}
    idx = obj.get("pick_index", 0)
    try:
        idx = int(idx)
    except Exception:
        idx = 0
    idx = max(0, min(idx, len(angles)-1))
    return angles[idx]

def write_article_from_angle(cluster_summary, angle, link):
    if WRITER_MODE != "openai" or not OPENAI_API_KEY:
        # fallback: gratis template op cluster
        return free_write_article(cluster_summary, link)

    prompt = ARTICLE_PROMPT.format(
        cluster_summary=cluster_summary,
        premise=angle.get("premise",""),
        twist=angle.get("twist",""),
        doelgroep=angle.get("doelgroep",""),
        risicos=angle.get("risicos",""),
        b1=(angle.get("beats") or ["","",""])[0],
        b2=(angle.get("beats") or ["","",""])[1],
        b3=(angle.get("beats") or ["","",""])[2],
        link=link
    )
    raw = call_openai(
        [{"role":"system","content":"Je schrijft scherpe, niet-kwetsende satire. Output strikt JSON."},
         {"role":"user","content":prompt}],
        temperature=0.9
    )
    obj = safe_json_loads(raw)
    if obj and all(k in obj for k in ["title","chapeau","body_html","facts_box","summary"]):
        return obj
    # fallback als model niet netjes JSON doet
    return free_write_article(cluster_summary, link)

# =========================
# HELPERS: Satire (gratis template)
# =========================
def free_write_article(headline, link):
    chapeau = "De werkelijkheid houdt een spiegel voor, wij zetten er confetti op."
    title = str(headline).strip().rstrip(".")
    punch = [
        "Bron: een woordvoerder uit een parallel universum.",
        "Het plan is tijdelijk, tenzij het per ongeluk werkt.",
        "Experts noemen het ‘complex’, het publiek noemt het ‘weer zoiets’.",
        "De oplossing wordt onderzocht door een werkgroep die vooral goed is in onderzoeken.",
        "Volgens ingewijden is het vooral belangrijk dat iedereen ‘het verhaal kan uitleggen’.",
        "Er komt een Taskforce ‘Even Rustig Aan’ om de snelheid van besluitvorming te monitoren.",
        "De communicatie is alvast klaar; de inhoud volgt zodra iemand de bijlage vindt.",
    ]
    random.shuffle(punch)

    paras = [
        f"In een ontwikkeling die door niemand werd gevraagd maar door iedereen wordt gescand, draait het vandaag om: <em>{headline}</em>.",
        "Betrokkenen benadrukken dat er ‘goed is geluisterd’, wat doorgaans betekent dat er vooral veel is genoteerd en weinig is gedaan.",
        "Critici noemen het een klassiek afleidingsmanoeuvre; voorstanders spreken van daadkracht, vooral in de communicatie daarover.",
        punch[0],
        punch[1],
        "Ondertussen blijven de feiten onverstoorbaar feiten. Daarom hieronder een kader met wat er wél echt speelt."
    ]
    body_html = "\n".join(f"<p>{p}</p>" for p in paras)
    facts_box = f"Wat is er echt gebeurd? Dit stuk is satire op basis van dit onderwerp. Bron: {link}"
    summary = f"Satire over: {headline}"
    return {"title": title, "chapeau": chapeau, "body_html": body_html, "facts_box": facts_box, "summary": summary}

# =========================
# HELPERS: Beeld (lokaal)
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

    for i, col in enumerate([(230,240,255),(210,225,255),(255,230,240)]):
        d.rounded_rectangle([30+i*15, 30+i*12, W-30-i*12, H-30-i*15], radius=24, fill=col)

    band_h = int(H * 0.42)
    d.rectangle([0, H-band_h, W, H], fill=(255,255,255))

    font_title = load_font(54)
    lines = wrap_text(d, title, font_title, W - 120)
    y = H - band_h + 40
    for line in lines:
        d.text((60, y), line, fill=(20,20,20), font=font_title)
        y += 66

    wm = "SATIRE / AI"
    font_wm = load_font(18)
    w = d.textlength(wm, font=font_wm)
    d.text((W - w - 22, H - 32), wm, fill=(120,120,120), font=font_wm)

    img.save(out_path, "PNG")

# =========================
# HELPERS: Artikelpagina
# =========================
def render_article_page(site_title, label, date, category, article, img_rel):
    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{article["title"]} - {site_title}</title>
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
<div class="panel" style="margin-top:14px;">
  <div class="panelHead"><h3>Meer lezen</h3></div>
  <div id="more" class="list"></div>
  <p class="panelHint">Meer uit dezelfde categorie.</p>
</div>

<script>
(async function(){
  try{
    const res = await fetch("/data/by_category.json", {cache:"no-store"});
    if(!res.ok) return;
    const byCat = await res.json();
    const cat = ${json.dumps(category)};
    const items = (byCat[cat] || []).filter(x => ("/"+x.path) !== location.pathname).slice(0, 5);
    const el = document.getElementById("more");
    el.innerHTML = items.map(it => `
      <a class="listItem" href="/${it.path}">
        <div class="listTitle">${it.title}</div>
        <div class="listMeta">${it.category} - ${it.date}</div>
      </a>
    `).join("") || `<div class="empty">Nog even geen meer-lezen.</div>`;
  }catch(e){}
})();
</script>
    <div class="footer">© {datetime.date.today().year} {site_title} - Dit is satire, niet echt nieuws.</div>
  </div>
</body>
</html>
"""

# =========================
# HELPERS: Data opslag
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
    Path("data").mkdir(parents=True, exist_ok=True)
    Path("data/articles.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

def add_article(items, new_item):
    items.insert(0, new_item)
    seen = set()
    out = []
    for it in items:
        path = it.get("path")
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(it)
    return out[:MAX_STORE]

def slug_category(name: str) -> str:
    m = {
        "Politiek": "politiek",
        "Economie": "economie",
        "Tech & AI": "tech-ai",
        "Maatschappij": "maatschappij",
        "Sport": "sport",
        "Algemeen": "algemeen",
    }
    return m.get(name, slugify(name))

def build_by_category(articles):
    by = {}
    for a in articles:
        cat = a.get("category") or "Algemeen"
        by.setdefault(cat, []).append(a)
    # sorteer per categorie op datum (desc) en dan titel
    for cat in by:
        by[cat].sort(key=lambda x: (x.get("date",""), x.get("title","")), reverse=True)
    return by

def build_search_index(articles):
    # minimale velden voor client-side search
    out = []
    for a in articles:
        out.append({
            "title": a.get("title",""),
            "summary": a.get("summary",""),
            "chapeau": a.get("chapeau",""),
            "path": a.get("path",""),
            "image": a.get("image",""),
            "category": a.get("category",""),
            "date": a.get("date",""),
        })
    return out

def write_sitemap(articles):
    # sitemap: homepage + categorieën + alle artikelen
    cats = ["Politiek","Economie","Tech & AI","Maatschappij","Sport","Algemeen"]

    urls = []
    urls.append(SITE_URL + "/")
    urls.append(SITE_URL + "/categorie/")
    urls.append(SITE_URL + "/search/")

    for c in cats:
        urls.append(SITE_URL + f"/categorie/{slug_category(c)}/")

    for a in articles:
        p = a.get("path","")
        if p:
            urls.append(SITE_URL + "/" + p)

    today = datetime.date.today().isoformat()
    body = "\n".join(
        f"""  <url><loc>{u}</loc><lastmod>{today}</lastmod></url>"""
        for u in sorted(set(urls))
    )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{body}
</urlset>
"""
    Path("sitemap.xml").write_text(xml, encoding="utf-8")


# =========================
# HELPERS: RSS
# =========================
def generate_feed(items):
    from xml.sax.saxutils import escape

    def item_xml(it):
        link = f"{SITE_URL}/{it['path']}"
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
    Path("content").mkdir(parents=True, exist_ok=True)
    Path("public/images").mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(parents=True, exist_ok=True)

    headlines = fetch_headlines()
    if not headlines:
        print("Geen headlines gevonden.")
        return

    clusters = cluster_headlines(headlines)
    if not clusters:
        print("Geen clusters gemaakt.")
        return

    today = datetime.date.today().isoformat()
    articles_store = load_articles()

    # Kies de grootste clusters eerst
    clusters = clusters[:max(PICKS_PER_RUN, 1)]

    for c in clusters:
        cluster_items = c["items"]
        # Neem 1 link voor facts (eerste item)
        anchor = cluster_items[0]
        link = anchor["link"]

        cluster_summary = build_cluster_summary(cluster_items)
        angles_obj = generate_angles(cluster_summary)
        best_angle = pick_best_angle(angles_obj)

        if not best_angle:
            # fallback
            article = free_write_article(cluster_summary, link)
        else:
            article = write_article_from_angle(cluster_summary, best_angle, link)

        category = guess_category(article.get("title", "") or cluster_summary)
        slug = slugify(article.get("title", cluster_summary))[:80]
        page_rel = f"content/{today}-{slug}.html"
        img_rel = f"public/images/{slug}.png"

        # skip als al bestaat
        if Path(page_rel).exists():
            continue

        # beeld maken (voorlopig tekstkaart)
        img_path = Path(img_rel)
        if not img_path.exists():
            make_meme_card(article["title"], img_path)

        # schrijf artikelpagina
        html = render_article_page(SITE_TITLE, LABEL, today, category, article, img_rel)
        Path(page_rel).write_text(html, encoding="utf-8")

        # update store
        new_item = {
            "title": article["title"],
            "chapeau": article["chapeau"],
            "summary": article["summary"],
            "path": page_rel,
            "image": img_rel,
            "category": category,
            "date": today,
        }
        articles_store = add_article(articles_store, new_item)

        print("GEPUBLICEERD:", article["title"])
        # kleine spreiding voor variatie
        random.shuffle(clusters)

    # schrijf data + rss
    save_articles(articles_store)
    Path("feed.xml").write_text(generate_feed(articles_store), encoding="utf-8")
    # extra data voor site-functionaliteit
    by_cat = build_by_category(articles_store)
    Path("data/by_category.json").write_text(json.dumps(by_cat, ensure_ascii=False, indent=2), encoding="utf-8")

    search_idx = build_search_index(articles_store)
    Path("data/search.json").write_text(json.dumps(search_idx, ensure_ascii=False, indent=2), encoding="utf-8")

    # sitemap
    write_sitemap(articles_store)

    print(f"Klaar. Artikelen in store: {len(articles_store)}")

if __name__ == "__main__":
    main()
