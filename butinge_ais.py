"""Būtiņģes bojas AIS monitorings.

Pieslēdzas aisstream.io, dažas minūtes klausās AIS ziņas Baltijas jūrā
un saglabā:
  data/butinge/latest.json  – kuģi pie bojas un kuģi ar galamērķi Būtiņģe
  data/butinge/calls.jsonl  – notikumi: pietauvojās / atstāja boju (ar iegrimi)

DWT un maksimālo iegrimi AIS nepārraida. Ja kuģis ir data/butinge/vessels.json
(atslēga = IMO), izmanto tos datus, citādi novērtē pēc kuģa garuma.

Palaišana:  AISSTREAM_API_KEY=... python butinge_ais.py [sekundes]
"""
import asyncio
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).parent / "data" / "butinge"
LATEST = DATA / "latest.json"
CALLS = DATA / "calls.jsonl"
VESSELS = DATA / "vessels.json"

# Aptuvenā bojas vieta (~7,5 km no krasta). Precīzāko vietu skripts
# iemācās pats no kuģiem, kas pie tās stāv (learned_buoy latest.json).
BUOY = (56.062, 20.958)
MOORED_KM = 1.5          # tuvāk par šo un gandrīz nekustas = pie bojas
AREA_KM = 40             # tuvāk par šo un stāv = gaida Būtiņģes reidā
FORGET_DAYS = 5          # kuģi, kas nav dzirdēti tik ilgi, izmet

# Visa Baltija, Dānijas šaurumi, Skagerraks un Ziemeļjūras dienvidi
BOXES = [[[53.0, 3.0], [66.0, 31.0]]]   # Baltija + pieejas: visas ziņas
WORLD = [[[-90.0, -180.0], [90.0, 180.0]]]  # ārpus reģiona: tikai kuģi ar galamērķi Baltijas valstīs


def in_region(lat, lon):
    return lat is not None and 53.0 <= lat <= 66.0 and 3.0 <= lon <= 31.0
DEST_RE = re.compile(r"BUT[I1]NG|LT\s*BOT|BUTINGE")
MOORED_STATUS = {5}      # AIS: 5 = pietauvots
ANCHOR_STATUS = {1}      # AIS: 1 = noenkurots


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def km(a, b):
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def dest_matches(dest):
    return bool(dest) and bool(DEST_RE.search(dest.upper()))


def est_dwt(length):
    """Tankkuģa DWT novērtējums pēc garuma (m)."""
    if not length:
        return None
    for lim, dwt in ((50, 600), (80, 2500), (110, 6000), (150, 12000), (185, 35000), (200, 50000), (235, 75000),
                     (255, 110000), (285, 160000)):
        if length <= lim:
            return dwt
    return 300000


def est_max_draught(dwt):
    if not dwt:
        return None
    for lim, t in ((140000, 16.0), (100000, 14.8), (70000, 13.6), (45000, 12.2), (25000, 10.5)):
        if dwt >= lim:
            return t
    return 8.5


def load_estimate(ship, vessels):
    """Papildina kuģi ar DWT, maks. iegrimi un noslodzes novērtējumu."""
    ref = vessels.get(str(ship.get("imo") or ""), {})
    dwt = ref.get("dwt") or est_dwt(ship.get("length"))
    tmax = ref.get("max_draught") or est_max_draught(dwt)
    ship["dwt"] = dwt
    ship["dwt_source"] = "registrs" if ref.get("dwt") else ("novērtēts" if dwt else None)
    ship["max_draught"] = tmax
    t = ship.get("draught") or None
    ship["draught"] = t
    if t and tmax:
        tb = 0.45 * tmax                     # balasta iegrime ≈ 45 % no maksimālās
        f = max(0.0, min(1.0, (t - tb) / (tmax - tb)))
        ship["load_pct"] = round(f * 100)
        ship["empty_pct"] = 100 - ship["load_pct"]
        ship["cargo_t_est"] = round(f * dwt * 0.95 / 100) * 100 if dwt else None
    else:
        ship["load_pct"] = ship["empty_pct"] = ship["cargo_t_est"] = None
    return ship


# Kravas novērtējums. AIS kravu nepārraida, tāpēc šis ir minējums pēc ostas,
# kuģa izmēra, nosaukuma un iegrimes. Dīzeli no benzīna atšķirt nevar.
PORT_CARGO = {
    "butinge": "jēlnafta (ORLEN Mažeiķu rūpnīcai)",
}


def cargo_guess(ship, port_id=None):
    name = (ship.get("name") or "").upper()
    length = ship.get("length") or 0
    why = []
    if re.search(r"\b(LPG|LNG|GAS)\b", name):
        kind = "sašķidrināta gāze (LPG/LNG)"
        why.append("nosaukumā gāze")
    elif re.search(r"CHEM|ESSBERGER|STOLT|ODFJELL", name):
        kind = "ķīmikālijas vai naftas produkti"
        why.append("nosaukums norāda uz ķīmikāliju tankkuģi")
    elif port_id in PORT_CARGO:
        kind = PORT_CARGO[port_id]
        why.append("Būtiņģe ir jēlnaftas terminālis")
    elif length >= 235:
        kind = "visticamāk jēlnafta"
        why.append(f"liels tankkuģis ({length} m, Aframax+)")
    elif length >= 120:
        kind = "naftas produkti: dīzelis, benzīns vai aviodegviela"
        why.append(f"produktu tankkuģa izmērs ({length} m)")
    elif 0 < length < 60:
        kind = "ostas vai bunkurēšanas tankkuģis (degviela citiem kuģiem)"
        why.append(f"ļoti mazs tankkuģis ({length} m)")
    elif length > 0:
        kind = "naftas produkti vai ķīmikālijas (mazs piekrastes tankkuģis)"
        why.append(f"mazs tankkuģis ({length} m)")
    else:
        kind = "nav zināms"
    lp = ship.get("load_pct")
    if lp is not None:
        if lp >= 70:
            state = "pilns"
        elif lp <= 25:
            state = "tukšs / balastā"
            if port_id:
                state += " — brauc iekraut"
        else:
            state = "daļēji pilns"
        why.append(f"iegrime {ship.get('draught')} m")
    else:
        state = None
    ship["cargo_guess"] = kind
    ship["cargo_state"] = state
    ship["cargo_basis"] = ", ".join(why)
    return ship


def status_of(ship, buoy):
    pos = ship.get("lat"), ship.get("lon")
    if pos[0] is None:
        return "ceļā"
    d = km(pos, buoy)
    ship["dist_buoy_km"] = round(d, 2)
    slow = (ship.get("sog") or 0) < 1.0
    if d <= MOORED_KM and (slow or ship.get("nav_status") in MOORED_STATUS):
        return "pie_bojas"
    if d <= AREA_KM and (slow or ship.get("nav_status") in ANCHOR_STATUS):
        return "gaida"
    return "ceļā"


def eta_str(eta):
    if not eta or not eta.get("Month") or not eta.get("Day"):
        return None
    if eta["Month"] > 12 or eta["Day"] > 31 or eta.get("Hour", 24) > 23:
        return None
    return f"{eta['Day']:02d}.{eta['Month']:02d} {eta['Hour']:02d}:{eta.get('Minute', 0):02d} UTC"


def process(messages, state, vessels, now):
    """Tīra funkcija: apstrādā AIS ziņas un atgriež (jaunais stāvoklis, notikumi)."""
    buoy = tuple(state.get("learned_buoy") or BUOY)
    old = {s["mmsi"]: s for s in state.get("ships", [])}
    static, pos = {}, {}
    for m in messages:
        meta = m.get("MetaData", {})
        mmsi = meta.get("MMSI")
        if not mmsi:
            continue
        body = m.get("Message", {})
        if "ShipStaticData" in body:
            static[mmsi] = (body["ShipStaticData"], meta)
        for k in ("PositionReport", "StandardClassBPositionReport"):
            if k in body:
                pos[mmsi] = (body[k], meta)

    ships = {k: dict(v) for k, v in old.items()}
    for mmsi, (s, meta) in static.items():
        dest = (s.get("Destination") or "").strip()
        near = False
        if mmsi in pos:
            p = pos[mmsi][0]
            near = km((p["Latitude"], p["Longitude"]), buoy) <= AREA_KM
        tanker = 80 <= (s.get("Type") or 0) <= 89
        if not (dest_matches(dest) or mmsi in ships or (near and tanker)):
            continue
        sh = ships.setdefault(mmsi, {"mmsi": mmsi, "first_seen": iso(now)})
        dim = s.get("Dimension") or {}
        length = (dim.get("A") or 0) + (dim.get("B") or 0)
        sh.update({
            "name": (s.get("Name") or meta.get("ShipName") or "").strip() or sh.get("name"),
            "imo": s.get("ImoNumber") or sh.get("imo"),
            "callsign": (s.get("CallSign") or "").strip() or sh.get("callsign"),
            "ais_type": s.get("Type"),
            "length": length or sh.get("length"),
            "beam": ((dim.get("C") or 0) + (dim.get("D") or 0)) or sh.get("beam"),
            "destination": dest,
            "dest_match": dest_matches(dest),
            "eta": eta_str(s.get("Eta")),
            "draught": s.get("MaximumStaticDraught") or sh.get("draught"),
            "static_time": iso(now),
        })

    for mmsi, (p, meta) in pos.items():
        lat, lon = p.get("Latitude"), p.get("Longitude")
        if lat is None or abs(lat) > 90:
            continue
        if mmsi not in ships:
            # kuģis bez statiskajiem datiem, bet tieši pie bojas
            # (ja statiskie dati bija un kuģis netika paņemts, tas nav tankkuģis)
            if mmsi in static or km((lat, lon), buoy) > MOORED_KM:
                continue
            ships[mmsi] = {"mmsi": mmsi, "first_seen": iso(now),
                           "name": (meta.get("ShipName") or "").strip()}
        sh = ships[mmsi]
        sh.update({"lat": round(lat, 5), "lon": round(lon, 5),
                   "sog": p.get("Sog"), "cog": p.get("Cog"),
                   "nav_status": p.get("NavigationalStatus"),
                   "pos_time": meta.get("time_utc", iso(now))[:19].replace(" ", "T") + "Z",
                   "last_seen": iso(now)})

    events, out = [], []
    cutoff = now - timedelta(days=FORGET_DAYS)
    for mmsi, sh in ships.items():
        prev = old.get(mmsi, {}).get("status")
        st = status_of(sh, buoy)
        sh["status"] = st
        seen = datetime.strptime(sh.get("last_seen") or sh["first_seen"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        t = sh.get("ais_type")
        # velkoņi un apkalpes laivas pie bojas nav interesanti: tikai tankkuģi vai galamērķis Būtiņģe
        # kuģis bez tipa paliek sarakstā tikai, kamēr to dzird (6 h)
        relevant = sh.get("dest_match") or (80 <= t <= 89 if t is not None
                                            else seen >= now - timedelta(hours=6))
        keep = relevant and (st != "ceļā" or sh.get("dest_match")) and seen >= cutoff
        if not relevant:
            continue
        if st == "pie_bojas" and prev != "pie_bojas":
            sh["arrived"] = iso(now)
            sh["arrival_draught"] = sh.get("draught")
            events.append({"time": iso(now), "event": "pietauvojās", "mmsi": mmsi,
                           "name": sh.get("name"), "imo": sh.get("imo"), "draught": sh.get("draught")})
        if prev == "pie_bojas" and st != "pie_bojas":
            events.append({"time": iso(now), "event": "atstāja", "mmsi": mmsi,
                           "name": sh.get("name"), "imo": sh.get("imo"), "draught": sh.get("draught"),
                           "arrived": sh.get("arrived"), "arrival_draught": sh.get("arrival_draught")})
            sh.pop("arrived", None)
            sh.pop("arrival_draught", None)
        if keep:
            out.append(cargo_guess(load_estimate(sh, vessels), "butinge"))

    moored = [s for s in out if s["status"] == "pie_bojas" and s.get("lat")]
    learned = state.get("learned_buoy")
    if moored:
        # tankkuģis pie SPM bojas stāv ~100 m no tās, tāpēc vidējā vieta ir labs tuvinājums
        la = sum(s["lat"] for s in moored) / len(moored)
        lo = sum(s["lon"] for s in moored) / len(moored)
        learned = [round(la, 5), round(lo, 5)] if not learned else \
            [round(0.8 * learned[0] + 0.2 * la, 5), round(0.8 * learned[1] + 0.2 * lo, 5)]

    # diagnostika: vai aisstream vispār dzird kuģus pie Būtiņģes?
    near = []
    for mmsi, (p, meta) in pos.items():
        if p.get("Latitude") is None or abs(p["Latitude"]) > 90:
            continue
        d = km((p["Latitude"], p["Longitude"]), buoy)
        if d <= 60:
            name = (static.get(mmsi, ({}, {}))[0].get("Name") or meta.get("ShipName") or "").strip()
            near.append({"mmsi": mmsi, "name": name, "km": round(d, 1), "sog": p.get("Sog")})
    near.sort(key=lambda x: x["km"])
    dests = sorted({(s.get("Destination") or "").strip() for s, _ in static.values()
                    if re.search(r"BUT|LTBOT|PALANG|SVENT", (s.get("Destination") or "").upper())})
    diag = {
        "static_msgs": len(static),
        "ships_heard": len(pos),
        "within_60km": len(near),
        "nearest": near[:8],
        "dest_like_butinge": dests[:20],
    }

    order = {"pie_bojas": 0, "gaida": 1, "ceļā": 2}
    out.sort(key=lambda s: (order[s["status"]], s.get("dist_buoy_km") or 1e9))
    new_state = {
        "updated": iso(now),
        "buoy": list(buoy),
        "learned_buoy": learned,
        "messages_heard": len(messages),
        "diag": diag,
        "ships": out,
    }
    return new_state, events


# ---------------------------------------------------------------------------
# Tankkuģi Baltijas valstu ostās
# Aplis ap ostu ietver arī tās enkurvietu (reidu).
PORTS_FILE = Path(__file__).parent / "data" / "ports" / "latest.json"
TANKER_CACHE = Path(__file__).parent / "data" / "ports" / "tankers_cache.json"
PORTS = [
    # id, nosaukums, valsts, lat, lon, rādiuss km
    # Lietuva, Latvija, Igaunija
    ("klaipeda", "Klaipēda", "LT", 55.705, 21.090, 14),
    ("butinge", "Būtiņģe", "LT", 56.062, 20.958, 6),
    ("liepaja", "Liepāja", "LV", 56.525, 20.990, 10),
    ("ventspils", "Ventspils", "LV", 57.405, 21.520, 14),
    ("riga", "Rīga", "LV", 57.050, 24.030, 16),
    ("skulte", "Skulte", "LV", 57.315, 24.390, 6),
    ("parnu", "Pērnava", "EE", 58.370, 24.450, 10),
    ("paldiski", "Paldiski", "EE", 59.345, 24.060, 9),
    ("tallinn", "Tallina / Muuga", "EE", 59.480, 24.880, 16),
    ("sillamae", "Sillamē", "EE", 59.415, 27.740, 8),
    # Somija
    ("helsinki", "Helsinki / Vuosāri", "FI", 60.170, 25.050, 14),
    ("porvoo", "Porvo / Šēldvika", "FI", 60.300, 25.550, 8),
    ("hamina_kotka", "Hamina-Kotka", "FI", 60.480, 26.980, 14),
    ("hanko", "Hanko", "FI", 59.820, 22.970, 6),
    ("turku_naantali", "Turku / Nāntali", "FI", 60.450, 22.120, 10),
    ("rauma", "Rauma", "FI", 61.130, 21.460, 6),
    ("pori", "Pori", "FI", 61.600, 21.450, 8),
    ("kokkola", "Kokola", "FI", 63.860, 23.030, 7),
    ("oulu", "Oulu", "FI", 65.000, 25.400, 10),
    # Krievija
    ("st_petersburg", "Sanktpēterburga", "RU", 59.880, 30.150, 14),
    ("ust_luga", "Ustjluga", "RU", 59.680, 28.400, 12),
    ("primorsk", "Primorska", "RU", 60.350, 28.620, 10),
    ("vysotsk", "Visocka", "RU", 60.620, 28.570, 7),
    ("kaliningrad", "Kaļiņingrada / Baltijska", "RU", 54.660, 20.000, 18),
    # Polija
    ("gdansk", "Gdaņska", "PL", 54.400, 18.680, 12),
    ("gdynia", "Gdiņa", "PL", 54.540, 18.570, 7),
    ("swinoujscie", "Svinoujsce / Ščecina", "PL", 53.920, 14.270, 12),
    # Vācija
    ("rostock", "Rostoka", "DE", 54.170, 12.100, 10),
    ("kiel", "Kīle", "DE", 54.380, 10.180, 10),
    ("travemunde", "Lībeka / Travemünde", "DE", 53.960, 10.870, 8),
    ("wismar", "Vismāra", "DE", 53.910, 11.460, 6),
    ("sassnitz", "Zasnica / Mukrāna", "DE", 54.500, 13.640, 7),
    # Dānija
    ("copenhagen", "Kopenhāgena", "DK", 55.700, 12.610, 7),
    ("ronne", "Rēne (Bornholma)", "DK", 55.100, 14.690, 6),
    # Zviedrija
    ("stockholm", "Stokholma", "SE", 59.330, 18.110, 10),
    ("nynashamn", "Nīneshamna", "SE", 58.900, 17.950, 7),
    ("oxelosund", "Ūkselēsunda", "SE", 58.670, 17.120, 7),
    ("norrkoping", "Norčēpinga", "SE", 58.600, 16.230, 8),
    ("visby", "Visbija", "SE", 57.640, 18.280, 5),
    ("karlshamn", "Karlshamna", "SE", 56.170, 14.860, 7),
    ("malmo", "Malme", "SE", 55.620, 12.980, 7),
    ("trelleborg", "Trelleborga", "SE", 55.370, 13.150, 6),
    ("gavle", "Jēvle", "SE", 60.680, 17.220, 8),
    ("sundsvall", "Sundsvalla", "SE", 62.390, 17.330, 8),
    ("lulea", "Luleo", "SE", 65.580, 22.150, 9),
    ("gothenburg", "Gēteborga", "SE", 57.690, 11.850, 12),
]
# LNG termināļi Baltijas jūrā (aptuvenas koordinātas; peldošās krātuves var pārvietoties)
LNG_TERMINALS = [
    {"name": "Klaipēdas LNG (peldošā krātuve Independence)", "country": "LT", "lat": 55.64, "lon": 21.13, "kind": "FSRU"},
    {"name": "Inkoo LNG (peldošā krātuve)", "country": "FI", "lat": 60.03, "lon": 24.00, "kind": "FSRU"},
    {"name": "Svinoujsces LNG terminālis", "country": "PL", "lat": 53.93, "lon": 14.27, "kind": "krasta"},
    {"name": "Mukrānas LNG (Deutsche Ostsee)", "country": "DE", "lat": 54.50, "lon": 13.62, "kind": "FSRU"},
    {"name": "Haminas LNG terminālis", "country": "FI", "lat": 60.55, "lon": 27.17, "kind": "krasta"},
    {"name": "Pori LNG terminālis", "country": "FI", "lat": 61.60, "lon": 21.45, "kind": "krasta"},
    {"name": "Tornio Manga LNG", "country": "FI", "lat": 65.80, "lon": 24.15, "kind": "krasta"},
    {"name": "Nīneshamnas LNG", "country": "SE", "lat": 58.90, "lon": 17.95, "kind": "krasta"},
    {"name": "Visockas LNG", "country": "RU", "lat": 60.62, "lon": 28.57, "kind": "krasta"},
    {"name": "Portovaja LNG", "country": "RU", "lat": 60.43, "lon": 28.07, "kind": "krasta"},
    {"name": "Kaļiņingradas FSRU (Marshal Vasilevskiy)", "country": "RU", "lat": 54.70, "lon": 19.95, "kind": "FSRU"},
]
# Gāzes kuģi AIS nav atsevišķs tips; tos atpazīst pēc nosaukuma
GAS_RE = re.compile(r"LNG|LPG|(^|[^A-Z])GAS|GAS($|[^A-Z])|HOEGH|EXEMPLAR|ENERGOS|TRANSGAS|VASILEVSK|GASLOG|ECOGAS")
GAS_FSRU_NAMES = re.compile(r"^(INDEPENDENCE|EXEMPLAR|HOEGH .*|NEPTUNE|ENERGOS .*|TRANSGAS .*|MARSHAL VASILEVSKIY)$")


def is_gas_ship(name, t):
    n = (name or "").upper().strip()
    if t is not None and (60 <= t <= 69 or t in (31, 32, 52)):
        return False   # pasažieru kuģi/prāmji (piem. MEGASTAR) un velkoņi nav gāzes kuģi
    if GAS_RE.search(n):
        return True
    return bool(GAS_FSRU_NAMES.match(n)) and (t is None or 80 <= t <= 89 or t == 90)


COUNTRY_LV = {"LT": "Lietuva", "LV": "Latvija", "EE": "Igaunija", "FI": "Somija", "RU": "Krievija",
              "PL": "Polija", "DE": "Vācija", "DK": "Dānija", "SE": "Zviedrija"}
CACHE_DAYS = 14


def is_tanker(t):
    return t is not None and 80 <= t <= 89


LNG_DEST = [
    (r"KLAIP|LT\s*KLJ", "Klaipēdas LNG (peldošā krātuve Independence)"),
    (r"INKOO|FI\s*INK", "Inkoo LNG (peldošā krātuve)"),
    (r"SWINO|[SŚ]WINOUJ|PL\s*SWI", "Svinoujsces LNG terminālis"),
    (r"MUKRAN|DE\s*MUK|SASSNITZ", "Mukrānas LNG (Deutsche Ostsee)"),
    (r"HAMINA|FI\s*HMN", "Haminas LNG terminālis"),
    (r"(^|[^A-Z])PORI|FI\s*POR", "Pori LNG terminālis"),
    (r"TORNIO|FI\s*TOR", "Tornio Manga LNG"),
    (r"NYNAS|SE\s*NYN", "Nīneshamnas LNG"),
    (r"VYSOTSK|RU\s*VYS", "Visockas LNG"),
    (r"PORTOVA", "Portovaja LNG"),
    (r"KALININGRAD|RU\s*KGD", "Kaļiņingradas FSRU (Marshal Vasilevskiy)"),
]


def lng_dest(dest):
    d = final_dest(dest)
    for rx, name in LNG_DEST:
        if re.search(rx, d):
            return name
    return None


def gas_ships(pos, cache):
    """Visi dzirdamie gāzes kuģi, ar tuvāko LNG termināli."""
    out = []
    for mmsi, (p, meta) in pos.items():
        c = cache.get(str(mmsi))
        if not c or not is_gas_ship(c.get("name"), c.get("type")):
            continue
        la, lo = p.get("Latitude"), p.get("Longitude")
        if la is None or abs(la) > 90:
            continue
        term = min(LNG_TERMINALS, key=lambda t: km((la, lo), (t["lat"], t["lon"])))
        dt = km((la, lo), (term["lat"], term["lon"]))
        sog = p.get("Sog") or 0
        name = (c.get("name") or "").upper()
        kind = "LPG" if "LPG" in name else ("LNG" if re.search(r"LNG|HOEGH|EXEMPLAR|ENERGOS|TRANSGAS|VASILEVSK|INDEPENDENCE", name) else "gāze")
        out.append({
            "mmsi": mmsi, "name": c.get("name"), "imo": c.get("imo"), "length": c.get("length"),
            "draught": c.get("draught") or None, "destination": c.get("destination"), "eta": c.get("eta"),
            "lat": round(la, 5), "lon": round(lo, 5), "sog": p.get("Sog"), "cog": p.get("Cog"),
            "gas_kind": kind,
            "to_terminal": lng_dest(c.get("destination")),
            "status": "kustībā" if sog >= 1 else ("pie LNG termināļa" if dt <= 3 else "stāv"),
            "near_terminal": term["name"] if dt <= 15 else None,
            "terminal_km": round(dt, 1),
        })
    for x in out:
        if x["to_terminal"]:
            t = next(t for t in LNG_TERMINALS if t["name"] == x["to_terminal"])
            x["to_terminal_km"] = round(km((x["lat"], x["lon"]), (t["lat"], t["lon"])))
            if x["status"] == "kustībā":
                x["status"] = "ceļā uz LNG termināli"
        # pilns vai tukšs pēc iegrimes (LNG kuģim iegrime pilnam ~11–12 m, tukšam ~9 m)
        L = x.get("length") or 0
        t = x.get("draught")
        if t and L >= 200:
            x["load"] = "pilns (ved gāzi)" if t >= 10.8 else ("tukšs / balastā" if t <= 9.6 else "daļēji")
        elif t and L:
            tmax = 0.06 * L          # mazs gāzes kuģis: aptuvenā pilna iegrime
            x["load"] = "pilns (ved gāzi)" if t >= 0.85 * tmax else ("tukšs / balastā" if t <= 0.65 * tmax else "daļēji")
        else:
            x["load"] = None
    order = {"ceļā uz LNG termināli": 0, "pie LNG termināļa": 1, "stāv": 2, "kustībā": 3}
    out.sort(key=lambda x: (order[x["status"]], x["terminal_km"]))
    return out


# ---------------------------------------------------------------------------
# Krievijai piesaistītie tankkuģi
SANCTIONS_FILE = Path(__file__).parent / "data" / "ports" / "sanctioned_vessels.json"
SANCTIONS_INDEX = "https://data.opensanctions.org/datasets/latest/maritime/index.json"
RU_PORTS_RE = [
    (r"PRIMORSK|RU\s*PRI", "Primorska"), (r"UST.?LUGA|RU\s*ULU", "Ustjluga"),
    (r"PETERSB|S\.?\s*PETERS|RU\s*LED|SPB", "Sanktpēterburga"), (r"VYSOTSK|RU\s*VYS", "Visocka"),
    (r"KALININGR|RU\s*KGD", "Kaļiņingrada"), (r"BALTIYSK|RU\s*BLT", "Baltijska"),
    (r"(^|[^A-Z])RU\s*[A-Z]{3}($|[^A-Z])", "Krievijas osta"),
]
RU_PORT_IDS = {"st_petersburg", "ust_luga", "primorsk", "vysotsk", "kaliningrad"}
FLAG_MID = {
    "273": "Krievija", "626": "Gabona", "613": "Kamerūna", "616": "Komoras", "620": "Komoras",
    "667": "Sjerraleone", "511": "Palau", "518": "Kuka salas", "341": "Sentkitsa un Nevisa",
    "312": "Beliza", "577": "Vanuatu", "457": "Mongolija", "671": "Togo", "450": "Irāna",
    "636": "Libērija", "538": "Māršala salas", "351": "Panama", "352": "Panama", "353": "Panama",
    "354": "Panama", "355": "Panama", "356": "Panama", "357": "Panama", "370": "Panama",
    "371": "Panama", "372": "Panama", "373": "Panama", "248": "Malta", "249": "Malta",
    "256": "Malta", "209": "Kipra", "210": "Kipra", "212": "Kipra", "240": "Grieķija",
    "241": "Grieķija", "477": "Honkonga", "563": "Singapūra", "564": "Singapūra", "565": "Singapūra",
    "566": "Singapūra", "311": "Bahamas", "308": "Bahamas", "309": "Bahamas", "229": "Malta",
    "215": "Malta", "472": "Tadžikistāna", "422": "Irāna", "403": "Saūda Arābija", "470": "AAE",
    "419": "Indija", "412": "Ķīna", "413": "Ķīna", "414": "Ķīna", "219": "Dānija", "220": "Dānija",
    "230": "Somija", "265": "Zviedrija", "266": "Zviedrija", "257": "Norvēģija", "258": "Norvēģija",
    "259": "Norvēģija", "211": "Vācija", "218": "Vācija", "261": "Polija", "275": "Latvija",
    "276": "Igaunija", "277": "Lietuva", "244": "Nīderlande", "245": "Nīderlande", "246": "Nīderlande",
    "232": "Lielbritānija", "233": "Lielbritānija", "234": "Lielbritānija", "235": "Lielbritānija",
}
# karogi, kas bieži izmantoti "ēnu flotē" (pazīme, ne pierādījums)
SHADOW_FLAGS = {"626", "613", "616", "620", "667", "511", "518", "341", "312", "577", "457", "671", "450", "472"}


def flag_of(mmsi):
    m = str(mmsi)
    return FLAG_MID.get(m[:3]) if len(m) == 9 else None


def ru_port_of(dest):
    d = final_dest(dest)
    for rx, name in RU_PORTS_RE:
        if re.search(rx, d):
            return name
    return None


def load_sanctions():
    try:
        return json.loads(SANCTIONS_FILE.read_text())
    except Exception:
        return {}


def update_sanctions(max_age_h=20):
    """Lejupielādē OpenSanctions jūrniecības sarakstu (kuģi ar IMO), ne biežāk kā reizi ~dienā."""
    import csv
    import io
    import urllib.request
    old = load_sanctions()
    upd = old.get("_updated")
    if upd and datetime.strptime(upd, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) > now_utc() - timedelta(hours=max_age_h):
        return old
    try:
        req = lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "robezas-sargs"}), timeout=60)
        idx = json.load(req(SANCTIONS_INDEX))
        url = next(r["url"] for r in idx.get("resources", []) if r.get("name") == "maritime.csv")
        text = req(url).read().decode("utf-8")
        out = {"_updated": iso(now_utc()), "_source": "OpenSanctions maritime (CC BY-NC 4.0)"}
        for row in csv.DictReader(io.StringIO(text)):
            if row.get("type") != "VESSEL":
                continue
            imo = re.sub(r"\D", "", row.get("imo") or "")
            if not imo:
                continue
            out[imo] = {"n": row.get("caption"), "r": row.get("risk"), "u": row.get("url")}
        if len(out) > 100:
            SANCTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SANCTIONS_FILE.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
            print(f"Sankciju saraksts: {len(out) - 2} kuģi")
            return out
    except Exception as e:
        print(f"Sankciju sarakstu neizdevās atjaunot: {e}")
    return old


def ru_tankers(pos, cache, ports, sanctions):
    in_ru_port = {}
    for p in ports:
        if p["id"] in RU_PORT_IDS:
            for t in p["tankers"]:
                in_ru_port[t["mmsi"]] = p["name"]
    out = []
    for mmsi, (p, meta) in pos.items():
        c = cache.get(str(mmsi))
        if not c or not (is_tanker(c.get("type")) or is_gas_ship(c.get("name"), c.get("type"))):
            continue
        la, lo = p.get("Latitude"), p.get("Longitude")
        if la is None or abs(la) > 90:
            continue
        why, risk = [], 0
        mid = str(mmsi)[:3]
        flag = flag_of(mmsi)
        if mid == "273":
            why.append("Krievijas karogs")
            risk += 2
        rp = ru_port_of(c.get("destination"))
        if rp:
            why.append(f"galamērķis: {rp}")
            risk += 2
        if mmsi in in_ru_port:
            why.append(f"stāv ostā: {in_ru_port[mmsi]}")
            risk += 2
        sanc = sanctions.get(str(c.get("imo") or "")) if c.get("imo") else None
        tags = set((sanc or {}).get("r", "").split(";")) - {""}
        sanctioned = "sanction" in tags
        shadow = "mare.shadow" in tags
        if sanctioned:
            why.append("sankcijās (ES/ASV/LK u.c.)")
            risk += 5
        if shadow:
            why.append("ēnu flotes sarakstā (OpenSanctions)")
            risk += 4
        if not why:
            continue
        if "mare.detained" in tags:
            why.append("bijis aizturēts ostas valsts kontrolē")
        if mid in SHADOW_FLAGS:
            why.append(f"karogs bieži lietots ēnu flotē ({flag})")
            risk += 1
        dest = (c.get("destination") or "").upper()
        if re.search(r"FOR ORDER|ORDERS", dest):
            why.append("galamērķis “for orders”")
        out.append({
            "mmsi": mmsi, "name": c.get("name"), "imo": c.get("imo"), "flag": flag,
            "length": c.get("length"), "draught": c.get("draught") or None,
            "destination": c.get("destination"), "eta": c.get("eta"),
            "lat": round(la, 5), "lon": round(lo, 5), "sog": p.get("Sog"), "cog": p.get("Cog"),
            "status": "kustībā" if (p.get("Sog") or 0) >= 1 else "stāv",
            "reasons": why, "risk": risk, "sanctioned": sanctioned, "shadow_listed": shadow,
            "sanction_url": sanc.get("u") if sanc else None,
            "area": area_name((la, lo)),
        })
    out.sort(key=lambda x: (-x["risk"], x.get("name") or ""))
    return out


# ---------------------------------------------------------------------------
# Militārie un dienesta kuģi (tikai tie, kas paši raida AIS; daudzi to nedara)
MIL_NAME_RE = re.compile(
    r"WARSHIP|NAVY|NAVAL|MILITARY|^(HMS|USS|USNS|HNLMS|HDMS|FGS|HMCS|ESPS|ITS|FS|ORP|KNM|HSWMS|HMSWS|"
    r"LVNS|LNS|EML|BNS|FNS|RFS|TCG|NRP|HS|SPS|HNOMS|FNFL)\s")
GOV_NAME_RE = re.compile(r"COAST ?GUARD|KYSTVAKT|KUSTBEVAKNING|VARTIOSTO|BORDER|BUNDESPOLIZEI|POLIZEI|"
                         r"STRAZ GRANICZNA|POGRANICHN|RESCUE|SAR |POLICE|ROBEZSARDZE|PIIRIVALVE|PASIENIO")


def service_kind(name, t):
    n = (name or "").upper().strip()
    if t == 35 or MIL_NAME_RE.search(n):
        return "militārais"
    if t == 55 or GOV_NAME_RE.search(n):
        return "robežsardze / krasta apsardze"
    return None


def service_ships(pos, cache):
    out = []
    for mmsi, (p, meta) in pos.items():
        c = cache.get(str(mmsi))
        if not c:
            continue
        kind = service_kind(c.get("name"), c.get("type"))
        if not kind:
            continue
        la, lo = p.get("Latitude"), p.get("Longitude")
        if la is None or abs(la) > 90:
            continue
        out.append({
            "mmsi": mmsi, "name": c.get("name") or (meta.get("ShipName") or "").strip(), "kind": kind,
            "flag": flag_of(mmsi), "length": c.get("length"), "destination": c.get("destination"),
            "lat": round(la, 5), "lon": round(lo, 5), "sog": p.get("Sog"), "cog": p.get("Cog"),
            "status": "kustībā" if (p.get("Sog") or 0) >= 1 else "stāv", "area": area_name((la, lo)),
        })
    out.sort(key=lambda x: (x["kind"] != "militārais", x.get("flag") or "", x.get("name") or ""))
    return out


_SANCTIONS = {}


def process_ports(messages, cache, vessels, now):
    """Atgriež (ostu pārskats, atjaunots tankkuģu kešs).

    Kešs glabā tankkuģu statiskos datus (tips, izmēri, iegrime, galamērķis),
    jo vienā palaišanā statisko ziņu dzird tikai daļai kuģu."""
    static, pos = {}, {}
    for m in messages:
        meta = m.get("MetaData", {})
        mmsi = meta.get("MMSI")
        body = m.get("Message", {})
        if not mmsi:
            continue
        if "ShipStaticData" in body:
            static[mmsi] = body["ShipStaticData"]
        for k in ("PositionReport", "StandardClassBPositionReport"):
            if k in body:
                pos[mmsi] = (body[k], meta)

    cache = dict(cache)
    for mmsi, s in static.items():
        key = str(mmsi)
        if 70 <= (s.get("Type") or 0) <= 89 or is_gas_ship(s.get("Name"), s.get("Type")) \
                or service_kind(s.get("Name"), s.get("Type")):
            dim = s.get("Dimension") or {}
            cache[key] = {
                "name": (s.get("Name") or "").strip(),
                "imo": s.get("ImoNumber"),
                "type": s.get("Type"),
                "length": (dim.get("A") or 0) + (dim.get("B") or 0) or None,
                "draught": s.get("MaximumStaticDraught"),
                "destination": (s.get("Destination") or "").strip(),
                "eta": eta_str(s.get("Eta")),
                "seen": iso(now),
            }
        elif key in cache:
            cache.pop(key)  # tips mainījies, vairs nav kravas/tankkuģis
    for mmsi in pos:
        if str(mmsi) in cache:
            cache[str(mmsi)]["seen"] = iso(now)
    cutoff = iso(now - timedelta(days=CACHE_DAYS))
    cache = {k: v for k, v in cache.items() if v["seen"] >= cutoff}

    ports = []
    for pid, name, cc, lat, lon, r in PORTS:
        ports.append({"id": pid, "name": name, "country": cc, "lat": lat, "lon": lon,
                      "radius_km": r, "ships_heard": 0, "tankers": [], "cargo": []})
    for mmsi, (p, meta) in pos.items():
        la, lo = p.get("Latitude"), p.get("Longitude")
        if la is None or abs(la) > 90:
            continue
        for port in ports:
            if km((la, lo), (port["lat"], port["lon"])) <= port["radius_km"]:
                port["ships_heard"] += 1
                break
    # kur atrodas zināmie tankkuģi (diagnostika)
    where = {}
    for mmsi, (p, meta) in pos.items():
        if str(mmsi) in cache and is_tanker(cache[str(mmsi)].get("type")) and p.get("Latitude") is not None and abs(p["Latitude"]) <= 90:
            k = f"{round(p['Latitude'])},{round(p['Longitude'])}"
            where[k] = where.get(k, 0) + 1
    for mmsi, (p, meta) in pos.items():
        c = cache.get(str(mmsi))
        if not c:
            continue
        la, lo = p.get("Latitude"), p.get("Longitude")
        if la is None or abs(la) > 90:
            continue
        for port in ports:
            d = km((la, lo), (port["lat"], port["lon"]))
            if d > port["radius_km"]:
                continue
            sog = p.get("Sog") or 0
            ns = p.get("NavigationalStatus")
            if sog >= 1:
                st = "kustībā"
            elif ns in ANCHOR_STATUS:
                st = "enkurvietā"
            else:
                st = "stāv ostā"
            sh = {"mmsi": mmsi, "name": c["name"] or (meta.get("ShipName") or "").strip(),
                  "imo": c["imo"], "length": c["length"], "draught": c["draught"],
                  "destination": c["destination"], "eta": c["eta"],
                  "lat": round(la, 5), "lon": round(lo, 5), "sog": p.get("Sog"),
                  "cog": p.get("Cog"), "status": st, "dist_km": round(d, 1)}
            if service_kind(c.get("name"), c.get("type")) or not (70 <= (c.get("type") or 0) <= 89):
                break
            if is_tanker(c.get("type")):
                port["tankers"].append(cargo_guess(load_estimate(sh, vessels), port["id"]))
            else:
                sh["ais_type"] = c.get("type")
                port["cargo"].append(sh)
            break
    for port in ports:
        port["tankers"].sort(key=lambda s: (s["status"] == "kustībā", s.get("name") or ""))
        port["cargo"].sort(key=lambda s: (s["status"] == "kustībā", s.get("name") or ""))
        port["country_name"] = COUNTRY_LV.get(port["country"], port["country"])
    summary = {
        "updated": iso(now),
        "tankers_known": sum(1 for v in cache.values() if is_tanker(v.get("type"))),
        "ships_known": len(cache),
        "total_in_ports": sum(len(p["tankers"]) for p in ports),
        "cargo_in_ports": sum(len(p["cargo"]) for p in ports),
        "tankers_heard_now": sum(1 for m in pos if str(m) in cache and is_tanker(cache[str(m)].get("type"))),
        "tanker_cells": dict(sorted(where.items(), key=lambda x: -x[1])[:25]),
        "ports": ports,
        "gas_ships": gas_ships(pos, cache),
        "ru_tankers": ru_tankers(pos, cache, ports, _SANCTIONS),
        "service_ships": service_ships(pos, cache),
        "lng_terminals": LNG_TERMINALS,
    }
    return summary, cache


# ---------------------------------------------------------------------------
# Kuģi ceļā uz Baltijas valstu ostām (pēc AIS galamērķa)
INBOUND_FILE = Path(__file__).parent / "data" / "ports" / "inbound_baltic.json"
DEST_PORTS = [
    # id, nosaukums, valsts, galamērķa paraugs (AIS teksts lielajiem burtiem), ostas centrs, pieejas mezgls
    ("riga", "Rīga", "LV", r"(^|[^A-Z])RIGA|LV\s*RIX", (57.05, 24.03), "rigaApp"),
    ("ventspils", "Ventspils", "LV", r"VENTSP|LV\s*VNT", (57.40, 21.55), "ventspilsW"),
    ("liepaja", "Liepāja", "LV", r"LIEPA|LV\s*LPX", (56.52, 21.00), "liepajaW"),
    ("skulte", "Skulte", "LV", r"SKULTE|LV\s*SKU", (57.31, 24.40), "rigaApp"),
    ("salacgriva", "Salacgrīva", "LV", r"SALACG|LV\s*SAL", (57.75, 24.35), "gorNorth"),
    ("mersrags", "Mērsrags", "LV", r"MERSRAG|LV\s*MRS", (57.34, 23.13), "gorMid"),
    ("roja", "Roja", "LV", r"(^|[^A-Z])ROJA($|[^A-Z])|LV\s*ROJ", (57.51, 22.80), "gorMid"),
    ("pavilosta", "Pāvilosta", "LV", r"PAVILOST|LV\s*PAV", (56.89, 21.18), "liepajaW"),
    ("klaipeda", "Klaipēda", "LT", r"KLAIP|LT\s*KLJ", (55.70, 21.12), "klaipedaW"),
    ("butinge", "Būtiņģe", "LT", r"BUT[I1]NG|LT\s*BOT", (56.06, 20.96), "klaipedaW"),
    ("tallinn", "Tallina", "EE", r"TALLIN|EE\s*TLL", (59.45, 24.77), "tallinnApp"),
    ("muuga", "Muuga", "EE", r"MUUGA|EE\s*MUG", (59.50, 24.95), "tallinnApp"),
    ("paldiski", "Paldiski", "EE", r"PALDISK|EE\s*PLA", (59.35, 24.05), "paldiskiApp"),
    ("sillamae", "Sillamē", "EE", r"SILLAM|EE\s*SLM", (59.41, 27.74), "gofEast"),
    ("kunda", "Kunda", "EE", r"KUNDA|EE\s*KUN", (59.52, 26.53), "gofEast"),
    ("parnu", "Pērnava", "EE", r"P[AÄ]RNU|EE\s*PRN", (58.37, 24.48), "parnuApp"),
]
LV_DEST = DEST_PORTS     # vecais nosaukums
INBOUND_DAYS = 21        # okeānā kuģi var nebūt dzirdami daudzas dienas
ARRIVED_KM = 12          # tuvāk ostai par šo = ieradies, izņem no saraksta

TYPE_LV = [(80, 89, "tankkuģis"), (70, 79, "kravas kuģis"), (60, 69, "pasažieru/prāmis"),
           (30, 30, "zvejas"), (31, 32, "velkonis"), (52, 52, "velkonis")]


def type_name(t):
    for a, b, n in TYPE_LV:
        if t is not None and a <= t <= b:
            return n
    return "cits"


def final_dest(dest):
    """AIS galamērķis bieži ir formā "NO>UZ" (piem. "LTBOT>USHOU"); mērķis ir pēdējā daļa."""
    d = (dest or "").upper().strip()
    if ">" in d:
        d = d.split(">")[-1].strip()
    return d


def dest_port_of(dest):
    d = final_dest(dest)
    for pid, name, cc, rx, center, _ in DEST_PORTS:
        if re.search(rx, d):
            return pid, name, center
    return None


lv_port_of = dest_port_of

# Kuģu ceļu tīkls Baltijas jūrā un tās pieejās (mezgli un jūras ceļi starp tiem).
# Ar to aprēķina ceļa garumu un simulē kustību, kad kuģis vairs nav dzirdams.
NODES = {
    "northScotland": (59.20, -3.00, "Ziemeļskotija"), "dover": (51.00, 1.50, "Lamanšs"),
    "channelW": (49.60, -5.20, "Lamanšs"), "finisterre": (43.40, -9.80, "Biskaja / Spānija"),
    "gibraltar": (36.00, -5.80, "Gibraltārs"), "sicily": (37.40, 11.50, "Vidusjūra"),
    "crete": (34.80, 24.00, "Vidusjūra"), "portSaid": (31.40, 32.40, "Suecas kanāls"),
    "bosporus": (40.90, 29.10, "Bosfors"), "aegean": (38.50, 25.50, "Egejas jūra"),
    "redSea": (20.00, 38.80, "Sarkanā jūra"), "bab": (12.50, 43.50, "Adenas līcis"),
    "capeTown": (-35.00, 19.00, "Labās Cerības rags"), "westAfrica": (5.00, -15.00, "Rietumāfrika"),
    "canaries": (28.00, -16.00, "Kanāriju salas"), "atlanticN": (45.00, -30.00, "Atlantijas okeāns"),
    "newYork": (40.30, -73.50, "ASV austrumkrasts"), "gulfMexico": (25.00, -88.00, "Meksikas līcis"),
    "germanBight": (54.20, 7.60, "Vācu līcis"), "jutlandW": (57.20, 7.60, "Jitlande"),
    "kielCanal": (54.30, 9.80, "Ķīles kanāls"),
    "norwayW": (60.30, 4.60, "Norvēģijas rietumi"), "lindesnes": (57.90, 7.00, "Norvēģijas dienvidi"), "skagen": (57.85, 10.70, "Skagena"),
    "oresundN": (55.95, 12.65, "Ēresunds"), "oresundS": (55.40, 12.85, "Ēresunds"),
    "fehmarn": (54.55, 11.30, "Fehmarna / Kīle"), "gedser": (54.35, 12.30, "Gēdsera"),
    "bornholm": (55.30, 14.40, "Bornholma"), "bornholmE": (55.50, 16.00, "Bornholma"),
    "hoburg": (56.80, 18.30, "Gotlande"), "gotlandE": (57.80, 19.60, "Gotlande"),
    "faro": (58.60, 19.80, "Gotlande"), "aland": (59.70, 19.50, "Ālandu jūra"),
    "bothnia": (61.00, 19.80, "Botnijas jūra"), "gofW": (59.40, 22.80, "Somu līcis"),
    "tallinnApp": (59.55, 24.70, "Somu līcis"), "gofEast": (59.90, 26.50, "Somu līcis"),
    "paldiskiApp": (59.45, 23.90, "Somu līcis"),
    "klaipedaW": (55.80, 20.70, "Lietuvas piekraste"), "liepajaW": (56.60, 20.40, "Kurzemes piekraste"),
    "ventspilsW": (57.20, 20.80, "Kurzemes piekraste"), "irbe": (57.78, 21.75, "Irbes šaurums"),
    "gorMid": (57.70, 22.80, "Rīgas līcis"), "rigaApp": (57.20, 23.90, "Rīgas līcis"),
    "gorNorth": (57.95, 23.80, "Rīgas līcis"), "parnuApp": (58.15, 23.95, "Rīgas līcis"),
    "gdanskBay": (54.70, 18.90, "Gdaņskas līcis"), "landsort": (58.70, 18.10, "Stokholmas pieeja"),
    "pomBay": (54.20, 14.20, "Pomožes līcis"), "bothnianBay": (64.30, 22.80, "Botnijas līcis"),
}
EDGES = [
    ("northScotland", "norwayW"), ("northScotland", "lindesnes"), ("dover", "germanBight"),
    ("channelW", "dover"), ("finisterre", "channelW"), ("gibraltar", "finisterre"), ("sicily", "gibraltar"),
    ("crete", "sicily"), ("portSaid", "crete"), ("aegean", "crete"), ("bosporus", "aegean"),
    ("redSea", "portSaid"), ("bab", "redSea"), ("capeTown", "westAfrica"), ("westAfrica", "canaries"),
    ("canaries", "finisterre"), ("atlanticN", "channelW"), ("atlanticN", "northScotland"),
    ("newYork", "atlanticN"), ("gulfMexico", "newYork"), ("germanBight", "jutlandW"),
    ("jutlandW", "skagen"), ("germanBight", "kielCanal"), ("kielCanal", "fehmarn"),
    ("norwayW", "lindesnes"), ("lindesnes", "skagen"), ("skagen", "oresundN"), ("oresundN", "oresundS"), ("oresundS", "bornholm"),
    ("fehmarn", "gedser"), ("gedser", "bornholm"), ("gedser", "oresundS"), ("bornholm", "bornholmE"),
    ("bornholmE", "hoburg"), ("bornholmE", "klaipedaW"), ("bornholmE", "gdanskBay"), ("gdanskBay", "klaipedaW"),
    ("klaipedaW", "liepajaW"), ("liepajaW", "ventspilsW"), ("hoburg", "liepajaW"), ("hoburg", "gotlandE"),
    ("gotlandE", "ventspilsW"), ("gotlandE", "faro"), ("faro", "gofW"), ("faro", "aland"), ("aland", "bothnia"),
    ("aland", "gofW"), ("gofW", "paldiskiApp"), ("paldiskiApp", "tallinnApp"), ("tallinnApp", "gofEast"),
    ("ventspilsW", "irbe"), ("irbe", "gorMid"), ("gorMid", "rigaApp"), ("gorMid", "gorNorth"),
    ("gorNorth", "parnuApp"), ("gorNorth", "rigaApp"),
    ("hoburg", "landsort"), ("landsort", "faro"), ("landsort", "aland"), ("bornholm", "pomBay"),
    ("gedser", "pomBay"), ("bothnia", "bothnianBay"),
]
KN_KMH = 1.852
_DIST_CACHE = {}


def _node_dist_to(port_id):
    """Dijkstra: īsākais ceļš no katra mezgla līdz ostai (km)."""
    if port_id in _DIST_CACHE:
        return _DIST_CACHE[port_id]
    port = next(p for p in DEST_PORTS if p[0] == port_id)
    adj = {n: [] for n in NODES}
    for u, v in EDGES:
        w = km(NODES[u][:2], NODES[v][:2])
        adj[u].append((v, w))
        adj[v].append((u, w))
    start = port[5]
    dist = {n: float("inf") for n in NODES}
    dist[start] = km(NODES[start][:2], port[4])
    todo = set(NODES)
    while todo:
        u = min(todo, key=lambda n: dist[n])
        todo.discard(u)
        for v, w in adj[u]:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
    _DIST_CACHE[port_id] = dist
    return dist


def route_remaining(pos, port_id):
    """Atlikušais ceļš km: tuvākais ceļu tīkla mezgls + īsākais ceļš no tā līdz ostai."""
    port = next(p for p in DEST_PORTS if p[0] == port_id)
    direct = km(pos, port[4])
    dist = _node_dist_to(port_id)
    # ieeja tīklā tikai caur 2 tuvākajiem mezgliem, lai ceļš neietu pāri sauszemei
    near = sorted(NODES, key=lambda n: km(pos, NODES[n][:2]))[:2]
    best = min(km(pos, NODES[n][:2]) + dist[n] for n in near)
    # pavisam tuvu ostai — taisni
    return min(best, direct) if direct < 60 else best


def area_name(pos):
    n = min(NODES, key=lambda k: km(pos, NODES[k][:2]))
    return NODES[n][2]


ROUTES = {p[0]: True for p in DEST_PORTS}


def simulate(sh, now):
    """Aprēķina prognozēto ierašanos un, ja kuģis nav dzirdams, tā aptuveno progresu."""
    if sh.get("lat") is None or sh.get("port_id") not in ROUTES:
        return
    rem = route_remaining((sh["lat"], sh["lon"]), sh["port_id"])
    sh["route_km"] = round(rem)
    sog = sh.get("sog") or 0
    if sog < 3:            # stāv vai velkas; prognozei vajag ātrumu
        sh.pop("pred_arrival", None)
        return
    seen = datetime.strptime(sh["last_seen"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    speed = sog * KN_KMH * 0.92          # nedaudz lēnāk par pēdējo ātrumu: līkumi, ostas pieeja
    arrive = seen + timedelta(hours=rem / speed)
    sh["pred_arrival"] = iso(arrive)
    hours_silent = (now - seen).total_seconds() / 3600
    if hours_silent > 0.5:
        sh["silent_h"] = round(hours_silent, 1)
        sh["pred_route_km"] = max(0, round(rem - speed * hours_silent))
    else:
        sh.pop("silent_h", None)
        sh.pop("pred_route_km", None)


def eta_is_stale(eta, now, days=4):
    """AIS ETA nav gada; ja tas ir vairāk nekā `days` dienas pagātnē, galamērķis ir novecojis."""
    if not eta or not eta.get("Month") or not eta.get("Day") or eta["Month"] > 12 or eta["Day"] > 31:
        return False
    for year in (now.year, now.year - 1, now.year + 1):
        try:
            d = datetime(year, eta["Month"], eta["Day"], tzinfo=timezone.utc)
        except ValueError:
            return False
        if abs((d - now).days) <= 183:
            return d < now - timedelta(days=days)
    return False


def process_inbound(messages, state, vessels, now):
    static, pos = {}, {}
    for m in messages:
        meta = m.get("MetaData", {})
        mmsi = meta.get("MMSI")
        body = m.get("Message", {})
        if not mmsi:
            continue
        if "ShipStaticData" in body:
            static[mmsi] = body["ShipStaticData"]
        for k in ("PositionReport", "StandardClassBPositionReport"):
            if k in body:
                pos[mmsi] = body[k]
    ships = {str(s["mmsi"]): dict(s) for s in state.get("ships", [])}
    arrived = list(state.get("arrived", []))

    for mmsi, s in static.items():
        key = str(mmsi)
        hit = lv_port_of(s.get("Destination"))
        t = s.get("Type")
        if not hit or not (70 <= (t or 0) <= 89):     # tikai kravas un tankkuģi
            ships.pop(key, None)                      # galamērķis mainījies
            continue
        pid, pname, _ = hit
        if eta_is_stale(s.get("Eta"), now):
            ships.pop(key, None)   # sens ETA = apkalpe nav atjaunojusi galamērķi
            continue
        dim = s.get("Dimension") or {}
        sh = ships.setdefault(key, {"mmsi": mmsi, "first_seen": iso(now)})
        sh.update({
            "name": (s.get("Name") or "").strip(), "imo": s.get("ImoNumber"),
            "type": type_name(t), "ais_type": t,
            "length": (dim.get("A") or 0) + (dim.get("B") or 0) or None,
            "draught": s.get("MaximumStaticDraught"),
            "destination": (s.get("Destination") or "").strip(),
            "port_id": pid, "port": pname, "eta": eta_str(s.get("Eta")),
            "country": next(x[2] for x in DEST_PORTS if x[0] == pid),
        })

    for key, sh in list(ships.items()):
        p = pos.get(sh["mmsi"])
        if p and p.get("Latitude") is not None and abs(p["Latitude"]) <= 90:
            la, lo = round(p["Latitude"], 4), round(p["Longitude"], 4)
            sh.setdefault("first_pos", [la, lo])
            sh.setdefault("from_area", area_name((la, lo)))
            sh.update({"lat": la, "lon": lo, "sog": p.get("Sog"), "cog": p.get("Cog"),
                       "last_seen": iso(now)})
        center = next(p[4] for p in DEST_PORTS if p[0] == sh["port_id"])
        sh["dest_pos"] = list(center)
        sh.setdefault("country", next(p[2] for p in DEST_PORTS if p[0] == sh["port_id"]))
        if sh.get("first_pos") and not sh.get("from_area"):
            sh["from_area"] = area_name(tuple(sh["first_pos"]))
        if sh.get("lat") is not None:
            sh["dist_km"] = round(km((sh["lat"], sh["lon"]), center))
            if sh["dist_km"] <= ARRIVED_KM:
                arrived.append({"time": iso(now), "name": sh.get("name"), "imo": sh.get("imo"),
                                "port": sh["port"], "type": sh.get("type"), "draught": sh.get("draught"),
                                "how": "AIS"})
                ships.pop(key)
                continue
            simulate(sh, now)
            pa = sh.get("pred_arrival")
            if pa and sh.get("silent_h") and pa <= iso(now):
                # nav dzirdams, bet pēc aprēķina jau ir ostā
                arrived.append({"time": pa, "name": sh.get("name"), "imo": sh.get("imo"),
                                "port": sh["port"], "type": sh.get("type"), "draught": sh.get("draught"),
                                "how": "prognoze", "last_seen": sh.get("last_seen")})
                ships.pop(key)
                continue
        seen = sh.get("last_seen") or sh["first_seen"]
        if seen < iso(now - timedelta(days=INBOUND_DAYS)):
            ships.pop(key)

    out = [cargo_guess(load_estimate(s, vessels), s.get("port_id")) if s.get("type") == "tankkuģis" else s
           for s in ships.values()]
    out.sort(key=lambda s: (s["port"], s.get("dist_km") or 1e9))
    counts = {}
    for s in out:
        counts[s["port"]] = counts.get(s["port"], 0) + 1
    return {"updated": iso(now), "total": len(out), "by_port": counts,
            "ships": out, "arrived": arrived[-60:]}


# ---------------------------------------------------------------------------
# Otrs avots: Somijas Digitraffic (Fintraffic) atvērtie AIS dati, CC BY 4.0, bez atslēgas.
DT_BASE = "https://meri.digitraffic.fi/api/ais/v1"
DT_HEADERS = {"Digitraffic-User": "robezas-sargs/1.0", "Accept-Encoding": "gzip",
              "User-Agent": "robezas-sargs (github.com/Toms0078/robezas-sargs-dati2)"}


def _dt_get(path):
    import gzip
    import urllib.request
    req = urllib.request.Request(DT_BASE + path, headers=DT_HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
    return json.loads(raw)


def dt_eta(v):
    """Digitraffic ETA bitu lauks -> aisstream formāts."""
    if not isinstance(v, int) or v <= 0:
        return None
    return {"Month": (v >> 16) & 0xF, "Day": (v >> 11) & 0x1F, "Hour": (v >> 6) & 0x1F, "Minute": v & 0x3F}


def digitraffic_to_messages(locations, vessels, max_age_min=30, now=None):
    """Pārvērš Digitraffic atbildes tādās pašās ziņās kā aisstream, lai pārējā apstrāde nemainās."""
    now = now or now_utc()
    cutoff_ms = (now - timedelta(minutes=max_age_min)).timestamp() * 1000
    msgs = []
    for v in vessels or []:
        mmsi = v.get("mmsi")
        if not mmsi:
            continue
        dr = v.get("draught")
        msgs.append({"MetaData": {"MMSI": mmsi, "ShipName": (v.get("name") or "").strip(), "source": "digitraffic"},
                     "Message": {"ShipStaticData": {
                         "Name": v.get("name") or "", "ImoNumber": v.get("imo") or 0, "Type": v.get("shipType"),
                         "Destination": v.get("destination") or "", "CallSign": v.get("callSign") or "",
                         "MaximumStaticDraught": (dr / 10.0) if isinstance(dr, (int, float)) and dr > 0 else None,
                         "Eta": dt_eta(v.get("eta")),
                         "Dimension": {"A": v.get("referencePointA") or 0, "B": v.get("referencePointB") or 0,
                                       "C": v.get("referencePointC") or 0, "D": v.get("referencePointD") or 0}}}})
    for f in (locations or {}).get("features", []):
        pr = f.get("properties") or {}
        mmsi = f.get("mmsi") or pr.get("mmsi")
        coords = (f.get("geometry") or {}).get("coordinates") or []
        ts = pr.get("timestampExternal") or 0
        if not mmsi or len(coords) < 2 or ts < cutoff_ms:
            continue
        t = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cog = pr.get("cog")
        msgs.append({"MetaData": {"MMSI": mmsi, "time_utc": t, "source": "digitraffic"},
                     "Message": {"PositionReport": {
                         "Latitude": coords[1], "Longitude": coords[0], "Sog": pr.get("sog"),
                         "Cog": cog if cog is not None and cog < 360 else None,
                         "NavigationalStatus": pr.get("navStat")}}})
    return msgs


def fetch_digitraffic():
    try:
        since = int((now_utc() - timedelta(minutes=30)).timestamp() * 1000)
        loc = _dt_get(f"/locations?from={since}")
        ves = _dt_get("/vessels")
        msgs = digitraffic_to_messages(loc, ves)
        print(f"Digitraffic: {len(loc.get('features', []))} pozīcijas, {len(ves)} kuģu dati")
        return msgs
    except Exception as e:
        print(f"Digitraffic neizdevās: {e}")
        return []


_DEST_RX = re.compile(r'"Destination"\s*:\s*"([^"]*)"')


# ---------------------------------------------------------------------------
# Enerģijas kravas uz Baltiju: gāzes kuģi uz LNG termināļiem un tankkuģi uz jebkuru Baltijas ostu
ENERGY_FILE = Path(__file__).parent / "data" / "ports" / "energy_inbound.json"
W = r"(^|[^A-Z])"
E = r"($|[^A-Z])"
BALTIC_DEST = [
    # ostas id (PORTS sarakstā), galamērķa paraugs
    ("riga", r"RIGA|LV\s*RIX"), ("ventspils", r"VENTSP|LV\s*VNT"), ("liepaja", r"LIEPA|LV\s*LPX"),
    ("skulte", r"SKULTE|LV\s*SKU"), ("klaipeda", r"KLAIP|LT\s*KLJ"), ("butinge", r"BUT[I1]NG|LT\s*BOT"),
    ("tallinn", r"TALLIN|MUUGA|EE\s*(TLL|MUG)"), ("paldiski", r"PALDISK|EE\s*PLA"),
    ("sillamae", r"SILLAM|EE\s*SLM"), ("parnu", r"P[AÄ]RNU|EE\s*PRN"),
    ("helsinki", r"HELSIN|VUOSAA|FI\s*(HEL|VUO)"), ("porvoo", r"PORVOO|SK[OÖ]LDVIK|KILPILAHT|FI\s*(PRV|SKV)"),
    ("hamina_kotka", r"HAMINA|KOTKA|MUSSALO|FI\s*(HMN|KTK)"), ("hanko", W + r"HANKO|FI\s*HKO"),
    ("turku_naantali", r"TURKU|NAANTAL|FI\s*(TKU|NLI)"), ("rauma", r"RAUMA|FI\s*RAU"),
    ("pori", W + r"PORI" + E + r"|MÄNTYLUOTO|MANTYLUOTO|TAHKOLUOTO|FI\s*POR"), ("kokkola", r"KOKKOLA|FI\s*KOK"),
    ("oulu", W + r"OULU|FI\s*OUL"), ("st_petersburg", r"PETERSB|RU\s*LED|SPB"),
    ("ust_luga", r"UST.?LUGA|RU\s*ULU"), ("primorsk", r"PRIMORSK|RU\s*PRI"), ("vysotsk", r"VYSOTSK|RU\s*VYS"),
    ("kaliningrad", r"KALININGR|BALTIYSK|RU\s*(KGD|BLT)"), ("gdansk", r"GDANSK|PL\s*GDN"),
    ("gdynia", r"GDYNIA|PL\s*GDY"), ("swinoujscie", r"SWINO|[SŚ]WINOUJ|SZCZECIN|PL\s*(SWI|SZZ)"),
    ("rostock", r"ROSTOCK|DE\s*RSK"), ("kiel", W + r"KIEL" + r"(?!\s*(CANAL|KANAL))|DE\s*KEL"),
    ("travemunde", r"L[UÜ]BECK|TRAVEM|DE\s*(LBC|TRV)"), ("wismar", r"WISMAR|DE\s*WIS"),
    ("sassnitz", r"SASSNITZ|MUKRAN|DE\s*(SAS|MUK)"), ("copenhagen", r"COPENH|K[OØ]BENH|DK\s*CPH"),
    ("ronne", r"R[OØ]NNE|DK\s*RNN"), ("stockholm", r"STOCKHOLM|SE\s*STO"), ("nynashamn", r"NYN[AÄ]S|SE\s*NYN"),
    ("oxelosund", r"OXEL[OÖ]|SE\s*OXE"), ("norrkoping", r"NORRK[OÖ]P|SE\s*NRK"), ("visby", r"VISBY|SE\s*VBY"),
    ("karlshamn", r"KARLSHAMN|SE\s*KAN"), ("malmo", r"MALM[OÖ]|SE\s*MMA"), ("trelleborg", r"TRELLEB|SE\s*TRG"),
    ("gavle", r"G[AÄ]VLE|SE\s*GVX"), ("sundsvall", r"SUNDSVALL|SE\s*SDL"), ("lulea", r"LULE[AÅ]|SE\s*LLA"),
    ("inkoo", r"INKOO|FI\s*INK"), ("tornio", r"TORNIO|R[OÖ]YT[TÄ]|FI\s*TOR"),
]
_EXTRA_PORTS = {"inkoo": ("Inkoo", "FI", 60.03, 24.00), "tornio": ("Tornio", "FI", 65.80, 24.15)}


def baltic_port_of(dest):
    d = final_dest(dest)
    if not d:
        return None
    for pid, rx in BALTIC_DEST:
        if re.search(rx, d):
            p = next((x for x in PORTS if x[0] == pid), None)
            if p:
                return {"id": pid, "name": p[1], "country": p[2], "pos": (p[3], p[4])}
            n, cc, la, lo = _EXTRA_PORTS[pid]
            return {"id": pid, "name": n, "country": cc, "pos": (la, lo)}
    return None


_BALTIC_NODES = None


def _approach_node(center):
    global _BALTIC_NODES
    if _BALTIC_NODES is None:
        _BALTIC_NODES = [n for n, v in NODES.items() if 53 <= v[0] <= 67 and 9 <= v[1] <= 31]
    return min(_BALTIC_NODES, key=lambda n: km(center, NODES[n][:2]))


def _dist_from_node(start, center):
    key = ("node", start, center)
    if key in _DIST_CACHE:
        return _DIST_CACHE[key]
    adj = {n: [] for n in NODES}
    for u, v in EDGES:
        w = km(NODES[u][:2], NODES[v][:2])
        adj[u].append((v, w))
        adj[v].append((u, w))
    dist = {n: float("inf") for n in NODES}
    dist[start] = km(NODES[start][:2], center)
    todo = set(NODES)
    while todo:
        u = min(todo, key=lambda n: dist[n])
        todo.discard(u)
        for v, w in adj[u]:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
    _DIST_CACHE[key] = dist
    return dist


def route_km_to(pos, center):
    direct = km(pos, center)
    if direct < 60:
        return direct
    dist = _dist_from_node(_approach_node(center), center)
    if pos[0] > 55.9 and pos[1] < 12.8 and pos[1] > 9.5:
        return km(pos, (55.95, 12.65)) + km((55.95, 12.65), (55.40, 12.85)) + route_km_to((55.40, 12.85), center)
    near = sorted(NODES, key=lambda n: km(pos, NODES[n][:2]))[:2]
    return min(km(pos, NODES[n][:2]) + dist[n] for n in near)


def is_energy_ship(name, t):
    return is_gas_ship(name, t) or (t is not None and 80 <= t <= 89)


def process_energy(messages, state, vessels, sanctions, now):
    static, pos = {}, {}
    for m in messages:
        meta = m.get("MetaData", {})
        mmsi = meta.get("MMSI")
        body = m.get("Message", {})
        if not mmsi:
            continue
        if "ShipStaticData" in body:
            static[mmsi] = body["ShipStaticData"]
        for k in ("PositionReport", "StandardClassBPositionReport"):
            if k in body:
                pos[mmsi] = body[k]
    ships = {str(s["mmsi"]): dict(s) for s in state.get("ships", [])}
    arrived = list(state.get("arrived", []))

    for mmsi, s in static.items():
        key = str(mmsi)
        name, t = (s.get("Name") or "").strip(), s.get("Type")
        if not is_energy_ship(name, t):
            continue
        port = baltic_port_of(s.get("Destination"))
        if not port or eta_is_stale(s.get("Eta"), now):
            ships.pop(key, None)
            continue
        gas = is_gas_ship(name, t)
        dim = s.get("Dimension") or {}
        sh = ships.setdefault(key, {"mmsi": mmsi, "first_seen": iso(now)})
        sh.update({
            "name": name, "imo": s.get("ImoNumber"), "ais_type": t, "flag": flag_of(mmsi),
            "length": (dim.get("A") or 0) + (dim.get("B") or 0) or None,
            "draught": s.get("MaximumStaticDraught") or None,
            "destination": (s.get("Destination") or "").strip(), "eta": eta_str(s.get("Eta")),
            "port_id": port["id"], "port": port["name"], "country": port["country"],
            "dest_pos": list(port["pos"]), "gas": gas,
            "terminal": lng_dest(s.get("Destination")) if gas else None,
        })

    for key, sh in list(ships.items()):
        p = pos.get(sh["mmsi"])
        if p and p.get("Latitude") is not None and abs(p["Latitude"]) <= 90:
            la, lo = round(p["Latitude"], 4), round(p["Longitude"], 4)
            sh.setdefault("from_area", area_name((la, lo)))
            sh.update({"lat": la, "lon": lo, "sog": p.get("Sog"), "cog": p.get("Cog"), "last_seen": iso(now)})
        if sh.get("lat") is None:
            continue
        center = tuple(sh["dest_pos"])
        d = km((sh["lat"], sh["lon"]), center)
        if d <= ARRIVED_KM:
            arrived.append({"time": iso(now), "name": sh.get("name"), "imo": sh.get("imo"), "port": sh["port"],
                            "gas": sh.get("gas"), "terminal": sh.get("terminal"), "draught": sh.get("draught"),
                            "how": "AIS"})
            ships.pop(key)
            continue
        rem = route_km_to((sh["lat"], sh["lon"]), center)
        sh["route_km"] = round(rem)
        seen = datetime.strptime(sh.get("last_seen") or sh["first_seen"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        sog = sh.get("sog") or 0
        if sog >= 3:
            speed = sog * KN_KMH * 0.92
            sh["pred_arrival"] = iso(seen + timedelta(hours=rem / speed))
            silent = (now - seen).total_seconds() / 3600
            if silent > 0.5:
                sh["silent_h"] = round(silent, 1)
                sh["pred_route_km"] = max(0, round(rem - speed * silent))
                if sh["pred_arrival"] <= iso(now):
                    arrived.append({"time": sh["pred_arrival"], "name": sh.get("name"), "imo": sh.get("imo"),
                                    "port": sh["port"], "gas": sh.get("gas"), "terminal": sh.get("terminal"),
                                    "draught": sh.get("draught"), "how": "prognoze"})
                    ships.pop(key)
                    continue
            else:
                sh.pop("silent_h", None)
                sh.pop("pred_route_km", None)
        if seen < now - timedelta(days=INBOUND_DAYS):
            ships.pop(key)

    out = []
    for sh in ships.values():
        if sh.get("lat") is None:
            continue
        sh = dict(sh)
        if sh.get("gas"):
            L, t = sh.get("length") or 0, sh.get("draught")
            name = (sh.get("name") or "").upper()
            sh["cargo_guess"] = "LPG" if "LPG" in name else ("LNG" if L >= 200 or "LNG" in name else "gāze (LPG/LNG)")
            if t and L >= 200:
                sh["laden"] = t >= 10.8
                sh["cargo_state"] = "pilns (ved gāzi)" if t >= 10.8 else ("tukšs / balastā" if t <= 9.6 else "daļēji")
            elif t and L:
                sh["laden"] = t >= 0.85 * 0.06 * L
                sh["cargo_state"] = "pilns (ved gāzi)" if sh["laden"] else ("tukšs / balastā" if t <= 0.65 * 0.06 * L else "daļēji")
            else:
                sh["laden"], sh["cargo_state"] = None, None
        else:
            cargo_guess(load_estimate(sh, vessels), sh["port_id"])
            lp = sh.get("load_pct")
            sh["laden"] = None if lp is None else lp >= 55
        sanc = sanctions.get(str(sh.get("imo") or "")) if sh.get("imo") else None
        tags = set((sanc or {}).get("r", "").split(";")) - {""}
        sh["sanctioned"], sh["shadow_listed"] = "sanction" in tags, "mare.shadow" in tags
        sh["ru_linked"] = str(sh["mmsi"])[:3] == "273" or sh["port_id"] in RU_PORT_IDS
        out.append(sh)
    out.sort(key=lambda x: (not x.get("gas"), x.get("laden") is not True, x.get("route_km") or 1e9))
    return {"updated": iso(now), "total": len(out), "gas": sum(1 for x in out if x.get("gas")),
            "tankers": sum(1 for x in out if not x.get("gas")),
            "laden": sum(1 for x in out if x.get("laden")),
            "ships": out, "arrived": arrived[-80:],
            "_state_ships": list(ships.values())}


async def _stream(key, boxes, types, seconds, on_msg, mmsi_filter=None, label=""):
    """Viens aisstream savienojums ar atkārtotu pieslēgšanos, līdz beidzas laiks."""
    import websockets
    loop = asyncio.get_event_loop()
    end = loop.time() + seconds
    n = 0
    while loop.time() < end - 5:
        sub = {"APIKey": key, "BoundingBoxes": boxes, "FilterMessageTypes": types}
        if mmsi_filter:
            sub["FiltersShipMMSI"] = [str(m) for m in mmsi_filter][:50]
        try:
            async with websockets.connect("wss://stream.aisstream.io/v0/stream", max_size=2**22,
                                          ping_interval=20, ping_timeout=60) as ws:
                await ws.send(json.dumps(sub))
                while loop.time() < end:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=max(1, end - loop.time()))
                    except asyncio.TimeoutError:
                        break
                    n += 1
                    on_msg(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
        except Exception as e:  # savienojums pārtrūka: mēģina vēlreiz
            print(f"aisstream {label}: {type(e).__name__}: {e}")
            await asyncio.sleep(2)
    return n


async def listen(key, seconds, tracked=()):
    """Trīs savienojumi: (1) Baltija un pieejas — viss; (2) visa pasaule — tikai kuģu statiskie dati,
    patur tikai ar galamērķi Baltijas valstīs; (3) pozīcijas jau sekotajiem kuģiem ārpus reģiona."""
    msgs = []
    world_keep = set()

    def on_region(raw):
        m = json.loads(raw)
        if "error" in m:
            raise RuntimeError(f"aisstream kļūda: {m['error']}")
        msgs.append(m)

    def on_world_static(raw):
        g = _DEST_RX.search(raw)
        if not g:
            return
        dest = g.group(1)
        lv = dest_port_of(dest)
        if not lv and not baltic_port_of(dest):
            return
        m = json.loads(raw)
        if not lv:
            st = m.get("Message", {}).get("ShipStaticData", {})
            if not is_energy_ship(st.get("Name"), st.get("Type")):
                return
        meta = m.get("MetaData", {})
        if in_region(meta.get("latitude"), meta.get("longitude")):
            return  # reģiona savienojums to jau dzird
        msgs.append(m)
        world_keep.add(meta.get("MMSI"))
        # pozīcija no metadatiem (ātrums nav zināms)
        msgs.append({"MetaData": {"MMSI": meta.get("MMSI"), "time_utc": meta.get("time_utc", "")},
                     "Message": {"PositionReport": {"Latitude": meta.get("latitude"),
                                                    "Longitude": meta.get("longitude"),
                                                    "Sog": None, "Cog": None}}})

    def on_tracked(raw):
        m = json.loads(raw)
        meta = m.get("MetaData", {})
        if not in_region(meta.get("latitude"), meta.get("longitude")):
            msgs.append(m)

    tasks = [_stream(key, BOXES, ["PositionReport", "ShipStaticData", "StandardClassBPositionReport"],
                     seconds, on_region, label="Baltija"),
             _stream(key, WORLD, ["ShipStaticData"], seconds, on_world_static, label="pasaule")]
    tracked = list(dict.fromkeys(tracked))
    for i in range(0, min(len(tracked), 100), 50):
        tasks.append(_stream(key, WORLD, ["PositionReport"], seconds, on_tracked,
                             mmsi_filter=tracked[i:i + 50], label=f"sekotie{i // 50 + 1}"))
    counts = await asyncio.gather(*tasks)
    print(f"aisstream: Baltija {counts[0]} ziņas, pasaules statiskie {counts[1]} "
          f"(no tiem uz Baltijas valstīm {len(world_keep)} kuģi)"
          + (f", sekoto pozīcijas {sum(counts[2:])}" if tracked else ""))
    return msgs


def main():
    key = os.environ.get("AISSTREAM_API_KEY")
    if not key:
        sys.exit("Nav AISSTREAM_API_KEY (GitHub: Settings → Secrets and variables → Actions)")
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 240
    DATA.mkdir(parents=True, exist_ok=True)
    state = json.loads(LATEST.read_text()) if LATEST.exists() else {}
    vessels = json.loads(VESSELS.read_text()) if VESSELS.exists() else {}
    # Digitraffic pirmais, lai svaigākās aisstream ziņas (pēc tam) virsrakstītu tās pašas MMSI pozīcijas
    _inb_path = INBOUND_FILE if INBOUND_FILE.exists() else None
    _tracked = []
    for _f, _k in ((ENERGY_FILE, "_state_ships"), (INBOUND_FILE, "ships")):
        if _f.exists():
            _tracked += [x["mmsi"] for x in json.loads(_f.read_text()).get(_k, [])
                         if x.get("lat") is not None and not in_region(x["lat"], x["lon"])]
    msgs = fetch_digitraffic() + asyncio.run(listen(key, seconds, _tracked))
    new_state, events = process(msgs, state, vessels, now_utc())
    LATEST.write_text(json.dumps(new_state, ensure_ascii=False, indent=1))
    if events:
        with CALLS.open("a") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    PORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(TANKER_CACHE.read_text()) if TANKER_CACHE.exists() else {}
    global _SANCTIONS
    _SANCTIONS = update_sanctions()
    summary, cache = process_ports(msgs, cache, vessels, now_utc())
    print(f"Militārie / dienesta kuģi: {len(summary['service_ships'])}")
    print(f"Krievijai piesaistīti tankkuģi: {len(summary['ru_tankers'])}, no tiem sankciju sarakstā: "
          f"{sum(1 for x in summary['ru_tankers'] if x['sanctioned'])}, ēnu flotes sarakstā: "
          f"{sum(1 for x in summary['ru_tankers'] if x['shadow_listed'])}")
    PORTS_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    TANKER_CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")))
    old_lv = INBOUND_FILE.parent / "inbound_lv.json"
    src = INBOUND_FILE if INBOUND_FILE.exists() else old_lv
    inbound_state = json.loads(src.read_text()) if src.exists() else {}
    energy_state = json.loads(ENERGY_FILE.read_text()) if ENERGY_FILE.exists() else {}
    energy = process_energy(msgs, {"ships": energy_state.get("_state_ships", []),
                                   "arrived": energy_state.get("arrived", [])}, vessels, _SANCTIONS, now_utc())
    ENERGY_FILE.write_text(json.dumps(energy, ensure_ascii=False, indent=1))
    print(f"Enerģija uz Baltiju: {energy['gas']} gāzes kuģi, {energy['tankers']} tankkuģi, ar kravu {energy['laden']}")
    inbound = process_inbound(msgs, inbound_state, vessels, now_utc())
    INBOUND_FILE.write_text(json.dumps(inbound, ensure_ascii=False, indent=1))
    print(f"Ceļā uz Baltijas ostām: {inbound['total']} {inbound['by_port']}")
    print(f"Tankkuģi ostās: {summary['total_in_ports']} (zināmi tankkuģi: {summary['tankers_known']})")
    for p in summary["ports"]:
        print(f"  {p['name']:<16} {len(p['tankers'])}")
    print(f"Ziņas: {len(msgs)}, kuģi sarakstā: {len(new_state['ships'])}, notikumi: {len(events)}")
    for s in new_state["ships"][:10]:
        print(f"  {s['status']:<9} {s.get('name') or s['mmsi']:<24} iegrime {s.get('draught')} m  galamērķis {s.get('destination')}")


if __name__ == "__main__":
    main()
