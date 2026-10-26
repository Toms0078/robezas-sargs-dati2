"""Lidmašīnu tipu foto Robežas sargam (Wikimedia Commons, brīvas licences) — bez AI.

Nolasa data/rs/airchecks.json, atrod lidmašīnu tipus (ICAO kods, piem. K35R), kuriem vēl nav foto,
atrod tipa rakstu angļu Wikipedia, paņem tā galveno attēlu no Wikimedia Commons ar autoru un licenci,
samazina līdz ~520 px JPEG un saglabā data/rs/typephotos/<TIPS>.json:
  {"img": "data:image/jpeg;base64,...", "name", "author", "license", "file", "fetchedAt"}
Lapa nedrīkst ielādēt ārējus attēlus (CSP), tāpēc attēls ir iebūvēts kā data URI.
Hourly Claude uzdevums "Baltijas debesis" (3b. solis) pārkopē jaunos failus artifact datubāzē (kolekcija "photos").
Lieto: python type_photos.py [--test] [--max N]
"""
import base64, datetime as dt, html, io, json, os, re, sys, time
import requests
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
AIR = os.path.join(HERE, "data", "rs", "airchecks.json")
OUTDIR = os.path.join(HERE, "data", "rs", "typephotos")
LOG = os.path.join(HERE, "data", "rs", "typephotos.log")
MISS = os.path.join(OUTDIR, "_missing.json")
UA = {"User-Agent": "robezas-sargs/1.0 (https://github.com/Toms0078/robezas-sargs-dati2; type photos for a dashboard)"}

# ICAO tipa kods -> angļu Wikipedia raksts
TYPES = {
    # degvielas uzpilde, transports, izlūki
    "K35R": "Boeing KC-135 Stratotanker", "K35E": "Boeing KC-135 Stratotanker", "KC46": "Boeing KC-46 Pegasus",
    "KC10": "McDonnell Douglas KC-10 Extender", "A332": "Airbus A330", "A333": "Airbus A330", "A339": "Airbus A330neo",
    "MRTT": "Airbus A330 MRTT", "A400": "Airbus A400M Atlas", "C17": "Boeing C-17 Globemaster III",
    "C30J": "Lockheed Martin C-130J Super Hercules", "C130": "Lockheed C-130 Hercules", "C295": "Airbus C-295",
    "CN35": "CASA/IPTN CN-235", "KC39": "Embraer C-390 Millennium", "E3TF": "Boeing E-3 Sentry", "E3CF": "Boeing E-3 Sentry",
    "E7WT": "Boeing E-7 Wedgetail", "R135": "Boeing RC-135", "RC35": "Boeing RC-135", "P8": "Boeing P-8 Poseidon",
    "P3": "Lockheed P-3 Orion", "Q4": "Northrop Grumman RQ-4 Global Hawk", "RQ4": "Northrop Grumman RQ-4 Global Hawk",
    "GLHK": "Northrop Grumman RQ-4 Global Hawk", "MQ9": "General Atomics MQ-9 Reaper", "U2": "Lockheed U-2",
    "E2": "Northrop Grumman E-2 Hawkeye", "GLF4": "Gulfstream IV", "GLF5": "Gulfstream V", "GLF6": "Gulfstream G650",
    "B350": "Beechcraft King Air", "B52": "Boeing B-52 Stratofortress", "B1": "Rockwell B-1 Lancer",
    "S102": "Saab 340", "SF34": "Saab 340", "PC12": "Pilatus PC-12", "PC24": "Pilatus PC-24", "M28": "PZL M28 Skytruck",
    "LJ35": "Learjet 35", "C560": "Cessna Citation V", "C680": "Cessna Citation Sovereign", "FA7X": "Dassault Falcon 7X",
    "F900": "Dassault Falcon 900", "F2TH": "Dassault Falcon 2000", "CL60": "Bombardier Challenger 600 series",
    "GL5T": "Bombardier Global 5000", "GLEX": "Bombardier Global Express",
    # iznīcinātāji, helikopteri
    "F16": "General Dynamics F-16 Fighting Falcon", "F35": "Lockheed Martin F-35 Lightning II", "F15": "McDonnell Douglas F-15 Eagle",
    "F18": "McDonnell Douglas F/A-18 Hornet", "EUFI": "Eurofighter Typhoon", "RFAL": "Dassault Rafale", "GRIP": "Saab JAS 39 Gripen",
    "H60": "Sikorsky UH-60 Black Hawk", "NH90": "NHIndustries NH90", "EH10": "AgustaWestland AW101", "H47": "Boeing CH-47 Chinook",
    "A139": "AgustaWestland AW139", "EC35": "Eurocopter EC135", "EC45": "Eurocopter EC145", "PZ3T": "PZL-130 Orlik",
    # Krievija/Baltkrievija
    "IL76": "Ilyushin Il-76", "IL78": "Ilyushin Il-78", "A50": "Beriev A-50", "IL20": "Ilyushin Il-20M", "IL38": "Ilyushin Il-38",
    "AN26": "Antonov An-26", "AN12": "Antonov An-12", "AN72": "Antonov An-72", "AN74": "Antonov An-72", "AN30": "Antonov An-30",
    "T134": "Tupolev Tu-134", "TU34": "Tupolev Tu-134", "T154": "Tupolev Tu-154", "TU54": "Tupolev Tu-154", "T214": "Tupolev Tu-204",
    "T204": "Tupolev Tu-204", "TU95": "Tupolev Tu-95", "T95": "Tupolev Tu-95", "TU22": "Tupolev Tu-22M", "T160": "Tupolev Tu-160",
    "SU24": "Sukhoi Su-24", "SU27": "Sukhoi Su-27", "SU30": "Sukhoi Su-30", "SU34": "Sukhoi Su-34", "SU35": "Sukhoi Su-35",
    "SU95": "Sukhoi Superjet 100", "IL96": "Ilyushin Il-96", "MI8": "Mil Mi-8",
    # pasažieru
    "A319": "Airbus A319", "A320": "Airbus A320 family", "A321": "Airbus A321", "A20N": "Airbus A320neo family",
    "A21N": "Airbus A321neo", "A359": "Airbus A350", "A388": "Airbus A380", "B737": "Boeing 737 Next Generation",
    "B738": "Boeing 737 Next Generation", "B739": "Boeing 737 Next Generation", "B38M": "Boeing 737 MAX", "B39M": "Boeing 737 MAX",
    "B752": "Boeing 757", "B763": "Boeing 767", "B772": "Boeing 777", "B77W": "Boeing 777", "B788": "Boeing 787 Dreamliner",
    "B789": "Boeing 787 Dreamliner", "E190": "Embraer E-Jet family", "E195": "Embraer E-Jet family", "E75L": "Embraer E-Jet family",
    "BCS3": "Airbus A220", "BCS1": "Airbus A220", "AT76": "ATR 72", "AT75": "ATR 72", "DH8D": "De Havilland Canada Dash 8",
    "CRJ9": "Bombardier CRJ900",
    "C27J": "Alenia C-27J Spartan", "MF17": "Saab MFI-15 Safari", "L410": "Let L-410 Turbolet", "A109": "AgustaWestland AW109",
    "D228": "Dornier 228", "B733": "Boeing 737 Classic", "B762": "Boeing 767",
}
LICENSE_OK = re.compile(r"^(CC0|CC BY|CC-BY|CC BY-SA|CC-BY-SA|Public domain|PD|GFDL|Attribution)", re.I)

log_lines = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s); log_lines.append(s)

def jget(url, params):
    for wait in (0, 4, 12):
        time.sleep(wait)
        try:
            r = requests.get(url, params=params, headers=UA, timeout=30)
            if r.status_code == 200: return r.json()
            log(f"  {url}: HTTP {r.status_code}")
        except Exception as e:
            log(f"  {url}: {str(e)[:120]}")
    return None

def strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()

def lead_image(title):
    """Wikipedia raksta galvenā attēla faila nosaukums."""
    d = jget("https://en.wikipedia.org/w/api.php", {"action": "query", "format": "json", "prop": "pageimages",
             "piprop": "name", "redirects": 1, "titles": title})
    if not d: return None
    for p in (d.get("query", {}).get("pages", {}) or {}).values():
        if p.get("pageimage"): return p["pageimage"]
    return None

def commons_info(fname):
    d = jget("https://commons.wikimedia.org/w/api.php", {"action": "query", "format": "json", "prop": "imageinfo",
             "iiprop": "url|extmetadata|mime", "iiurlwidth": 640, "titles": "File:" + fname})
    if not d: return None
    for p in (d.get("query", {}).get("pages", {}) or {}).values():
        ii = (p.get("imageinfo") or [None])[0]
        if not ii: return None
        md = ii.get("extmetadata") or {}
        return {"thumb": ii.get("thumburl") or ii.get("url"), "page": ii.get("descriptionurl"), "mime": ii.get("mime", ""),
                "author": strip_html((md.get("Artist") or {}).get("value"))[:120] or "nezināms",
                "license": strip_html((md.get("LicenseShortName") or {}).get("value"))[:60]}
    return None

def to_data_uri(url):
    r = requests.get(url, headers=UA, timeout=40); r.raise_for_status()
    im = Image.open(io.BytesIO(r.content)).convert("RGB")
    im.thumbnail((520, 360))
    for q in (72, 62, 52):
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
        if buf.tell() <= 60_000: break
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

def main():
    test = "--test" in sys.argv
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 20
    os.makedirs(OUTDIR, exist_ok=True)
    try: checks = json.load(open(AIR, encoding="utf-8"))
    except Exception as e: log("Nevar nolasīt airchecks.json:", e); checks = []
    seen = {}
    for c in checks:
        for a in (c.get("list") or []) + (c.get("ruList") or []):
            t = str(a.get("type") or "").upper().strip()
            if t: seen[t] = seen.get(t, 0) + 1
    try: missing = json.load(open(MISS, encoding="utf-8"))
    except Exception: missing = {}
    todo = [t for t, _ in sorted(seen.items(), key=lambda x: -x[1])
            if not os.path.exists(os.path.join(OUTDIR, t + ".json")) and t not in missing]
    log(f"{dt.datetime.utcnow():%Y-%m-%d %H:%M}Z tipi datos: {len(seen)}, bez foto: {len(todo)}")
    done = 0
    for t in todo[:mx]:
        title = TYPES.get(t)
        if not title:
            log(f"  {t}: nav zināma raksta (pievieno TYPES)"); missing[t] = "nav kartēts"; continue
        fname = lead_image(title)
        if not fname: log(f"  {t}: rakstam '{title}' nav attēla"); missing[t] = "nav attēla"; continue
        info = commons_info(fname)
        if not info or not info.get("thumb"): log(f"  {t}: nav Commons info {fname}"); continue
        if not LICENSE_OK.match(info["license"] or ""):
            log(f"  {t}: licence '{info['license']}' nav droši brīva — izlaižu"); missing[t] = "licence"; continue
        if test: log(f"  TEST {t}: {title} | {fname} | {info['license']} | {info['author']}"); continue
        try: img = to_data_uri(info["thumb"])
        except Exception as e: log(f"  {t}: attēla kļūda {str(e)[:100]}"); continue
        doc = {"img": img, "name": title, "author": info["author"], "license": info["license"],
               "file": info["page"], "fetchedAt": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
        json.dump(doc, open(os.path.join(OUTDIR, t + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
        log(f"  {t}: OK {title} ({len(img)//1024} KB, {info['license']})"); done += 1
        time.sleep(1)
    json.dump(missing, open(MISS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"Saglabāti {done} jauni foto.")
    open(LOG, "w", encoding="utf-8").write("\n".join(log_lines) + "\n")

if __name__ == "__main__":
    main()
