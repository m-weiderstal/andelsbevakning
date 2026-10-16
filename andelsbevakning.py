#!/usr/bin/env python3
"""
Bevakar gamblingcabin.se/andelar-spela-tillsammans/ och skickar en push-notis
(via ntfy) för varje nytt andelsspel som dyker upp.

Vilka spelare/spel du vill ha notiser om styrs av två textfiler bredvid skriptet:
  spelare.txt  – ett namn per rad (t.ex. Timman, Bobby, Borg). Tom fil = alla spelare.
  spel.txt     – en spelform per rad (t.ex. Stryktipset, Powerplay). Tom fil = alla spel.
Rader som börjar med # ignoreras. Matchningen bryr sig inte om stora/små bokstäver
och räcker med en del av namnet ("klister" träffar "Mr Klisters").

Se vilka spelare som finns just nu:
  python3 andelsbevakning.py --lista

Första körningen sparar bara nuläget (inga notiser), sen notifieras bara nya spel.
"""
import html
import json
import os
import pathlib
import re
import sys
import urllib.parse
import urllib.request

URL = "https://gamblingcabin.se/andelar-spela-tillsammans/"
NTFY_TOPIC_URL = os.environ.get("NTFY_TOPIC_URL", "https://ntfy.sh/BYT-TILL-DITT-HEMLIGA-AMNE")

HERE = pathlib.Path(__file__).parent
STATE = HERE / "andelar_seen.json"
SPELARE_FIL = HERE / "spelare.txt"
SPEL_FIL = HERE / "spel.txt"

# Förkortningar som förekommer i speltitlarna, så att "Europatipset" i spel.txt även träffar "EU red 52kr"
SPEL_ALIAS = {
    "stryktipset": ["stryktips", "st "],
    "europatipset": ["europatips", "eu "],
    "topptipset": ["topptips", "tt "],
    "powerplay": ["powerplay", "pp "],
    "bomben": ["bomben"],
    "big9": ["big9", "big 9"],
    "challenge": ["challenge"],
}

PATTERN = re.compile(
    r'<img[^>]+alt="([^"]*)"'                                                # bild = ny spelargrupp
    r'|<a[^>]+href="(https://gamblingcabin\.se/and/[^"]+)"[^>]*>(.*?)</a>',  # andelslänk
    re.S | re.I,
)


def fetch() -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (andelsbevakning)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def clean(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\s+", " ", s).strip()


def bettarnamn(alt: str) -> str:
    """'Andelar-Adam-Perleroth' -> 'Adam Perleroth', 'Andelar Timman 2024' -> 'Timman'."""
    s = clean(alt).replace("-", " ").replace("_", " ")
    s = re.sub(r"(?i)\b(andelar|gambling cabin|silhouette|ny|alla|jpg|20\d\d)\b|jpg$", " ", s)
    s = re.sub(r"(?i)stryktipsetjpg", "Stryktipset", s)
    return re.sub(r"\s+", " ", s).strip()


def parse(page: str) -> dict:
    items, bettare = {}, ""
    for m in PATTERN.finditer(page):
        if m.group(1) is not None:
            bettare = bettarnamn(m.group(1))
            continue
        href, title = m.group(2), clean(m.group(3))
        if not title:
            continue
        # Nyckel = länk + titel, eftersom samma länk-slug ibland återanvänds med ny text
        items[f"{href}|{title}"] = {"href": href, "title": title, "bettare": bettare}
    return items


def las_lista(fil: pathlib.Path) -> list:
    if not fil.exists():
        return []
    rader = (r.strip().lower() for r in fil.read_text("utf-8").splitlines())
    return [r for r in rader if r and not r.startswith("#")]


def matchar(item: dict, spelare: list, spel: list) -> bool:
    text = f" {item['bettare']} {item['title']} ".lower()
    if spelare and not any(s in text for s in spelare):
        return False
    if spel:
        nycklar = [a for s in spel for a in SPEL_ALIAS.get(s.replace(" ", ""), [s])]
        if not any(n in text for n in nycklar):
            return False
    return True


def notify(item: dict) -> None:
    params = urllib.parse.urlencode({
        "title": f"Nytt andelsspel: {item['bettare'] or 'okänd'}",
        "click": item["href"],
        "tags": "moneybag",
        "priority": "high",
    })
    body = f"{item['title']}\n{item['href']}".encode("utf-8")
    urllib.request.urlopen(urllib.request.Request(f"{NTFY_TOPIC_URL}?{params}", data=body), timeout=15)


def lista(current: dict) -> None:
    per_spelare = {}
    for v in current.values():
        per_spelare.setdefault(v["bettare"] or "(okänd)", []).append(v["title"])
    for namn, spel in per_spelare.items():
        print(f"{namn}:")
        for t in spel:
            print(f"   - {t}")


def main() -> None:
    current = parse(fetch())
    if not current:
        print("Varning: hittade inga andelar – har sidan ändrat struktur?")
        return

    if "--lista" in sys.argv:
        lista(current)
        return

    first_run = not STATE.exists()
    seen = set() if first_run else set(json.loads(STATE.read_text("utf-8")))
    spelare, spel = las_lista(SPELARE_FIL), las_lista(SPEL_FIL)

    new = [v for k, v in current.items() if k not in seen]
    if not first_run:
        for item in new:
            if matchar(item, spelare, spel):
                notify(item)
                print("Notis:", item["bettare"], "|", item["title"])
            else:
                print("Ny men filtrerad bort:", item["bettare"], "|", item["title"])

    # Alla spel sparas som sedda (även bortfiltrerade), så att en ändring i filtren
    # inte plötsligt skickar notiser om gamla spel.
    STATE.write_text(json.dumps(sorted(seen | set(current)), ensure_ascii=False), "utf-8")
    if first_run:
        print(f"Första körningen: sparade {len(current)} spel, inga notiser skickade.")


if __name__ == "__main__":
    main()
