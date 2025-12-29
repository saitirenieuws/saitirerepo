import os
import json
import datetime
from pathlib import Path
from slugify import slugify

SITE_URL = "https://saitire.nl"

DATA_DIR = Path("data")
CONTENT_DIR = Path("content")
DATA_DIR.mkdir(exist_ok=True)
CONTENT_DIR.mkdir(exist_ok=True)

ARTICLES_FILE = DATA_DIR / "articles.json"
BY_CATEGORY_FILE = DATA_DIR / "by_category.json"
SEARCH_FILE = DATA_DIR / "search.json"
FEED_FILE = Path("feed.xml")
SITEMAP_FILE = Path("sitemap.xml")


def load_articles():
    if ARTICLES_FILE.exists():
        return json.loads(ARTICLES_FILE.read_text(encoding="utf-8"))
    return []


def save_articles(articles):
    ARTICLES_FILE.write_text(
        json.dumps(articles, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def render_article_page(article):
    html = """
<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="/assets/site.css">
</head>
<body>
<div class="wrap">
<header class="header">
  <div>
    <a class="logo" href="/"><span class="logoMark">S</span><span class="logoText">Saitire</span></a>
    <p class="subtitle">100% AI-gegenereerde satire. Niet echt nieuws.</p>
  </div>
</header>

<nav class="nav">
  <a href="/categorie/politiek/">Politiek</a>
  <a href="/categorie/economie/">Economie</a>
  <a href="/categorie/tech-ai/">Tech & AI</a>
  <a href="/categorie/maatschappij/">Maatschappij</a>
  <a href="/categorie/sport/">Sport</a>
  <a href="/categorie/algemeen/">Algemeen</a>
</nav>

<article class="section">
  <div class="badges">
    <span class="badge cat">{category}</span>
    <span class="badge">{date}</span>
    <span class="badge hot">SATIRE</span>
  </div>

  <h1>{title}</h1>
  <p class="desc"><em>{chapeau}</em></p>

  <img class="thumb" src="/{image}" alt="Satire afbeelding">

  {body}

  <div class="panel">
    <strong>Wat is er echt gebeurd?</strong>
    <p>{facts}</p>
  </div>

  __MORE__
</article>

<footer class="footer">
  <div>© {year} Saitire</div>
</footer>
</div>
</body>
</html>
""".format(
        title=article["title"],
        category=article["category"],
        date=article["date"],
        chapeau=article["chapeau"],
        image=article["image"],
        body=article["body_html"],
        facts=article["facts_box"],
        year=datetime.date.today().year
    )

    more_html = """
<div class="panel" style="margin-top:14px;">
  <div class="panelHead"><h3>Meer lezen</h3></div>
  <div id="more" class="list"></div>
</div>

<script>
(function(){
  fetch("/data/by_category.json", {cache:"no-store"})
    .then(r => r.json())
    .then(byCat => {
      const cat = "__CATEGORY__";
      const items = (byCat[cat] || [])
        .filter(x => ("/"+x.path) !== location.pathname)
        .slice(0, 5);

      const el = document.getElementById("more");
      if (!el) return;

      el.innerHTML = items.map(it => `
        <a class="listItem" href="/${it.path}">
          <div class="listTitle">${it.title}</div>
          <div class="listMeta">${it.category} - ${it.date}</div>
        </a>
      `).join("") || '<div class="empty">Nog geen andere artikelen.</div>';
    });
})();
</script>
"""

    html = html.replace("__MORE__", more_html.replace("__CATEGORY__", article["category"]))
    return html


def build_by_category(articles):
    out = {}
    for a in articles:
        out.setdefault(a["category"], []).append(a)
    for k in out:
        out[k].sort(key=lambda x: x["date"], reverse=True)
    return out


def build_search_index(articles):
    return [
        {
            "title": a["title"],
            "summary": a.get("summary", ""),
            "chapeau": a["chapeau"],
            "path": a["path"],
            "image": a["image"],
            "category": a["category"],
            "date": a["date"],
        }
        for a in articles
    ]


def write_feed(articles):
    items = ""
    for a in articles[:20]:
        items += f"""
<item>
  <title>{a['title']}</title>
  <link>{SITE_URL}/{a['path']}</link>
  <description>{a['summary']}</description>
  <pubDate>{a['date']}</pubDate>
</item>
"""
    FEED_FILE.write_text(f"""<?xml version="1.0"?>
<rss version="2.0">
<channel>
<title>Saitire</title>
<link>{SITE_URL}</link>
<description>100% AI satire</description>
{items}
</channel>
</rss>
""", encoding="utf-8")


def write_sitemap(articles):
    urls = [
        SITE_URL + "/",
        SITE_URL + "/categorie/",
        SITE_URL + "/search/"
    ]

    for cat in ["politiek", "economie", "tech-ai", "maatschappij", "sport", "algemeen"]:
        urls.append(SITE_URL + f"/categorie/{cat}/")

    for a in articles:
        urls.append(SITE_URL + "/" + a["path"])

    today = datetime.date.today().isoformat()
    body = "\n".join(
        f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>"
        for u in urls
    )

    SITEMAP_FILE.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{body}
</urlset>
""",
        encoding="utf-8"
    )


def main():
    articles = load_articles()

    # GEEN re-render van bestaande content/*.html
    # articles.json is alleen index-data (titel/chapeau/path/image/etc.)

    save_articles(articles)

    BY_CATEGORY_FILE.write_text(
        json.dumps(build_by_category(articles), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    SEARCH_FILE.write_text(
        json.dumps(build_search_index(articles), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    write_feed(articles)
    write_sitemap(articles)

    print(f"Klaar. Artikelen in store: {len(articles)}")


if __name__ == "__main__":
    main()
