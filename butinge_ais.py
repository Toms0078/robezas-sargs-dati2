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
BOXES = [[[53.0, 3.0], [66.0, 31.0]]]
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
    for lim, dwt in ((150, 12000), (185, 35000), (200, 50000), (235, 75000),
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
    t = ship.get("draught")
    if t and tmax:
        tb = 0.45 * tmax                     # balasta iegrime ≈ 45 % no maksimālās
        f = max(0.0, min(1.0, (t - tb) / (tmax - tb)))
        ship["load_pct"] = round(f * 100)
        ship["empty_pct"] = 100 - ship["load_pct"]
        ship["cargo_t_est"] = round(f * dwt * 0.95 / 100) * 100 if dwt else None
    else:
        ship["load_pct"] = ship["empty_pct"] = ship["cargo_t_est"] = None
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
            out.append(load_estimate(sh, vessels))

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
]
CACHE_DAYS = 14


def is_tanker(t):
    return t is not None and 80 <= t <= 89


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
        if is_tanker(s.get("Type")):
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
            cache.pop(key)  # tips mainījies, vairs nav tankkuģis
    for mmsi in pos:
        if str(mmsi) in cache:
            cache[str(mmsi)]["seen"] = iso(now)
    cutoff = iso(now - timedelta(days=CACHE_DAYS))
    cache = {k: v for k, v in cache.items() if v["seen"] >= cutoff}

    ports = []
    for pid, name, cc, lat, lon, r in PORTS:
        ports.append({"id": pid, "name": name, "country": cc, "lat": lat, "lon": lon,
                      "radius_km": r, "ships_heard": 0, "tankers": []})
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
        if str(mmsi) in cache and p.get("Latitude") is not None and abs(p["Latitude"]) <= 90:
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
            port["tankers"].append(load_estimate(sh, vessels))
            break
    for port in ports:
        port["tankers"].sort(key=lambda s: (s["status"] == "kustībā", s.get("name") or ""))
    summary = {
        "updated": iso(now),
        "tankers_known": len(cache),
        "total_in_ports": sum(len(p["tankers"]) for p in ports),
        "tankers_heard_now": sum(1 for m in pos if str(m) in cache),
        "tanker_cells": dict(sorted(where.items(), key=lambda x: -x[1])[:25]),
        "ports": ports,
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
INBOUND_DAYS = 7         # kuģi, kas nav dzirdēti tik ilgi, izmet
ARRIVED_KM = 12          # tuvāk ostai par šo = ieradies, izņem no saraksta

TYPE_LV = [(80, 89, "tankkuģis"), (70, 79, "kravas kuģis"), (60, 69, "pasažieru/prāmis"),
           (30, 30, "zvejas"), (31, 32, "velkonis"), (52, 52, "velkonis")]


def type_name(t):
    for a, b, n in TYPE_LV:
        if t is not None and a <= t <= b:
            return n
    return "cits"


def dest_port_of(dest):
    d = (dest or "").upper()
    for pid, name, cc, rx, center, _ in DEST_PORTS:
        if re.search(rx, d):
            return pid, name, center
    return None


lv_port_of = dest_port_of

# Kuģu ceļu tīkls Baltijas jūrā un tās pieejās (mezgli un jūras ceļi starp tiem).
# Ar to aprēķina ceļa garumu un simulē kustību, kad kuģis vairs nav dzirdams.
NODES = {
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
    "gdanskBay": (54.70, 18.90, "Gdaņskas līcis"),
}
EDGES = [
    ("norwayW", "lindesnes"), ("lindesnes", "skagen"), ("skagen", "oresundN"), ("oresundN", "oresundS"), ("oresundS", "bornholm"),
    ("fehmarn", "gedser"), ("gedser", "bornholm"), ("gedser", "oresundS"), ("bornholm", "bornholmE"),
    ("bornholmE", "hoburg"), ("bornholmE", "klaipedaW"), ("bornholmE", "gdanskBay"), ("gdanskBay", "klaipedaW"),
    ("klaipedaW", "liepajaW"), ("liepajaW", "ventspilsW"), ("hoburg", "liepajaW"), ("hoburg", "gotlandE"),
    ("gotlandE", "ventspilsW"), ("gotlandE", "faro"), ("faro", "gofW"), ("faro", "aland"), ("aland", "bothnia"),
    ("aland", "gofW"), ("gofW", "paldiskiApp"), ("paldiskiApp", "tallinnApp"), ("tallinnApp", "gofEast"),
    ("ventspilsW", "irbe"), ("irbe", "gorMid"), ("gorMid", "rigaApp"), ("gorMid", "gorNorth"),
    ("gorNorth", "parnuApp"), ("gorNorth", "rigaApp"),
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

    out = [load_estimate(s, vessels) if s.get("type") == "tankkuģis" else s for s in ships.values()]
    out.sort(key=lambda s: (s["port"], s.get("dist_km") or 1e9))
    counts = {}
    for s in out:
        counts[s["port"]] = counts.get(s["port"], 0) + 1
    return {"updated": iso(now), "total": len(out), "by_port": counts,
            "ships": out, "arrived": arrived[-60:]}


async def listen(key, seconds):
    import websockets  # importē tikai šeit, lai process() var testēt bez tā
    sub = {"APIKey": key, "BoundingBoxes": BOXES,
           "FilterMessageTypes": ["PositionReport", "ShipStaticData", "StandardClassBPositionReport"]}
    msgs = []
    loop = asyncio.get_event_loop()
    end = loop.time() + seconds
    async with websockets.connect("wss://stream.aisstream.io/v0/stream", max_size=2**22) as ws:
        await ws.send(json.dumps(sub))
        while loop.time() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(1, end - loop.time()))
            except asyncio.TimeoutError:
                break
            m = json.loads(raw)
            if "error" in m:
                raise RuntimeError(f"aisstream kļūda: {m['error']}")
            msgs.append(m)
    return msgs


def main():
    key = os.environ.get("AISSTREAM_API_KEY")
    if not key:
        sys.exit("Nav AISSTREAM_API_KEY (GitHub: Settings → Secrets and variables → Actions)")
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 240
    DATA.mkdir(parents=True, exist_ok=True)
    state = json.loads(LATEST.read_text()) if LATEST.exists() else {}
    vessels = json.loads(VESSELS.read_text()) if VESSELS.exists() else {}
    msgs = asyncio.run(listen(key, seconds))
    new_state, events = process(msgs, state, vessels, now_utc())
    LATEST.write_text(json.dumps(new_state, ensure_ascii=False, indent=1))
    if events:
        with CALLS.open("a") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    PORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(TANKER_CACHE.read_text()) if TANKER_CACHE.exists() else {}
    summary, cache = process_ports(msgs, cache, vessels, now_utc())
    PORTS_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    TANKER_CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")))
    old_lv = INBOUND_FILE.parent / "inbound_lv.json"
    src = INBOUND_FILE if INBOUND_FILE.exists() else old_lv
    inbound_state = json.loads(src.read_text()) if src.exists() else {}
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
