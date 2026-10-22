"""Boutique Fortnite -> carrousel Instagram, automatiquement.

Usage :
  python shop.py generate            # télécharge la boutique et crée out/<date>/1.jpg, 2.jpg...
  python shop.py post <base_url> [all|feed|story]
      # publie le carrousel et/ou la story (images accessibles via <base_url>/<date>/...)
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
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SHOP_URL = "https://fortnite-api.com/v2/shop?language=fr"
GRAPH = "https://graph.instagram.com/v21.0"
OUT = Path("out")
FONT_FILE = Path(__file__).parent / "fonts" / "LilitaOne-Regular.ttf"
HANDLE = os.environ.get("IG_HANDLE", "@zzazo0")
CREATOR_CODE = os.environ.get("CREATOR_CODE", "IMAN")

# Format Instagram 4:5 portrait
W, H = 1080, 1350
MAX_SLIDES = 10  # limite d'un carrousel via l'API

# Couverture : les 6 objets phares en grand
HERO_COLS, HERO_ROWS = 3, 2
HERO_N = HERO_COLS * HERO_ROWS
# Pages suivantes : grille 5 x 5
COLS, ROWS = 5, 5
PER_SLIDE = COLS * ROWS

YELLOW = (255, 214, 0)
BG_TOP, BG_BOTTOM = (40, 22, 98), (9, 6, 32)
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
          "août", "septembre", "octobre", "novembre", "décembre"]
_fonts = {}


def font(size):
    if size not in _fonts:
        try:
            _fonts[size] = ImageFont.truetype(str(FONT_FILE), size)
        except OSError:
            _fonts[size] = ImageFont.load_default(size=size)
    return _fonts[size]


def date_fr(iso):
    y, m, d = iso[:10].split("-")
    return f"{int(d)} {MONTHS[int(m) - 1]} {y}"


def hex_rgb(h, default=(90, 90, 110)):
    try:
        h = h.lstrip("#")[:6]
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (AttributeError, ValueError):
        return default


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(size, top, bottom):
    g = Image.new("RGB", (1, 256))
    for y in range(256):
        g.putpixel((0, y), mix(top, bottom, y / 255))
    return g.resize(size, Image.BICUBIC)


def glow(size, color, strength=200):
    """Halo radial doux centré."""
    w, h = size
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).ellipse((w * 0.12, h * 0.05, w * 0.88, h * 0.75), fill=strength)
    m = m.filter(ImageFilter.GaussianBlur(min(w, h) / 6))
    layer = Image.new("RGBA", (w, h), color + (0,))
    layer.putalpha(m)
    return layer


# Catégories de la boutique complète, dans l'ordre d'affichage
CATEGORIES = ["PACKS", "SKINS", "DANSES", "MASCOTTES & COMPAGNONS", "CHAUSSURES", "PIOCHES",
              "SACS À DOS", "PLANEURS", "REVÊTEMENTS", "AÉROSOLS", "VOITURES", "INSTRUMENTS",
              "LEGO", "AUTRES"]
TYPE_CATEGORY = {  # type d'objet (API) -> catégorie, par ordre d'importance
    "outfit": "SKINS", "emote": "DANSES", "sidekick": "MASCOTTES & COMPAGNONS",
    "petcarrier": "MASCOTTES & COMPAGNONS", "pet": "MASCOTTES & COMPAGNONS",
    "shoe": "CHAUSSURES", "pickaxe": "PIOCHES", "backpack": "SACS À DOS", "glider": "PLANEURS",
    "wrap": "REVÊTEMENTS", "spray": "AÉROSOLS",
}


def category(e, br):
    if e.get("bundle"):
        return "PACKS"
    if e.get("cars"):
        return "VOITURES"
    if e.get("instruments"):
        return "INSTRUMENTS"
    if e.get("legoKits"):
        return "LEGO"
    types = {(i.get("type") or {}).get("value") for i in br}
    for t, cat in TYPE_CATEGORY.items():  # le type le plus important de l'offre l'emporte
        if t in types:
            return cat
    return "AUTRES"


def parse_entry(e):
    """Extrait les infos d'une offre (None pour les pistes musicales seules)."""
    br = e.get("brItems") or []
    others = (e.get("cars") or []) + (e.get("instruments") or []) + (e.get("legoKits") or [])
    if not br and not others:
        return None
    first = (br or others)[0]
    name = (e.get("bundle") or {}).get("name") or first.get("name") or first.get("title") or "?"

    img = None
    renders = (e.get("newDisplayAsset") or {}).get("renderImages") or []
    if renders:
        img = renders[0].get("image")
    img = img or (e.get("bundle") or {}).get("image")
    if not img:
        ims = first.get("images") or {}
        img = ims.get("featured") or ims.get("icon") or ims.get("large") or ims.get("small")

    colors = e.get("colors") or {}
    c1 = hex_rgb(colors.get("color1"))
    c3 = hex_rgb(colors.get("color3") or colors.get("color2"), c1)
    txt = hex_rgb(colors.get("textBackgroundColor"), mix(c1, (0, 0, 0), 0.7))
    if 0.299 * txt[0] + 0.587 * txt[1] + 0.114 * txt[2] > 90:  # bandeau trop clair : on l'assombrit
        txt = mix(txt, (0, 0, 0), 0.55)

    final, regular = e.get("finalPrice", 0), e.get("regularPrice", 0)
    banner = (e.get("banner") or {})
    if banner.get("backendValue") == "AmountOff" and regular > final:
        badge = f"-{regular - final:,}".replace(",", " ")
    else:
        badge = (banner.get("value") or "").upper()
    return {"name": name, "price": final, "regular": regular, "img": img,
            "top": c3, "bottom": c1, "strip": txt, "badge": badge,
            "in_date": (e.get("inDate") or "")[:10], "added": (first.get("added") or "")[:10],
            "is_new": banner.get("value", "").lower() == "nouveau", "cat": category(e, br)}


def download(url, max_side=480):
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)).convert("RGBA")
        im.thumbnail((max_side, max_side), Image.LANCZOS)
        return im
    except Exception:
        return None


def fit_font(draw, text, max_w, size, min_size):
    while size > min_size and draw.textlength(text, font=font(size)) > max_w:
        size -= 1
    f = font(size)
    if draw.textlength(text, font=f) > max_w:
        while text and draw.textlength(text + "…", font=f) > max_w:
            text = text[:-1]
        text += "…"
    return text, f


def shadow_text(draw, xy, text, f, fill, anchor="mm", offset=3):
    draw.text((xy[0] + offset, xy[1] + offset), text, font=f, fill=(0, 0, 0), anchor=anchor)
    draw.text(xy, text, font=f, fill=fill, anchor=anchor)


def draw_card(item, thumb, vbuck, w, h, big=False):
    radius = 22 if big else 14
    strip_h = int(h * (0.24 if big else 0.27))
    card = gradient((w, h), mix(item["top"], (255, 255, 255), 0.12), item["bottom"]).convert("RGBA")
    card.alpha_composite(glow((w, h - strip_h), (255, 255, 255), 150 if big else 120))

    # Objet, agrandi pour remplir la tuile
    if thumb:
        area_w, area_h = w - 8, h - strip_h - 6
        s = min(area_w / thumb.width, area_h / thumb.height)
        t = thumb.resize((max(1, int(thumb.width * s)), max(1, int(thumb.height * s))), Image.LANCZOS)
        card.alpha_composite(t, ((w - t.width) // 2, h - strip_h - t.height))

    d = ImageDraw.Draw(card)
    # Bandeau du nom et du prix
    d.rectangle((0, h - strip_h, w, h), fill=item["strip"] + (255,))
    d.rectangle((0, h - strip_h, w, h - strip_h + (4 if big else 3)), fill=mix(item["top"], (255, 255, 255), 0.35))

    name = item["name"].upper()
    name_y = h - strip_h + strip_h * 0.33
    txt, f = fit_font(d, name, w - 16, 34 if big else 19, 22 if big else 13)
    shadow_text(d, (w // 2, name_y), txt, f, "white", offset=2)

    # Prix
    pf = font(32 if big else 18)
    price = f"{item['price']:,}".replace(",", " ")
    icon = vbuck.resize((pf.size + 4, pf.size + 4), Image.LANCZOS) if vbuck else None
    old = f"{item['regular']:,}".replace(",", " ") if item["regular"] > item["price"] else ""
    of = font(24 if big else 14)
    gap = 6
    total = (icon.width + gap if icon else 0) + d.textlength(price, font=pf) + \
            (gap * 2 + d.textlength(old, font=of) if old else 0)
    x = int((w - total) / 2)
    py = int(h - strip_h * 0.3)
    if icon:
        card.alpha_composite(icon, (x, py - icon.height // 2))
        x += icon.width + gap
    d.text((x, py), price, font=pf, fill=(235, 235, 245), anchor="lm")
    if old:
        x += d.textlength(price, font=pf) + gap * 2
        d.text((x, py), old, font=of, fill=(170, 170, 185), anchor="lm")
        ow = d.textlength(old, font=of)
        d.line((x, py, x + ow, py), fill=(170, 170, 185), width=2)

    # Badge (NOUVEAU, réduction...)
    if item["badge"]:
        bf = font(24 if big else 13)
        btxt, bf = fit_font(d, item["badge"], w - 30, bf.size, 10)
        bw = d.textlength(btxt, font=bf) + (24 if big else 14)
        bh = bf.size + (14 if big else 8)
        d.rounded_rectangle((8, 8, 8 + bw, 8 + bh), radius=bh // 2, fill=YELLOW + (255,))
        d.text((8 + bw / 2, 8 + bh / 2 + 1), btxt, font=bf, fill=(20, 12, 40), anchor="mm")

    # Bord lumineux + coins arrondis
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius,
                        outline=mix(item["top"], (255, 255, 255), 0.45) + (255,), width=3 if big else 2)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    card.putalpha(mask)
    return card


def background(h=H):
    bg = gradient((W, h), BG_TOP, BG_BOTTOM).convert("RGBA")
    # rayons lumineux en éventail depuis le haut
    rays = Image.new("L", (W, h), 0)
    rd = ImageDraw.Draw(rays)
    for k in range(-6, 7, 2):
        rd.polygon([(W / 2, -200), (W / 2 + k * 160 - 60, h), (W / 2 + k * 160 + 60, h)], fill=26)
    rays = rays.filter(ImageFilter.GaussianBlur(30))
    light = Image.new("RGBA", (W, h), (140, 110, 255, 0))
    light.putalpha(rays)
    bg.alpha_composite(light)
    bg.alpha_composite(glow((W, 600), (120, 90, 255), 90), (0, -150))
    return bg


def paste_with_shadow(slide, card, xy):
    sh = Image.new("RGBA", (card.width + 30, card.height + 30), (0, 0, 0, 0))
    m = Image.new("L", sh.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((15, 15, 15 + card.width, 15 + card.height), radius=18, fill=150)
    sh.putalpha(m.filter(ImageFilter.GaussianBlur(8)))
    slide.alpha_composite(sh, (xy[0] - 15 + 4, xy[1] - 15 + 7))
    slide.alpha_composite(card, xy)


def header(slide, day, page, n_pages, big=False, y0=0, title=("BOUTIQUE", "FORTNITE")):
    d = ImageDraw.Draw(slide)
    if big:
        shadow_text(d, (W // 2, y0 + 92), "BOUTIQUE", font(118), "white", offset=5)
        shadow_text(d, (W // 2, y0 + 196), "FORTNITE", font(92), YELLOW, offset=5)
        y = y0 + 268
    else:
        left, right = title[0] + " ", " " + title[1]
        tf = font(64)
        while d.textlength(left + right, font=tf) > W - 260:
            tf = font(tf.size - 2)
        x = W // 2 + (d.textlength(left, font=tf) - d.textlength(right, font=tf)) / 2
        shadow_text(d, (x, 58), left, tf, "white", anchor="rm", offset=4)
        shadow_text(d, (x, 58), right, tf, YELLOW, anchor="lm", offset=4)
        y = 120
    # pastille date
    df = font(30 if big else 26)
    txt = date_fr(day).upper()
    tw = d.textlength(txt, font=df) + 44
    pill = Image.new("RGBA", slide.size, (0, 0, 0, 0))
    ImageDraw.Draw(pill).rounded_rectangle((W / 2 - tw / 2, y - 22, W / 2 + tw / 2, y + 22),
                                           radius=22, fill=(255, 255, 255, 45))
    slide.alpha_composite(pill)
    d = ImageDraw.Draw(slide)
    d.text((W // 2, y + 1), txt, font=df, fill="white", anchor="mm")
    if not n_pages:
        return
    # numéro de page
    pf = font(24)
    ptxt = f"{page}/{n_pages}"
    pw = d.textlength(ptxt, font=pf) + 26
    d.rounded_rectangle((W - 30 - pw, 26, W - 30, 62), radius=18, fill=YELLOW + (255,))
    d.text((W - 30 - pw / 2, 45), ptxt, font=pf, fill=(20, 12, 40), anchor="mm")


def code_pill(img, cy, size=34):
    """Pastille jaune « CODE CRÉATEUR : IMAN » centrée sur la hauteur cy."""
    d = ImageDraw.Draw(img)
    f_lbl, f_code = font(int(size * 0.8)), font(size + 8)
    lbl, code = "CODE CRÉATEUR : ", CREATOR_CODE
    tw = d.textlength(lbl, font=f_lbl) + d.textlength(code, font=f_code)
    pw, ph = tw + size * 1.6, size * 1.9
    x0, y0 = W / 2 - pw / 2, cy - ph / 2
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x0 + 4, y0 + 6, x0 + pw + 4, y0 + ph + 6), radius=ph / 2, fill=(0, 0, 0, 140))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((x0, y0, x0 + pw, y0 + ph), radius=ph / 2, fill=YELLOW + (255,),
                        outline=(255, 255, 255, 255), width=3)
    x = W / 2 - tw / 2
    d.text((x, cy + 2), lbl, font=f_lbl, fill=(40, 20, 80), anchor="lm")
    d.text((x + d.textlength(lbl, font=f_lbl), cy + 2), code, font=f_code, fill=(20, 10, 40), anchor="lm")


def footer(slide, text):
    d = ImageDraw.Draw(slide)
    d.text((W // 2, H - 24), text, font=font(24), fill=(200, 190, 255), anchor="mm")


def fetch_shop():
    """Attend (jusqu'à 20 min) que la boutique du jour soit en ligne juste après le reset."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    for _ in range(40):
        try:
            data = requests.get(SHOP_URL, timeout=60).json()["data"]
            if data["date"][:10] == today:
                return data
            print(f"Boutique encore à la date du {data['date'][:10]}, nouvelle tentative dans 30 s…")
        except Exception as e:
            print(f"API indisponible ({e}), nouvelle tentative dans 30 s…")
        time.sleep(30)
    sys.exit("La boutique du jour n'est pas disponible")


def grid_shape(n):
    """Colonnes x lignes adaptées au nombre d'objets d'une page (max 36)."""
    for cols, rows in ((3, 1), (3, 2), (3, 3), (4, 3), (4, 4), (5, 4), (5, 5), (6, 5), (6, 6)):
        if n <= cols * rows:
            return cols, rows
    return 6, 6


def grid_page(bg, day, page, n_pages, title, items, thumb, vbuck, shape=None, note=None):
    """Page en grille : titre, objets, pied de page avec le code créateur."""
    slide = bg.copy()
    header(slide, day, page, n_pages, title=title)
    cols, rows = shape or grid_shape(len(items))
    m, gap, top, bottom = 24, 10 if cols > 3 else 18, 160, 52 + (34 if note else 0)
    cw = (W - 2 * m - (cols - 1) * gap) // cols
    ch = min((H - top - bottom - (rows - 1) * gap) // rows, int(cw * 1.45))
    used = rows * ch + (rows - 1) * gap
    top += (H - top - bottom - used) // 2  # centre verticalement les petites grilles
    for k, it in enumerate(items[:cols * rows]):
        r, c = divmod(k, cols)
        paste_with_shadow(slide, draw_card(it, thumb(it), vbuck, cw, ch, big=cols <= 3),
                          (m + c * (cw + gap), top + r * (ch + gap)))
    if note:
        shadow_text(ImageDraw.Draw(slide), (W // 2, H - 70), note, font(24), "white", offset=2)
    footer(slide, f"CODE CRÉATEUR : {CREATOR_CODE}   •   {HANDLE}")
    return slide


CAT_TOP, CAT_BOTTOM, CAT_M, CAT_GAP, LABEL_H = 160, 52, 24, 10, 50


def paginate_sections(sections, cols, ch, n_pages):
    """Répartit les catégories en pages (une catégorie peut continuer sur la page suivante).
    Renvoie [[(titre, [rangées d'objets]), ...], ...] ou None si ça ne tient pas."""
    avail = H - CAT_TOP - CAT_BOTTOM
    pages, y = [[]], 0
    for title, lst in sections:
        rows = [lst[k:k + cols] for k in range(0, len(lst), cols)]
        block = None
        for row in rows:
            need = (LABEL_H if block is None else 0) + ch + CAT_GAP
            if y + need > avail:
                if len(pages) == n_pages:
                    return None
                pages.append([])
                y, block = 0, None
                need = LABEL_H + ch + CAT_GAP
            if block is None:
                block = (title, [])
                pages[-1].append(block)
            block[1].append(row)
            y += need
    return pages


def category_pages(items, n_pages):
    """Choisit la plus grande taille de carte qui fait tenir toute la boutique dans n_pages."""
    sections = [(c, [i for i in items if i["cat"] == c]) for c in CATEGORIES]
    sections = [(c, lst) for c, lst in sections if lst]
    for cols in (6, 7, 8):
        cw = (W - 2 * CAT_M - (cols - 1) * CAT_GAP) // cols
        for ch in range(int(cw * 1.35), int(cw * 0.95), -4):
            pages = paginate_sections(sections, cols, ch, n_pages)
            if pages:
                return pages, cols, cw, ch
    raise SystemExit("La boutique est trop grande pour le carrousel")


def section_label(slide, y, title, count):
    d = ImageDraw.Draw(slide)
    f = font(30)
    txt = f"{title}"
    tw = d.textlength(txt, font=f)
    d.rounded_rectangle((CAT_M, y + 6, CAT_M + tw + 36, y + LABEL_H - 6), radius=(LABEL_H - 12) // 2,
                        fill=YELLOW + (255,))
    d.text((CAT_M + 18, y + LABEL_H / 2 + 1), txt, font=f, fill=(20, 12, 40), anchor="lm")
    d.text((CAT_M + tw + 52, y + LABEL_H / 2 + 1), f"{count} objet{'s' if count > 1 else ''}",
           font=font(22), fill=(200, 190, 255), anchor="lm")
    d.line((CAT_M + tw + 60 + d.textlength(f"{count} objets", font=font(22)), y + LABEL_H / 2,
            W - CAT_M, y + LABEL_H / 2), fill=(95, 80, 160), width=2)


def category_page(bg, day, page, n_pages, blocks, counts, cols, cw, ch, thumb, vbuck):
    slide = bg.copy()
    header(slide, day, page, n_pages)
    y = CAT_TOP
    for title, rows in blocks:
        section_label(slide, y, title, counts[title])
        y += LABEL_H
        for row in rows:
            for c, it in enumerate(row):
                paste_with_shadow(slide, draw_card(it, thumb(it), vbuck, cw, ch),
                                  (CAT_M + c * (cw + CAT_GAP), y))
            y += ch + CAT_GAP
    footer(slide, f"CODE CRÉATEUR : {CREATOR_CODE}   •   {HANDLE}")
    return slide


def is_new(it, day):
    """Objet jamais sorti : bandeau « Nouveau » d'Epic, ou arrivé aujourd'hui en boutique
    alors qu'il a été ajouté au jeu il y a 7 jours max."""
    if it["is_new"]:
        return True
    if it["in_date"] != day:
        return False
    try:
        delta = (time.mktime(time.strptime(day, "%Y-%m-%d"))
                 - time.mktime(time.strptime(it["added"], "%Y-%m-%d"))) / 86400
        return 0 <= delta <= 7
    except ValueError:
        return False


def generate():
    data = fetch_shop()
    day = data["date"][:10]
    items = [p for p in (parse_entry(e) for e in data["entries"]) if p]
    items.sort(key=lambda i: -i["price"])  # les plus chers en premier
    total = len(items)
    new_items = [i for i in items if is_new(i, day)]
    arrivals = [i for i in items if i["in_date"] == day and not is_new(i, day)]
    print(f"{total} objets dans la boutique du {day} "
          f"({len(new_items)} nouveautés, {len(arrivals)} sorties du jour)")

    with ThreadPoolExecutor(16) as ex:
        thumbs = list(ex.map(lambda i: download(i["img"]) if i["img"] else None, items))
    by_id = {id(i): t for i, t in zip(items, thumbs)}
    thumb = lambda it: by_id.get(id(it))
    vbuck = download(data.get("vbuckIcon") or "https://fortnite-api.com/images/vbuck.png", 64)

    out = OUT / day
    out.mkdir(parents=True, exist_ok=True)
    bg = background()

    # Pages spéciales (seulement si elles ont du contenu), puis le catalogue complet
    specials = [(("LES", "NOUVEAUTÉS"), new_items), (("SORTIES", "DU JOUR"), arrivals)]
    specials = [(t, lst) for t, lst in specials if lst]
    catalog, cols, cw_cat, ch_cat = category_pages(items, MAX_SLIDES - 1 - len(specials))
    counts = {c: sum(1 for i in items if i["cat"] == c) for c in CATEGORIES}
    n_slides = 1 + len(specials) + len(catalog)

    # 1) Couverture
    slide = bg.copy()
    header(slide, day, 1, n_slides, big=True)
    m, gap, top = 36, 20, 320
    cw = (W - 2 * m - (HERO_COLS - 1) * gap) // HERO_COLS
    ch = (H - top - 150 - (HERO_ROWS - 1) * gap) // HERO_ROWS
    for k, it in enumerate(items[:HERO_N]):
        r, c = divmod(k, HERO_COLS)
        paste_with_shadow(slide, draw_card(it, thumb(it), vbuck, cw, ch, big=True),
                          (m + c * (cw + gap), top + r * (ch + gap)))
    d = ImageDraw.Draw(slide)
    parts = [f"{len(new_items)} NOUVEAUTÉS" if new_items else "",
             f"{len(arrivals)} SORTIES DU JOUR" if arrivals else "", f"{total} OBJETS"]
    shadow_text(d, (W // 2, H - 112), "  •  ".join(p for p in parts if p) + "  >>",
                font(30), "white", offset=2)
    code_pill(slide, H - 52, 30)
    slide.convert("RGB").save(out / "1.jpg", "JPEG", quality=92)

    # 2) Nouveautés et sorties du jour
    page = 1
    for title, lst in specials:
        page += 1
        extra = len(lst) - 36
        note = f"+ {extra} AUTRES DANS LA BOUTIQUE COMPLÈTE" if extra > 0 else None
        grid_page(bg, day, page, n_slides, title, lst[:36], thumb, vbuck, note=note) \
            .convert("RGB").save(out / f"{page}.jpg", "JPEG", quality=92)

    # 3) Boutique complète, rangée par catégorie
    for blocks in catalog:
        page += 1
        category_page(bg, day, page, n_slides, blocks, counts, cols, cw_cat, ch_cat, thumb, vbuck) \
            .convert("RGB").save(out / f"{page}.jpg", "JPEG", quality=92)

    # 3) Story verticale 9:16 (marges hautes/basses laissées libres pour l'interface Instagram)
    SH = 1920
    story = background(SH)
    header(story, day, 0, 0, big=True, y0=140)
    cols, rows, m, gap, top, bot = 3, 3, 36, 20, 470, 1460
    cw = (W - 2 * m - (cols - 1) * gap) // cols
    ch = (bot - top - (rows - 1) * gap) // rows
    for k in range(min(cols * rows, len(items))):
        r, c = divmod(k, cols)
        paste_with_shadow(story, draw_card(items[k], thumbs[k], vbuck, cw, ch, big=True),
                          (m + c * (cw + gap), top + r * (ch + gap)))
    d = ImageDraw.Draw(story)
    code_pill(story, 1545, 44)
    shadow_text(d, (W // 2, 1640), f"{total} OBJETS  •  TOUTE LA BOUTIQUE SUR {HANDLE}", font(32), "white", offset=2)
    story.convert("RGB").save(out / "story.jpg", "JPEG", quality=92)

    top5 = ", ".join(i["name"] for i in items[:5])
    caption = (f"🛒 Boutique Fortnite du {date_fr(day)} !\n\n"
               f"À ne pas manquer : {top5}…\n\n"
               + (f"🆕 {len(new_items)} nouveautés : {', '.join(i['name'] for i in new_items[:4])}…\n" if new_items else "")
               + (f"🔁 {len(arrivals)} sorties du jour\n" if arrivals else "")
               + ("\n" if new_items or arrivals else "") +
               "Glisse pour tout voir ➡️\n\n"
               f"💛 Soutiens-moi en utilisant le code créateur {CREATOR_CODE} dans la boutique !\n\n"
               "#fortnite #boutiquefortnite #fortniteshop #itemshop #fortnitefr #skin #EpicPartner")
    (out / "meta.json").write_text(json.dumps({"day": day, "slides": n_slides, "caption": caption},
                                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{n_slides} image(s) générée(s) dans {out}")


def ig(method, path, **params):
    params["access_token"] = "".join(os.environ["IG_ACCESS_TOKEN"].split())
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


def post(base_url, what="all"):
    """what : "all" (carrousel + story), "feed" (carrousel seul) ou "story" (story seule)."""
    day_dir = max(p for p in OUT.iterdir() if p.is_dir())
    meta = json.loads((day_dir / "meta.json").read_text(encoding="utf-8"))
    user = os.environ["IG_USER_ID"].strip()
    base = f"{base_url.rstrip('/')}/{meta['day']}"
    if what in ("all", "feed"):
        post_feed(user, [f"{base}/{i + 1}.jpg" for i in range(meta["slides"])], meta["caption"])
    if what in ("all", "story"):
        cid = ig("POST", f"{user}/media", image_url=f"{base}/story.jpg", media_type="STORIES")["id"]
        wait_ready(cid)
        res = ig("POST", f"{user}/media_publish", creation_id=cid)
        print(f"Story publiée ! id={res['id']}")


def post_feed(user, urls, caption):
    if len(urls) == 1:
        creation = ig("POST", f"{user}/media", image_url=urls[0], caption=caption)["id"]
    else:
        children = []
        for u in urls:
            cid = ig("POST", f"{user}/media", image_url=u, is_carousel_item="true")["id"]
            wait_ready(cid)
            children.append(cid)
        creation = ig("POST", f"{user}/media", media_type="CAROUSEL",
                      children=",".join(children), caption=caption)["id"]
    wait_ready(creation)
    res = ig("POST", f"{user}/media_publish", creation_id=creation)
    print(f"Publié sur Instagram ! id={res['id']}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "generate":
        generate()
    elif len(sys.argv) >= 3 and sys.argv[1] == "post":
        post(sys.argv[2], sys.argv[3] if len(sys.argv) >= 4 else "all")
    else:
        sys.exit(__doc__)
