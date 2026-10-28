"""Atvērto ADS-B datu avoti ar rezervēm (bez AI, bez atslēgām).

adsb.lol no GitHub Actions kopīgajām IP adresēm mēdz atbildēt HTTP 429 (pārāk daudz pieprasījumu).
Tādēļ katru vaicājumu mēģinām pēc kārtas: adsb.lol → airplanes.live → adsb.fi. Visiem ir tas pats readsb JSON formāts
(lauks "ac"; adsb.fi v2 dažkārt "aircraft"). Avots, kas atbildēja 429 vai kļūdu, šajā palaišanā uz COOL sekundēm tiek
izlaists, lai to nepārslogotu. Ievērojam ~1 pieprasījumu sekundē uz katru avotu (airplanes.live un adsb.fi noteikums).
"""
import time
import requests

UA = {"User-Agent": "robezas-sargs (+https://github.com/Toms0078/robezas-sargs-dati2)"}
COOL = 300
_cool = {}      # avots -> laiks, līdz kuram to neizmanto
_last = {}      # avots -> pēdējā pieprasījuma laiks
used = {}       # avots -> veiksmīgo atbilžu skaits (logam / lapai)
errors = []     # īsi kļūdu apraksti logam

POINT = {
    "adsb.lol": lambda la, lo, r: f"https://api.adsb.lol/v2/point/{la}/{lo}/{r}",
    "airplanes.live": lambda la, lo, r: f"https://api.airplanes.live/v2/point/{la}/{lo}/{min(r, 250)}",
    "adsb.fi": lambda la, lo, r: f"https://opendata.adsb.fi/api/v3/lat/{la}/lon/{lo}/dist/{min(r, 250)}",
}
MIL = {
    "adsb.lol": "https://api.adsb.lol/v2/mil",
    "airplanes.live": "https://api.airplanes.live/v2/mil",
    "adsb.fi": "https://opendata.adsb.fi/api/v2/mil",
}
ORDER = ["adsb.lol", "airplanes.live", "adsb.fi"]


def _get(src, url):
    now = time.time()
    if _cool.get(src, 0) > now: return None
    wait = 1.1 - (now - _last.get(src, 0))
    if wait > 0: time.sleep(wait)
    _last[src] = time.time()
    try:
        r = requests.get(url, headers=UA, timeout=30)
    except Exception as e:
        errors.append(f"{src}: {str(e)[:80]}"); _cool[src] = time.time() + 60; return None
    if r.status_code != 200:
        errors.append(f"{src}: HTTP {r.status_code}")
        _cool[src] = time.time() + (COOL if r.status_code in (429, 403, 503) else 60)
        return None
    try: j = r.json()
    except Exception:
        errors.append(f"{src}: nav JSON"); return None
    if "ac" not in j and isinstance(j.get("aircraft"), list): j["ac"] = j["aircraft"]
    if not isinstance(j.get("ac"), list):
        errors.append(f"{src}: nav lauka ac"); return None
    used[src] = used.get(src, 0) + 1
    return j


def point(la, lo, r):
    for src in ORDER:
        j = _get(src, POINT[src](la, lo, r))
        if j is not None: return j
    return None


def mil():
    for src in ORDER:
        j = _get(src, MIL[src])
        if j is not None: return j
    return None


def source_label():
    return " + ".join(s for s in ORDER if used.get(s)) or "nav"
