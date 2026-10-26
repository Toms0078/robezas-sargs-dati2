"""Militārās lidmašīnas virs Baltijas, Polijas, Ziemeļvalstīm (atklātie ADS-B dati no adsb.lol) — bez AI.

Rezultāts: data/rs/airchecks.json (jaunākā pārbaude pirmā; tieši to lasa Robežas sarga lapa), logs data/rs/airchecks.log.
Kategorijas: "tanker" (degvielas uzpilde), "nato" (citas NATO/sabiedroto militārās), "other" (Krievija/Baltkrievija militārās),
atsevišķi Krievijas civilie reisi (ruList). Klasifikācija pēc tipa, izsaukuma zīmes, reģistrācijas un adsb.lol militārā karodziņa.
"""
import json, math, os, re, sys, time, datetime as dt
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "rs", "airchecks.json")
LOG = os.path.join(HERE, "data", "rs", "airchecks.log")
UA = {"User-Agent": "robezas-sargs (+https://github.com/Toms0078/robezas-sargs-dati2)"}
POINTS = [(57.9, 25, 150), (55.2, 22.5, 150), (52.4, 21.6, 150), (52.6, 16.6, 150), (50.4, 19.2, 150),
          (57.5, 18.5, 120), (61.5, 25.5, 200), (60.5, 14.5, 200), (68.5, 24, 250)]
BBOX = (47.0, 71.5, 4.0, 42.0)  # lat min/max, lon min/max
KEEP = 168

TANKER_T = {"K35R", "K35E", "KC46", "KC10", "KC2", "KC39", "KC390", "MRTT", "A400"}  # A400 only when callsign says tanker
TANKER_CS = re.compile(r"^(LAGR|QID|PEARL|BOLT|ESSO|SHELL|GOLD|BLUE|NATO[0-9]|MMF|RRR[0-9]+|TARTN|ARCO|CLEAN|NCHO|PKSN|TEXAC)", re.I)
NATO_CS = re.compile(r"^(PLF|GAF|CEF|CFC|RCH|NATO|FORTE|JAKE|HOMER|DUKE|ASCOT|RRR|CTM|IAM|BAF|NAF|HKY|SVF|FNY|FAF|NOW|NORF|LYF|LAF|"
                     r"ESTAF|LTU|LVA|RFR|DAF|HAF|SHF|BRK|MMF|REACH|SAVER|SNAKE|ROCKY|SPAR|SAM|VALOR|CNV|NAVY|FISH|POLAR|TOPCAT)", re.I)
MIL_T = {"E3TF", "E3CF", "E7WT", "R135", "RC35", "P8", "Q4", "GLHK", "C17", "C30J", "C130", "C295", "A400", "B52", "B1", "F16", "F35",
         "EUFI", "RFAL", "GRIP", "S102", "GLF4", "EH10", "H60", "NH90", "PZ3T", "M28", "CN35", "P3", "E2", "B350", "U2", "RQ4", "MQ9"}
RU_MIL_T = {"IL76", "IL78", "TU34", "T134", "AN26", "AN12", "T214", "TU95", "T95", "TU22", "T160", "SU24", "SU27", "SU30", "SU34", "SU35",
            "A50", "IL20", "IL38", "AN30", "AN72", "AN74", "TU54", "T154"}
RU_CIV_CS = re.compile(r"^(AFL|SDM|PBD|AUL|SBI|SVR|UTA|RSY|NWS|KAR|SYL)\d", re.I)
RU_MIL_CS = re.compile(r"^(RFF|RSD)", re.I)

log_lines = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s); log_lines.append(s)

def ru_hex(h):
    try: v = int(h, 16)
    except Exception: return False
    return 0x140000 <= v <= 0x15FFFF or 0x510000 <= v <= 0x5103FF  # Russia, Belarus ICAO blocks

def get(url):
    for wait in (0, 5, 15):
        time.sleep(wait)
        try:
            r = requests.get(url, headers=UA, timeout=40)
            if r.status_code == 200: return r.json()
            if r.status_code == 404: return None  # nav ieraksta
            log(f"  {url}: HTTP {r.status_code}")
        except Exception as e:
            log(f"  {url}: {str(e)[:100]}")
    return None

def classify(a):
    t = (a.get("t") or "").upper(); cs = (a.get("flight") or "").strip().upper(); reg = (a.get("r") or "").upper()
    mil = bool((a.get("dbFlags") or 0) & 1)
    is_ru = reg.startswith("RA-") or reg.startswith("EW-") or ru_hex(a.get("hex", ""))
    if is_ru and (t in RU_MIL_T and not RU_CIV_CS.match(cs) or RU_MIL_CS.match(cs) or mil):
        return "other"
    if is_ru or RU_CIV_CS.match(cs):
        return "other" if t in RU_MIL_T else "ru"
    if t in TANKER_T - {"A400"} or (TANKER_CS.match(cs) and (mil or t in TANKER_T or t.startswith("A33"))) or (t.startswith("A33") and mil):
        return "tanker"
    if mil or NATO_CS.match(cs) and (t in MIL_T or not t) or t in MIL_T and mil:
        return "nato"
    return None

NOTE = {"tanker": "Degvielas uzpildes lidmašīna", "nato": "NATO/sabiedroto militārā lidmašīna",
        "other": "Krievijas/Baltkrievijas militārā lidmašīna"}
ROLE = {"E3TF": "AWACS", "E3CF": "AWACS", "E7WT": "AWACS", "R135": "izlūklidmašīna RC-135", "RC35": "izlūklidmašīna RC-135",
        "P8": "jūras patruļlidmašīna P-8", "Q4": "bezpilota izlūks Global Hawk", "GLHK": "bezpilota izlūks Global Hawk",
        "C17": "transportlidmašīna C-17", "C30J": "transportlidmašīna C-130J", "C130": "transportlidmašīna C-130",
        "A400": "transportlidmašīna A400M", "S102": "Zviedrijas izlūklidmašīna", "B52": "bumbvedējs B-52", "F35": "iznīcinātājs F-35",
        "F16": "iznīcinātājs F-16", "EUFI": "iznīcinātājs Eurofighter", "GRIP": "iznīcinātājs Gripen", "RFAL": "iznīcinātājs Rafale"}

def bearing(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2); x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

CITY = {"Moscow": "Maskava", "Saint Petersburg": "Sanktpēterburga", "St Petersburg": "Sanktpēterburga", "St. Petersburg": "Sanktpēterburga", "Sankt-Peterburg": "Sanktpēterburga", "Kaliningrad": "Kaļiņingrada",
        "Minsk": "Minska", "Murmansk": "Murmanska", "Sochi": "Soči", "Kazan": "Kazaņa", "Yekaterinburg": "Jekaterinburga"}

def off_route_km(p, a, b):
    """Attālums (km) no punkta p līdz lielā loka nogrieznim a–b."""
    R = 6371.0
    def dist(x, y):
        la1, lo1, la2, lo2 = map(math.radians, (x[0], x[1], y[0], y[1]))
        h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
        return 2 * R * math.asin(min(1, math.sqrt(h)))
    dab, dap, dpb = dist(a, b), dist(a, p), dist(p, b)
    if dab < 1: return dap
    xt = abs(math.asin(max(-1, min(1, math.sin(dap / R) * math.sin(math.radians(bearing(a, p) - bearing(a, b))))))) * R
    if dap + dpb > dab + 2 * max(xt, 1) + 600:  # punkts aiz nogriežņa galiem
        return min(dap, dpb)
    return xt

CACHE = os.path.join(HERE, "data", "rs", "routes_cache.json")
_cache, _new = None, [0]

def route(cs, pos, trk):
    """Plānotais maršruts pēc izsaukuma zīmes (adsbdb.com). Kešs 24 h, lai nepārslogotu avotu (pārbaude ik 10 min)."""
    global _cache
    if _cache is None:
        try: _cache = json.load(open(CACHE, encoding="utf-8"))
        except Exception: _cache = {}
    now = time.time()
    c = _cache.get(cs)
    if not c or now - c.get("t", 0) > (86400 if c.get("o") else 43200):
        if _new[0] >= 60: return None, None
        _new[0] += 1
        j = get(f"https://api.adsbdb.com/v0/callsign/{cs}")
        fr = (((j or {}).get("response") or {}).get("flightroute") or {}) if isinstance((j or {}).get("response"), dict) else {}
        o, d = fr.get("origin") or {}, fr.get("destination") or {}
        f = lambda a: {"code": a.get("iata_code") or a.get("icao_code"), "city": CITY.get(a.get("municipality"), a.get("municipality")),
                       "lat": a.get("latitude"), "lon": a.get("longitude")}
        c = {"t": now, "o": f(o), "d": f(d)} if o and d else {"t": now}
        _cache[cs] = c
    if not c.get("o"): return None, None
    d = c["d"]
    if trk is not None and d.get("lat") is not None:
        diff = abs((bearing(pos, (d["lat"], d["lon"])) - trk + 180) % 360 - 180)
        if diff > 100: return None, None  # novecojis ieraksts maršrutu datubāzē
    o = c["o"]
    if None not in (o.get("lat"), d.get("lat")) and off_route_km(pos, (o["lat"], o["lon"]), (d["lat"], d["lon"])) > 350:
        return None, None  # lidmašīna nav ne tuvu šim maršrutam — izsaukuma zīme izmantota citam reisam
    lv = lambda a: dict(a, city=CITY.get(a.get("city"), a.get("city")))
    return lv(c["o"]), lv(d)

def save_cache():
    if _cache is None: return
    now = time.time()
    keep = {k: v for k, v in _cache.items() if now - v.get("t", 0) < 2 * 86400}
    json.dump(keep, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

TRACE_N = [0, 0]  # mēģināti, izdevušies

def trace(hex_):
    """Lidojuma ceļš no adsb.lol (tie paši atvērtie ADS-B dati, ko rāda globe.adsb.lol karte): tikai pašreizējais lidojums, ≤ 80 punkti."""
    h = hex_.lower()
    TRACE_N[0] += 1
    j = None
    for kind in ("full", "recent"):
        try:
            r = requests.get(f"https://globe.adsb.lol/data/traces/{h[-2:]}/trace_{kind}_{h}.json", timeout=20,
                             headers=dict(UA, Referer="https://globe.adsb.lol/"))
            if r.status_code == 200:
                j = r.json(); break
            if TRACE_N[0] <= 2: log(f"  trase {h} {kind}: HTTP {r.status_code}")
        except Exception as e:
            if TRACE_N[0] <= 2: log(f"  trase {h} {kind}: {str(e)[:80]}")
    if not j or not j.get("trace"): return None
    base = float(j.get("timestamp") or 0)
    pts, last_t = [], None
    for q in j["trace"]:
        if len(q) < 3 or q[1] is None: continue
        t = base + float(q[0]); flags = q[6] if len(q) > 6 and isinstance(q[6], int) else 0
        if q[3] == "ground" or (last_t and t - last_t > 1800) or (flags & 2):
            pts = []  # jauns lidojums sākas
            if q[3] == "ground": last_t = t; continue
        pts.append((t, round(q[1], 3), round(q[2], 3))); last_t = t
    if len(pts) < 2: return None
    step = max(1, len(pts) // 80)
    pts = pts[::step] + ([pts[-1]] if (len(pts) - 1) % step else [])
    TRACE_N[1] += 1
    return [[la, lo, dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")] for t, la, lo in pts]


def thin(arr, t_now):
    """Pārbaudes ik 10 min. Glabā: pēdējās 6 h visas; 6–24 h viena stundā (ar sarakstu trasēm); 1–7 dienas viena stundā tikai skaitļi."""
    out, hours = [], set()
    for i, x in enumerate(arr):  # jaunākā pirmā; trases glabā tikai jaunākajā pārbaudē
        if i > 0:
            for k in ("list", "ruList"):
                for it in x.get(k) or []: it.pop("trace", None)
        try: t = dt.datetime.fromisoformat(str(x.get("checkedAt")).replace("Z", "+00:00"))
        except Exception: continue
        age = (t_now - t).total_seconds() / 3600
        if age > 24 * 7: continue
        if age <= 6: out.append(x); continue
        h = t.strftime("%Y%m%d%H")
        if h in hours: continue
        hours.add(h)
        out.append(x if age <= 24 else {k: v for k, v in x.items() if k not in ("list", "ruList")})
    return out


def main():
    t_now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    log(f"{t_now.isoformat()} lidmašīnu pārbaude")
    seen, ok_pts = {}, 0
    for la, lo, r in POINTS:
        j = get(f"https://api.adsb.lol/v2/point/{la}/{lo}/{r}")
        if not j: continue
        ok_pts += 1
        for a in j.get("ac") or []:
            if a.get("alt_baro") == "ground" or a.get("lat") is None: continue
            seen[a["hex"]] = a
    mj = get("https://api.adsb.lol/v2/mil")
    for a in (mj or {}).get("ac") or []:
        if a.get("lat") is None or a.get("alt_baro") == "ground": continue
        if BBOX[0] <= a["lat"] <= BBOX[1] and BBOX[2] <= a["lon"] <= BBOX[3]:
            seen.setdefault(a["hex"], a)
    log(f"apgabali: {ok_pts}/{len(POINTS)}, militāro saraksts: {'ok' if mj else 'nav'}, lidmašīnas gaisā: {len(seen)}")
    if not seen:
        log("nav datu — neko nesaglabāju"); open(LOG, "w").write("\n".join(log_lines) + "\n"); return
    lst, ru = [], []
    for a in seen.values():
        c = classify(a)
        if not c: continue
        alt = a.get("alt_baro"); alt = alt if isinstance(alt, (int, float)) else None
        item = {"hex": a["hex"].lower(), "callsign": (a.get("flight") or "").strip(), "type": a.get("t") or "", "altFt": alt,
                "lat": round(a["lat"], 4), "lon": round(a["lon"], 4), "track": a.get("track")}
        if a.get("r"): item["reg"] = a["r"]
        if item["callsign"]:
            fr, to = route(item["callsign"], (a["lat"], a["lon"]), a.get("track"))
            if fr: item["from"], item["to"] = fr, to
        # trace(): globe.adsb.lol trašu faili automātiskiem pieprasījumiem atbild 403 — neizmanto (ievērojam vietnes ierobežojumu)
        if c == "ru":
            ru.append(item)
        else:
            t = (a.get("t") or "").upper()
            item["cat"] = c
            item["note"] = NOTE[c] + (f" — {ROLE[t]}" if t in ROLE else (f" ({t})" if t else "")) + (f", reģ. {a.get('r')}" if a.get("r") else "")
            reg_u = str(a.get("r") or "").strip()
            if t in ("GLF4", "S102") and (item["callsign"].upper().startswith("SVF") or reg_u in ("102002", "102003")):
                # Zviedrijas S 102B Korpen (Gulfstream IV) — signālu izlūkošana; lido gar robežām, lai uztvertu radarus un sakarus
                item["note"] = NOTE[c] + " — Zviedrijas signālu izlūkošanas lidmašīna S 102B Korpen" + (f", reģ. {reg_u}" if reg_u else "")
            lst.append(item)
    order = {"tanker": 0, "other": 1, "nato": 2}
    lst.sort(key=lambda x: order[x["cat"]])
    # pilni maršruti no mil_tracks.py (ik ~30 s pozīcijas pēdējās 12 h) — tikai jaunākajai pārbaudei
    try: mt = json.load(open(os.path.join(HERE, "data", "rs", "miltracks.json"), encoding="utf-8")).get("tracks") or {}
    except Exception: mt = {}
    iso = lambda s_: dt.datetime.fromtimestamp(s_, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for x in lst:
        tr = (mt.get(x["hex"]) or {}).get("p") or []
        if len(tr) < 2: continue
        if len(tr) > 150: st = len(tr) / 150; tr = [tr[int(i * st)] for i in range(150)] + [tr[-1]]
        x["trace"] = [[q[0], q[1], iso(q[2])] for q in tr] + [[x["lat"], x["lon"], t_now.strftime("%Y-%m-%dT%H:%M:%SZ")]]
    n = {k: sum(1 for x in lst if x["cat"] == k) for k in order}
    note = (f"{len(seen)} lidmašīnas gaisā ({ok_pts}/{len(POINTS)} apgabali): militārās {len(lst)} — tankeri {n['tanker']}, "
            f"NATO {n['nato']}, Krievijas/Baltkrievijas {n['other']}; Krievijas civilie reisi {len(ru)}.")
    doc = {"checkedAt": t_now.strftime("%Y-%m-%dT%H:%M:%SZ"), "area": "Baltija, Polija, Baltijas jūra, Gotlande, Somija, Zviedrija, Norvēģija",
           "totalAirborne": len(seen), "tankers": n["tanker"], "natoMilitary": n["tanker"] + n["nato"], "otherMilitary": n["other"],
           "ruCivil": len(ru), "list": lst, "ruList": ru, "note": note, "source": "adsb.lol (GitHub Actions)"}
    try:
        arr = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        arr = []
    from zoneinfo import ZoneInfo
    doc["_id"] = t_now.astimezone(ZoneInfo("Europe/Riga")).strftime("%Y-%m-%d-%H%M")
    arr = thin([doc] + [x for x in arr if x.get("_id") != doc["_id"]], t_now)
    for old_doc in arr[1:]:
        for it in old_doc.get("list") or []: it.pop("trace", None)
    json.dump(arr, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    save_cache()
    log(note + f" Maršruti: {sum(1 for x in lst + ru if x.get('from'))}/{len(lst) + len(ru)}, jauni vaicājumi {_new[0]}. Trases: {TRACE_N[1]}/{TRACE_N[0]}.")
    for x in lst: log(f"  {x['cat']:6} {x['callsign']:9} {x['type']:5} {x['note']}")
    open(LOG, "w", encoding="utf-8").write("\n".join(log_lines) + "\n")

if __name__ == "__main__":
    main()
