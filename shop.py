"""Boutique Fortnite -> carrousel Instagram, automatiquement.

Usage :
  python shop.py generate            # télécharge la boutique et crée out/<date>/1.jpg, 2.jpg...
  python shop.py post <base_url>     # publie les images (accessibles via <base_url>/<date>/N.jpg)
"""
import io
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

SHOP_URL = "https://fortnite-api.com/v2/shop?language=fr"
GRAPH = "https://graph.instagram.com/v21.0"
OUT = Path("out")

# Format Instagram 4:5 portrait
W, H = 1080, 1350
COLS, ROWS = 5, 5
PER_SLIDE = COLS * ROWS
MAX_SLIDES = 10  # limite d'un carrousel via l'API
MARGIN, GAP, HEADER = 30, 12, 160
CARD_W = (W - 2 * MARGIN - (COLS - 1) * GAP) // COLS
CARD_H = (H - HEADER - MARGIN - (ROWS - 1) * GAP) // ROWS
TEXT_H = 54

RARITY = {
    "common": "#7b7b7b", "uncommon": "#4c9a2a", "rare": "#2f7bd6",
    "epic": "#8a3fd1", "legendary": "#d4772a", "mythic": "#c9a227",
    "marvel": "#b3262d", "dc": "#2b4fa8", "dark": "#a0158f", "icon": "#1d8aa3",
    "starwars": "#222222", "gaminglegends": "#4a2fb8", "shadow": "#3a3a3a",
    "slurp": "#16a7b5", "frozen": "#6fb4dd", "lava": "#c2452d", "lego": "#d9a400",
}
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
          "août", "septembre", "octobre", "novembre", "décembre"]


def font(size):
    for name in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "arialbd.ttf", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def date_fr(iso):
    y, m, d = iso[:10].split("-")
    return f"{int(d)} {MONTHS[int(m) - 1]} {y}"


def parse_entry(e):
    """Renvoie (nom, prix, image_url, couleur) ou None pour les pistes musicales seules."""
    br = e.get("brItems") or []
    others = (e.get("cars") or []) + (e.get("instruments") or []) + (e.get("legoKits") or [])
    if not br and not others:
        return None  # pistes musicales : on les ignore
    first = (br or others)[0]
    name = (e.get("bundle") or {}).get("name") or first.get("name") or first.get("title") or "?"

    img = None
    nda = e.get("newDisplayAsset") or {}
    renders = nda.get("renderImages") or []
    if renders:
        img = renders[0].get("image")
    img = img or (e.get("bundle") or {}).get("image")
    if not img:
        ims = first.get("images") or {}
        img = ims.get("featured") or ims.get("icon") or ims.get("large") or ims.get("small") or ims.get("smallIcon")

    rarity = ((first.get("series") or {}).get("backendValue") or "").lower().replace("series", "")
    rarity = rarity if rarity in RARITY else (first.get("rarity") or {}).get("value", "common")
    color = RARITY.get(rarity.lower(), RARITY["common"])
    return name, e.get("finalPrice", 0), img, color


def download(url, size):
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)).convert("RGBA")
        im.thumbnail(size, Image.LANCZOS)
        return im
    except Exception:
        return None


def fit_text(draw, text, f, max_w):
    if draw.textlength(text, font=f) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=f) > max_w:
        text = text[:-1]
    return text + "…"


def draw_card(item, thumb, vbuck):
    name, price, _, color = item
    card = Image.new("RGB", (CARD_W, CARD_H), color)
    # dégradé sombre vers le bas
    shade = Image.new("L", (1, CARD_H))
    for y in range(CARD_H):
        shade.putpixel((0, y), int(150 * y / CARD_H))
    card.paste((10, 10, 25), (0, 0), shade.resize((CARD_W, CARD_H)))
    if thumb:
        x = (CARD_W - thumb.width) // 2
        y = (CARD_H - TEXT_H - thumb.height) // 2
        card.paste(thumb, (x, y), thumb)
    d = ImageDraw.Draw(card)
    d.rectangle((0, CARD_H - TEXT_H, CARD_W, CARD_H), fill=(15, 15, 30))
    d.rectangle((0, CARD_H - TEXT_H, CARD_W, CARD_H - TEXT_H + 3), fill=color)
    f_name, f_price = font(16), font(16)
    d.text((CARD_W // 2, CARD_H - TEXT_H + 15), fit_text(d, name, f_name, CARD_W - 10),
           font=f_name, fill="white", anchor="mm")
    ptxt = f"{price:,}".replace(",", " ")
    pw = d.textlength(ptxt, font=f_price) + (22 if vbuck else 0)
    px = int((CARD_W - pw) // 2)
    if vbuck:
        card.paste(vbuck, (px, CARD_H - 15 - vbuck.height // 2), vbuck)
        px += 22
    d.text((px, CARD_H - 15), ptxt, font=f_price, fill="#e8e8f0", anchor="lm")
    return card


def generate():
    data = requests.get(SHOP_URL, timeout=60).json()["data"]
    day = data["date"][:10]
    items = [p for p in (parse_entry(e) for e in data["entries"]) if p]
    items.sort(key=lambda i: -i[1])  # les plus chers en premier
    items = items[:PER_SLIDE * MAX_SLIDES]
    print(f"{len(items)} objets dans la boutique du {day}")

    with ThreadPoolExecutor(16) as ex:
        thumbs = list(ex.map(lambda i: download(i[2], (CARD_W - 8, CARD_H - TEXT_H - 8)) if i[2] else None, items))
    vbuck = download(data.get("vbuckIcon") or "https://fortnite-api.com/images/vbuck.png", (18, 18))

    out = OUT / day
    out.mkdir(parents=True, exist_ok=True)
    n_slides = math.ceil(len(items) / PER_SLIDE)
    for s in range(n_slides):
        slide = Image.new("RGB", (W, H), (18, 14, 40))
        d = ImageDraw.Draw(slide)
        d.text((W // 2, 62), "BOUTIQUE FORTNITE", font=font(58), fill="white", anchor="mm")
        d.text((W // 2, 118), f"{date_fr(day)}  •  {s + 1}/{n_slides}", font=font(30), fill="#f5c542", anchor="mm")
        for k, idx in enumerate(range(s * PER_SLIDE, min((s + 1) * PER_SLIDE, len(items)))):
            r, c = divmod(k, COLS)
            slide.paste(draw_card(items[idx], thumbs[idx], vbuck),
                        (MARGIN + c * (CARD_W + GAP), HEADER + r * (CARD_H + GAP)))
        slide.save(out / f"{s + 1}.jpg", "JPEG", quality=90)

    top = ", ".join(i[0] for i in items[:5])
    caption = (f"🛒 Boutique Fortnite du {date_fr(day)} !\n\n"
               f"À ne pas manquer : {top}…\n\n"
               "Glisse pour tout voir ➡️\n\n"
               "#fortnite #boutiquefortnite #fortniteshop #itemshop #fortnitefr #skin")
    (out / "meta.json").write_text(json.dumps({"day": day, "slides": n_slides, "caption": caption},
                                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{n_slides} image(s) générée(s) dans {out}")


def ig(method, path, **params):
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    r = requests.request(method, f"{GRAPH}/{path}", params=params, timeout=60)
    if not r.ok:
        sys.exit(f"Erreur Instagram {r.status_code}: {r.text}")
    return r.json()


def wait_ready(container_id):
    for _ in range(30):
        status = ig("GET", container_id, fields="status_code")["status_code"]
        if status == "FINISHED":
            return
        if status == "ERROR":
            sys.exit(f"Le conteneur {container_id} est en erreur")
        time.sleep(5)
    sys.exit(f"Le conteneur {container_id} n'est jamais prêt")


def post(base_url):
    day_dir = max(p for p in OUT.iterdir() if p.is_dir())
    meta = json.loads((day_dir / "meta.json").read_text(encoding="utf-8"))
    user = os.environ["IG_USER_ID"]
    urls = [f"{base_url.rstrip('/')}/{meta['day']}/{i + 1}.jpg" for i in range(meta["slides"])]

    if len(urls) == 1:
        creation = ig("POST", f"{user}/media", image_url=urls[0], caption=meta["caption"])["id"]
    else:
        children = []
        for u in urls:
            cid = ig("POST", f"{user}/media", image_url=u, is_carousel_item="true")["id"]
            wait_ready(cid)
            children.append(cid)
        creation = ig("POST", f"{user}/media", media_type="CAROUSEL",
                      children=",".join(children), caption=meta["caption"])["id"]
    wait_ready(creation)
    res = ig("POST", f"{user}/media_publish", creation_id=creation)
    print(f"Publié sur Instagram ! id={res['id']}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "generate":
        generate()
    elif len(sys.argv) >= 3 and sys.argv[1] == "post":
        post(sys.argv[2])
    else:
        sys.exit(__doc__)
