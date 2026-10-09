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
    print(f"Ziņas: {len(msgs)}, kuģi sarakstā: {len(new_state['ships'])}, notikumi: {len(events)}")
    for s in new_state["ships"][:10]:
        print(f"  {s['status']:<9} {s.get('name') or s['mmsi']:<24} iegrime {s.get('draught')} m  galamērķis {s.get('destination')}")


if __name__ == "__main__":
    main()
