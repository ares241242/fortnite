"""Automatisations supplémentaires à partir de fortnite-api.com.

Usage :
  python extras.py preview                # aperçu de tout dans out/preview/ (ne publie rien)
  python extras.py retours                # prépare le post « Retours rares » du jour (s'il y en a)
  python extras.py post-retours <base>    # le publie
  python extras.py carte <ancien_etat>    # regarde si la carte a changé
  python extras.py post-carte <base>      # publie la nouvelle carte (image dans <base>/<nom>)
  python extras.py actus <ancien_etat>    # repère les nouvelles actus du jeu
  python extras.py post-actus <base>      # les publie en story

Chaque fonction make_* renvoie une liste d'images (PIL) prêtes à publier :
  derniere_chance  story  : objets qui quittent la boutique cette nuit
  retours_rares    post   : objets de retour après une longue absence
  leaks            post   : nouveaux cosmétiques de la dernière mise à jour (carrousel)
  carte            post   : la carte de l'île avec ses lieux nommés
  actus            story  : les actualités du jeu (une story par actu)
  festival         story  : les pistes Festival arrivées aujourd'hui
  recap            post   : les skins partis de la boutique cette semaine
"""
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter

import shop
from shop import (W, H, YELLOW, font, fit_font, shadow_text, draw_card, background, paste_with_shadow,
                  header, code_pill, footer, grid_shape, date_fr, hex_rgb, mix, download)

API = "https://fortnite-api.com"
SH = 1920  # hauteur d'une story (9:16)
RARITY = {"common": (110, 110, 125), "uncommon": (60, 150, 40), "rare": (40, 120, 215),
          "epic": (140, 60, 210), "legendary": (215, 120, 40), "mythic": (200, 160, 30),
          "exotic": (60, 180, 200), "transcendent": (200, 60, 90)}


def api(path, **params):
    params.setdefault("language", "fr")
    r = requests.get(f"{API}{path}", params=params, timeout=120)
    r.raise_for_status()
    return r.json()["data"]


def days_between(a, b):
    return round((time.mktime(time.strptime(b[:10], "%Y-%m-%d"))
                  - time.mktime(time.strptime(a[:10], "%Y-%m-%d"))) / 86400)


MONTHS_SHORT = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def short_date(iso):
    y, m, d = iso[:10].split("-")
    return f"{int(d)} {MONTHS_SHORT[int(m) - 1]}"


def cosmetic_item(c, badge="", subtitle=None):
    """Carte pour un cosmétique hors boutique (pas de prix) : couleurs selon la rareté/série."""
    series = c.get("series") or {}
    cols = [hex_rgb(x) for x in series.get("colors") or []]
    base = cols[0] if cols else RARITY.get((c.get("rarity") or {}).get("value", ""), RARITY["common"])
    ims = c.get("images") or {}
    t = (c.get("type") or {})
    return {"name": c.get("name") or "?", "price": None,
            "subtitle": subtitle if subtitle is not None else (t.get("displayValue") or "").upper(),
            "img": ims.get("featured") or ims.get("icon") or ims.get("smallIcon"),
            "top": mix(base, (255, 255, 255), 0.25), "bottom": mix(base, (0, 0, 0), 0.35),
            "strip": mix(base, (0, 0, 0), 0.75), "badge": badge,
            "cat": shop.TYPE_CATEGORY.get(t.get("value"), "AUTRES")}


def load_thumbs(items):
    with ThreadPoolExecutor(16) as ex:
        thumbs = list(ex.map(lambda i: download(i["img"]) if i.get("img") else None, items))
    by_id = {id(i): t for i, t in zip(items, thumbs)}
    return lambda it: by_id.get(id(it))


def vbuck_icon():
    return download("https://fortnite-api.com/images/vbuck.png", 64)


def place_grid(img, items, thumb, vbuck, top, bottom, max_cols=6):
    """Grille adaptative centrée entre top et bottom."""
    cols, rows = grid_shape(len(items))
    cols = min(cols, max_cols)
    rows = -(-len(items) // cols)
    gap = 10 if cols > 3 else 18
    m = 24 if cols > 3 else 36
    cw = (W - 2 * m - (cols - 1) * gap) // cols
    ch = min((bottom - top - (rows - 1) * gap) // rows, int(cw * 1.45))
    y0 = top + (bottom - top - (rows * ch + (rows - 1) * gap)) // 2
    for k, it in enumerate(items):
        r, c = divmod(k, cols)
        n_row = min(cols, len(items) - r * cols)  # centre la dernière rangée
        x0 = m + (cols - n_row) * (cw + gap) // 2
        paste_with_shadow(img, draw_card(it, thumb(it), vbuck, cw, ch, big=cols <= 3 and ch >= 330),
                          (x0 + c * (cw + gap), y0 + r * (ch + gap)))


def tagline(img, y, text, size=34, color=YELLOW):
    shadow_text(ImageDraw.Draw(img), (W // 2, y), text, font(size), color, offset=3)


def story(title, day):
    img = background(SH)
    header(img, day, 0, 0, big=True, y0=140, title=title)
    return img


def post_page(title, day, page=0, n_pages=0):
    img = background()
    header(img, day, page, n_pages, title=title)
    return img


# ---------------------------------------------------------------- 1. Dernière chance
def make_derniere_chance(shop_data, max_items=24):
    day = shop_data["date"][:10]
    entries = [e for e in shop_data["entries"] if (e.get("outDate") or "")[:10] == day]
    items = sorted((p for p in map(shop.parse_entry, entries) if p), key=lambda i: -i["price"])
    if not items:
        return []
    img = story(("DERNIÈRE", "CHANCE"), day)
    tagline(img, 470, f"{len(items)} OBJETS QUITTENT LA BOUTIQUE CETTE NUIT")
    shown = items[:max_items]
    place_grid(img, shown, load_thumbs(shown), vbuck_icon(), 520, 1480)
    if len(items) > max_items:
        tagline(img, 1510, f"+ {len(items) - max_items} AUTRES", 28, "white")
    code_pill(img, 1590, 44)
    return [img]


# ---------------------------------------------------------------- 2. Retours rares
def shop_history():
    """id cosmétique -> liste des jours de présence en boutique (gros téléchargement, ~25 Mo)."""
    data = api("/v2/cosmetics/br", responseFlags=4)
    return {c["id"]: c.get("shopHistory") or [] for c in data}


def make_retours_rares(shop_data, history, min_days=180, max_items=12):
    day = shop_data["date"][:10]
    found = []
    for e in shop_data["entries"]:
        br = e.get("brItems") or []
        it = shop.parse_entry(e)
        if not it or not br or e.get("bundle"):
            continue
        start = (e.get("inDate") or day)[:10]
        before = [d for d in history.get(br[0]["id"], []) if d[:10] < start]
        if before:
            gap = days_between(before[-1], day)
            if gap >= min_days:
                it["badge"] = f"PAS VU DEPUIS {gap} JOURS"
                found.append((gap, it))
    found.sort(key=lambda g: -g[0])
    items = [it for _, it in found[:max_items]]
    lines = [f"• {it['name']} : pas vu depuis {gap} jours" for gap, it in found[:5]]
    if not items:
        return [], []
    img = post_page(("RETOURS", "RARES"), day)
    place_grid(img, items, load_thumbs(items), vbuck_icon(), 170, H - 60)
    footer(img, f"CODE CRÉATEUR : {shop.CREATOR_CODE}   •   {shop.HANDLE}")
    return [img], lines


# ---------------------------------------------------------------- 3. Leaks (nouveaux cosmétiques)
def make_leaks(max_pages=10):
    data = api("/v2/cosmetics/new")
    build = data.get("build", "")
    version = (re.search(r"Release-([\d.]+)", build) or [None, ""])[1]
    day = (data.get("date") or time.strftime("%Y-%m-%d"))[:10]
    raw = (data.get("items") or {}).get("br") or []
    raw = [c for c in raw if (c.get("name") or "").strip().lower() not in ("", "null", "tbd")
           and (c.get("images") or {}).get("icon")]  # objets pas encore finalisés par Epic
    items = [cosmetic_item(c) for c in raw]
    if not items:
        return [], version
    order = {c: k for k, c in enumerate(shop.CATEGORIES)}
    items.sort(key=lambda i: order.get(i["cat"], 99))
    thumb = load_thumbs(items)
    title = ("NOUVEAUX", "COSMÉTIQUES")

    cover = story_cover = background()
    header(cover, day, 1, 0, big=True, title=title)
    tagline(cover, 330, f"MISE À JOUR {version}  •  {len(items)} OBJETS DÉCOUVERTS", 30, "white")
    hero = [i for i in items if i["cat"] == "SKINS"][:6] or items[:6]
    place_grid(cover, hero, thumb, None, 370, H - 110, max_cols=3)
    code_pill(story_cover, H - 52, 30)
    pages, cols, cw, ch = shop.category_pages(items, max_pages - 1)
    counts = {c: sum(1 for i in items if i["cat"] == c) for c in shop.CATEGORIES}
    n = 1 + len(pages)
    out = [cover]
    for k, blocks in enumerate(pages, start=2):
        out.append(shop.category_page(background(), day, k, n, blocks, counts, cols, cw, ch, thumb, None,
                                      title=("NOUVEAUX", "COSMÉTIQUES")))
    return out, version


# ---------------------------------------------------------------- 4. Carte
def make_carte():
    data = api("/v1/map")
    day = time.strftime("%Y-%m-%d")
    img = post_page(("NOUVELLE", "CARTE"), day)
    m = download((data.get("images") or {}).get("pois"), 2048)
    if m:
        side = 1000
        m = m.convert("RGBA").resize((side, side), Image.LANCZOS)
        mask = Image.new("L", (side, side), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, side - 1, side - 1), radius=28, fill=255)
        m.putalpha(mask)
        paste_with_shadow(img, m, ((W - side) // 2, 175))
    names = sorted({p["name"] for p in data.get("pois") or [] if p.get("name") and "UnNamed" not in p["id"]})
    tagline(img, H - 120, f"{len(names)} LIEUX NOMMÉS", 32)
    footer(img, f"CODE CRÉATEUR : {shop.CREATOR_CODE}   •   {shop.HANDLE}")
    return [img]


# ---------------------------------------------------------------- 5. Actus du jeu
def wrap(draw, text, f, max_w):
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=f) <= max_w:
            line = test
        else:
            lines.append(line)
            line = word
    return lines + [line] if line else lines


def make_actus(max_stories=5):
    data = api("/v2/news/br")
    day = (data.get("date") or time.strftime("%Y-%m-%d"))[:10]
    return [make_actu_story(m, day) for m in (data.get("motds") or [])[:max_stories]]


def make_actu_story(motd, day):
    if True:
        img = story(("ACTU", "FORTNITE"), day)
        pic = download(motd.get("image"), 1920)
        y = 520
        if pic:
            pic = pic.convert("RGBA")
            pw = W - 72
            pic = pic.resize((pw, int(pic.height * pw / pic.width)), Image.LANCZOS)
            mask = Image.new("L", pic.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, pic.width - 1, pic.height - 1), radius=28, fill=255)
            pic.putalpha(mask)
            paste_with_shadow(img, pic, (36, y))
            y += pic.height + 50
        d = ImageDraw.Draw(img)
        for line in wrap(d, (motd.get("title") or "").upper(), font(56), W - 100)[:3]:
            shadow_text(d, (W // 2, y), line, font(56), YELLOW, offset=3)
            y += 66
        y += 20
        for line in wrap(d, motd.get("body") or "", font(34), W - 120)[:6]:
            d.text((W // 2, y), line, font=font(34), fill="white", anchor="mm")
            y += 44
        code_pill(img, 1590, 44)
        return img


# ---------------------------------------------------------------- 6. Pistes Festival
def make_festival(shop_data, max_items=12):
    day = shop_data["date"][:10]
    entries = [e for e in shop_data["entries"] if e.get("tracks") and not e.get("brItems")]
    today = [e for e in entries if (e.get("inDate") or "")[:10] == day] or entries[:max_items]
    items = []
    for e in today[:max_items]:
        t = e["tracks"][0]
        c1 = hex_rgb((e.get("colors") or {}).get("color1"), (60, 40, 140))
        items.append({"name": t.get("title") or "?", "price": e.get("finalPrice", 0),
                      "regular": e.get("regularPrice", 0), "img": t.get("albumArt"),
                      "top": mix(c1, (255, 255, 255), 0.2), "bottom": c1, "strip": mix(c1, (0, 0, 0), 0.7),
                      "badge": (t.get("artist") or "").upper()})
    if not items:
        return []
    img = story(("PISTES", "FESTIVAL"), day)
    tagline(img, 470, f"{len(items)} NOUVELLES PISTES AUJOURD'HUI")
    place_grid(img, items, load_thumbs(items), vbuck_icon(), 520, 1480, max_cols=3)
    code_pill(img, 1590, 44)
    return [img]


# ---------------------------------------------------------------- 7. Récap de la semaine
def make_recap(history_full, day, max_items=30):
    """Skins vus en boutique cette semaine qui n'y sont plus aujourd'hui."""
    week = {time.strftime("%Y-%m-%d", time.gmtime(time.mktime(time.strptime(day, "%Y-%m-%d")) - k * 86400))
            for k in range(1, 8)}
    gone = []
    for c in history_full:
        if (c.get("type") or {}).get("value") != "outfit":
            continue
        dates = {d[:10] for d in c.get("shopHistory") or []}
        seen = sorted(dates & week)
        if seen and day not in dates:
            gone.append((seen[-1], cosmetic_item(c, subtitle=f"PARTI LE {short_date(seen[-1]).upper()}")))
    order = {k: i for i, k in enumerate(RARITY)}
    gone.sort(key=lambda g: (g[0], -order.get("legendary", 0)), reverse=True)
    items = [it for _, it in gone[:max_items]]
    if not items:
        return []
    img = post_page(("PARTIS", "CETTE SEMAINE"), day)
    place_grid(img, items, load_thumbs(items), None, 170, H - 60)
    footer(img, f"{len(gone)} SKINS ONT QUITTÉ LA BOUTIQUE   •   {shop.HANDLE}")
    return [img]


# ---------------------------------------------------------------- Publication automatique
HASHTAGS = "#fortnite #boutiquefortnite #fortnitefr #fortniteshop #EpicPartner"


def post_single(url, caption):
    user = __import__("os").environ["IG_USER_ID"].strip()
    cid = shop.ig("POST", f"{user}/media", image_url=url, caption=caption)["id"]
    shop.wait_ready(cid)
    res = shop.ig("POST", f"{user}/media_publish", creation_id=cid)
    print(f"Publié sur Instagram ! id={res['id']}")


def cmd_retours():
    """Crée out/<jour>/retours.jpg + retours.txt (légende) s'il y a des retours rares aujourd'hui."""
    shop_data = shop.fetch_shop()
    day = shop_data["date"][:10]
    out = shop.OUT / day
    out.mkdir(parents=True, exist_ok=True)
    imgs, lines = make_retours_rares(shop_data, shop_history())
    if not imgs:
        print("Aucun retour rare aujourd'hui : pas de post.")
        return
    imgs[0].convert("RGB").save(out / "retours.jpg", "JPEG", quality=92)
    caption = (f"🔙 Retours rares dans la boutique Fortnite du {date_fr(day)} !\n\n"
               f"{chr(10).join(lines)}\n\n"
               f"💛 Soutiens-moi avec le code créateur {shop.CREATOR_CODE} dans la boutique !\n\n{HASHTAGS}")
    (out / "retours.txt").write_text(caption, encoding="utf-8")
    print("Retours rares prêts :", out / "retours.jpg")


def cmd_post_retours(base_url):
    day_dir = max(p for p in shop.OUT.iterdir() if p.is_dir() and p.name[:2] == "20")
    if not (day_dir / "retours.jpg").exists():
        print("Pas de retours rares aujourd'hui.")
        return
    post_single(f"{base_url.rstrip('/')}/{day_dir.name}/retours.jpg",
                (day_dir / "retours.txt").read_text(encoding="utf-8"))


def map_state():
    """Empreinte de la carte : lieux nommés et leur position (arrondie)."""
    data = api("/v1/map")
    pois = sorted(f"{p['name']}@{round(p['location']['x'], -3)},{round(p['location']['y'], -3)}"
                  for p in data.get("pois") or [] if p.get("name") and "UnNamed" not in p["id"])
    return __import__("hashlib").sha1("|".join(pois).encode()).hexdigest(), data


def cmd_carte(old_state_file):
    """Compare la carte au dernier état connu. Écrit out/carte/{state.txt, carte.jpg, carte.txt, decision}.
    decision = post (carte changée), init (premier passage : on mémorise sans publier) ou rien."""
    out = shop.OUT / "carte"
    out.mkdir(parents=True, exist_ok=True)
    old = Path(old_state_file).read_text().strip() if Path(old_state_file).exists() else ""
    state, data = map_state()
    decision = "rien" if state == old else ("init" if not old else "post")
    (out / "state.txt").write_text(state)
    (out / "decision").write_text(decision)
    print(f"Carte : {decision} (ancien={old[:8] or '-'} nouveau={state[:8]})")
    if decision == "post":
        name = f"carte_{state[:10]}.jpg"  # nom unique : évite les images en cache
        make_carte()[0].convert("RGB").save(out / name, "JPEG", quality=92)
        (out / "image").write_text(name)
        names = sorted({p["name"] for p in data.get("pois") or [] if p.get("name") and "UnNamed" not in p["id"]})
        caption = (f"🗺️ La carte Fortnite a changé !\n\n{len(names)} lieux nommés : {', '.join(names[:8])}"
                   f"{'…' if len(names) > 8 else ''}\n\n"
                   f"💛 Code créateur {shop.CREATOR_CODE} dans la boutique !\n\n{HASHTAGS} #fortnitemap")
        (out / "carte.txt").write_text(caption, encoding="utf-8")


def cmd_post_carte(base_url):
    out = shop.OUT / "carte"
    post_single(f"{base_url.rstrip('/')}/{(out / 'image').read_text().strip()}",
                (out / "carte.txt").read_text(encoding="utf-8"))


def motd_key(m):
    return m.get("id") or __import__("hashlib").sha1((m.get("title", "") + m.get("body", "")).encode()).hexdigest()


def cmd_actus(old_state_file, max_new=3):
    """Repère les actus jamais vues. Écrit out/actus/{state.txt, decision, a_publier, actu_*.jpg}.
    decision = post, init (premier passage : on mémorise sans publier) ou rien."""
    out = shop.OUT / "actus"
    out.mkdir(parents=True, exist_ok=True)
    p = Path(old_state_file)
    seen = set(p.read_text().split()) if p.exists() else set()
    data = api("/v2/news/br")
    day = (data.get("date") or time.strftime("%Y-%m-%d"))[:10]
    motds = data.get("motds") or []
    fresh = [m for m in motds if motd_key(m) not in seen]
    decision = "init" if not seen else ("post" if fresh else "rien")
    keep = list(dict.fromkeys([motd_key(m) for m in motds] + sorted(seen)))[:200]
    (out / "state.txt").write_text("\n".join(keep))
    (out / "decision").write_text(decision)
    names = []
    if decision == "post":
        for m in fresh[:max_new]:
            name = f"actu_{motd_key(m)[:12]}.jpg"
            make_actu_story(m, day).convert("RGB").save(out / name, "JPEG", quality=92)
            names.append(name)
    (out / "a_publier").write_text("\n".join(names))
    print(f"Actus : {decision} ({len(fresh)} nouvelle(s) sur {len(motds)})")


def cmd_post_actus(base_url):
    user = __import__("os").environ["IG_USER_ID"].strip()
    for name in (shop.OUT / "actus" / "a_publier").read_text().split():
        cid = shop.ig("POST", f"{user}/media", image_url=f"{base_url.rstrip('/')}/{name}", media_type="STORIES")["id"]
        shop.wait_ready(cid)
        res = shop.ig("POST", f"{user}/media_publish", creation_id=cid)
        print(f"Story actu publiée ! id={res['id']}")


# ---------------------------------------------------------------- Aperçu de tout
def save(images, name, out):
    for k, img in enumerate(images, start=1):
        p = out / (f"{name}.jpg" if len(images) == 1 else f"{name}_{k}.jpg")
        img.convert("RGB").save(p, "JPEG", quality=90)
        print("  ", p)


def preview():
    out = shop.OUT / "preview"
    out.mkdir(parents=True, exist_ok=True)
    shop_data = api("/v2/shop")
    day = shop_data["date"][:10]
    print("1. Dernière chance");   save(make_derniere_chance(shop_data), "1_derniere_chance_story", out)
    print("   (téléchargement de l'historique de la boutique…)")
    full = api("/v2/cosmetics/br", responseFlags=4)
    history = {c["id"]: c.get("shopHistory") or [] for c in full}
    print("2. Retours rares");     save(make_retours_rares(shop_data, history)[0], "2_retours_rares", out)
    print("3. Leaks");             save(make_leaks()[0], "3_leaks", out)
    print("4. Carte");             save(make_carte(), "4_carte", out)
    print("5. Actus");             save(make_actus(2), "5_actu_story", out)
    print("6. Festival");          save(make_festival(shop_data), "6_festival_story", out)
    print("7. Récap semaine");     save(make_recap(full, day), "7_recap_semaine", out)


if __name__ == "__main__":
    cmd = sys.argv[1:] + [""]
    if cmd[0] == "preview":
        preview()
    elif cmd[0] == "retours":
        cmd_retours()
    elif cmd[0] == "post-retours" and cmd[1]:
        cmd_post_retours(cmd[1])
    elif cmd[0] == "carte" and cmd[1]:
        cmd_carte(cmd[1])
    elif cmd[0] == "post-carte" and cmd[1]:
        cmd_post_carte(cmd[1])
    elif cmd[0] == "actus" and cmd[1]:
        cmd_actus(cmd[1])
    elif cmd[0] == "post-actus" and cmd[1]:
        cmd_post_actus(cmd[1])
    else:
        sys.exit(__doc__)
