"""Būtiņģes naftas terminālis un Klaipēdas LNG terminālis: piegāžu uzskaite un simulācija.

Avots: Global Fishing Watch ostu apmeklējumi (port visits) apgabalā ap Būtiņģes boju un ap
Klaipēdas peldošo LNG krātuvi (FSRU) pēdējo 365 dienu laikā; kuģu reģistra dati (GT, garums)
un iepriekšējā osta (no kurienes kuģis atbrauca).

Novērtējumi (skaidri atzīmēti lapā kā aplēses):
  * jēlnafta: DWT ≈ 1,85 × GT; krava ≈ 95 % no DWT; 1 t ≈ 7,33 barelas
  * LNG: kravas tilpums ≈ 1,5 × GT m³ (lieliem), piegāde ≈ 95 %; 1 m³ LNG ≈ 6,9 MWh ≈ 585 m³ gāzes
  * FSRU krātuve 170 000 m³; aizpildījums – simulācija: piegādes mīnus vidējā izsūtīšana

Rezultāts: data/terminals/latest.json
Palaišana:  GFW_TOKEN=... python terminals.py [--test]
"""
import json
import math
import re
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = "https://gateway.api.globalfishingwatch.org/v3"
OUT = Path(__file__).parent / "data" / "terminals"
CACHE = OUT / "vessel_cache.json"
UA = "robezas-sargs (github.com/Toms0078/robezas-sargs-dati2)"

BUTINGE = {"id": "butinge", "name": "Būtiņģes SPM boja", "lat": 56.062, "lon": 20.958, "r_km": 4.0}
# Klaipēdas FSRU vieta tiek precizēta pēc paša FSRU "INDEPENDENCE" ostas apmeklējumiem
KLAIPEDA_LNG = {"id": "klaipeda_lng", "name": "Klaipēdas LNG (FSRU Independence)", "lat": 55.6645, "lon": 21.1375,
                "r_km": 1.0, "search_box": (55.645, 55.685, 21.105, 21.170),
                # plašāks apgabals ar ārējo reidu: ostas apmeklējuma "position" bieži ir pirmā enkurvieta
                "visit_box": (55.55, 55.85, 20.70, 21.20)}
FSRU_CAPACITY_M3 = 170000
TRANSIT = ("PORT SAID", "SUEZ CANAL", "GIBRALTAR", "SKAGEN", "KIEL", "BRUNSBUTTEL", "CANAKKALE", "ISTANBUL")


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def call(token, path, params=None, body=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                              "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:400]
            if e.code in (429, 503) and attempt < 2:
                time.sleep(20)
                continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")


def box(lat0, lat1, lon0, lon1):
    return {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]}


def port_visits_in(token, geom, start, end):
    out, offset = [], 0
    while True:
        res = call(token, "/events", {"limit": 500, "offset": offset, "sort": "-start"},
                   {"datasets": ["public-global-port-visits-c2-events:latest"], "confidences": ["2", "3", "4"],
                    "startDate": start, "endDate": end, "geometry": geom})
        ent = res.get("entries", [])
        out += ent
        if not res.get("nextOffset") or len(ent) == 0 or len(out) >= 5000:
            break
        offset = res["nextOffset"]
    return out


def vessel_info(token, ids, cache):
    need = [i for i in ids if i not in cache]
    for k in range(0, len(need), 20):
        chunk = need[k:k + 20]
        params = {"datasets[0]": "public-global-vessel-identity:latest"}
        for j, i in enumerate(chunk):
            params[f"ids[{j}]"] = i
        try:
            res = call(token, "/vessels", params)
        except Exception as e:
            print("vessel_info:", e)
            continue
        for ent in res.get("entries", []):
            reg = (ent.get("registryInfo") or [{}])[0] if ent.get("registryInfo") else {}
            sri = ent.get("selfReportedInfo") or []
            types = [t.get("name") for c in ent.get("combinedSourcesInfo") or [] for t in c.get("shiptypes") or []]
            info = {"gt": reg.get("tonnageGt"), "length": reg.get("lengthM"), "imo": reg.get("imo") or
                    next((s.get("imo") for s in sri if s.get("imo")), None),
                    "name": (sri[0].get("shipname") if sri else None) or reg.get("shipname"),
                    "flag": (sri[0].get("flag") if sri else None) or reg.get("flag"),
                    "geartypes": reg.get("geartypes"), "shiptypes": types}
            for s in sri:
                cache[s.get("id")] = info
            for c in ent.get("combinedSourcesInfo") or []:
                cache[c.get("vesselId")] = info
        time.sleep(1)
    return cache


def previous_port(token, vessel_id, before, here_pos, cache):
    key = f"prev:{vessel_id}:{before[:10]}"
    if key in cache:
        return cache[key]
    start = (datetime.fromisoformat(before[:10]) - timedelta(days=90)).date().isoformat()
    try:
        res = call(token, "/events", {"limit": 10, "offset": 0, "sort": "-start"},
                   {"datasets": ["public-global-port-visits-c2-events:latest"], "vessels": [vessel_id],
                    "confidences": ["3", "4"], "startDate": start, "endDate": before[:10]})
    except Exception as e:
        print("previous_port:", e)
        return None
    best = None
    for e in sorted(res.get("entries", []), key=lambda x: x.get("start") or "", reverse=True):
        if (e.get("end") or "") > before:
            continue
        pv = e.get("port_visit") or {}
        anch = pv.get("intermediateAnchorage") or pv.get("startAnchorage") or {}
        name = (anch.get("topDestination") or anch.get("name") or "").upper()
        pos = (e.get("position") or {})
        if pos and km((pos.get("lat", 0), pos.get("lon", 0)), here_pos) < 30:
            continue  # tā pati vieta
        if any(t in name for t in TRANSIT) and (pv.get("durationHrs") or 0) < 20:
            continue
        best = {"port": name.title(), "country": anch.get("flag"), "end": e.get("end")}
        break
    cache[key] = best
    time.sleep(0.5)
    return best


def anchor_min_km(e, pos):
    """Mazākais attālums no ostas apmeklējuma enkurvietām (sākuma/starpposma/beigu) līdz vietai."""
    pv = e.get("port_visit") or {}
    best = 9999.0
    for k in ("startAnchorage", "intermediateAnchorage", "endAnchorage"):
        a = pv.get(k) or {}
        if a.get("lat") is not None:
            best = min(best, km((a["lat"], a["lon"]), pos))
    p = e.get("position") or {}
    if p.get("lat") is not None:
        best = min(best, km((p["lat"], p["lon"]), pos))
    return best


KL_PORT = (55.715, 21.06)   # Klaipēdas osta + reids (apmeklējumi ≤ 30 km)
# LNG eksporta termināļi (kuģis, kas tur stāvējis ≥ 8 h, ir LNG tankkuģis)
LNG_EXPORT = {"Hammerfest (Melkøya)": (70.684, 23.600, 6), "Sabine Pass": (29.745, -93.870, 4),
              "Cameron LNG": (30.035, -93.330, 4), "Calcasieu Pass": (29.770, -93.340, 4),
              "Plaquemines": (29.460, -89.624, 2), "Corpus Christi": (27.885, -97.260, 2.5),
              "Freeport": (28.935, -95.310, 2.5), "Cove Point": (38.400, -76.383, 4), "Elba Island": (32.087, -81.000, 3),
              "Ras Laffan": (25.900, 51.580, 6), "Idku": (31.330, 30.300, 4), "Point Fortin": (10.180, -61.690, 4),
              "Soyo": (-6.100, 12.350, 6), "Bioko": (3.770, 8.700, 5)}
# LNG importa/pārkraušanas termināļi (daļēja krava var nākt no turienes)
LNG_TERM = {"Zeebrugge LNG": (51.343, 3.207, 2), "Gate (Roterdama)": (51.970, 4.030, 2.5), "Dunkerque LNG": (51.040, 2.208, 2),
            "Montoir": (47.300, -2.130, 2.5), "Isle of Grain": (51.440, 0.720, 2.5), "Svinoujscie LNG": (53.925, 14.270, 2),
            "Inkoo FSRU": (60.030, 24.000, 3), "Wilhelmshaven FSRU": (53.590, 8.160, 3), "Brunsbuttel FSRU": (53.890, 9.200, 2),
            "Mukran FSRU": (54.480, 13.610, 3), "Skagen (gaida)": (57.687, 10.719, 8)}
GAS_NAME = re.compile(r"LNG|(^|[^A-Z])GAS|GAS($|[^A-Z])|HOEGH|GASLOG|CLIPPER")


def is_lng_candidate(name, info, flag, n_visits, length):
    gtypes = " ".join((info.get("geartypes") or []) + (info.get("shiptypes") or [])).upper()
    gt = info.get("gt") or 0
    if not name or "INDEPENDENCE" in name:
        return False
    if GAS_NAME.search(name):
        return True
    if any(t in gtypes for t in ("FISH", "TRAWL", "PASSENGER", "SEISMIC", "CARGO", "CONTAINER", "REEFER",
                                 "CARRIER", "TUG", "DREDGE", "PILOT", "BUNKER")):
        return False
    if flag == "LTU" or "PILOT" in name or name.startswith("LT-"):
        return False
    if n_visits > 12 or (gt and gt < 3000) or (length and length < 90):
        return False
    return True


def lng_cap(length, gt):
    if length >= 260 or gt > 80000:
        return 170000
    if length >= 200 or gt > 40000:
        return 140000
    if length >= 120 or gt > 8000:
        return 30000
    if length:
        return 7500
    return 150000  # nezināms izmērs: tipisks lielais LNG tankkuģis


def anch_info(e):
    pv = e.get("port_visit") or {}
    a = pv.get("intermediateAnchorage") or pv.get("startAnchorage") or pv.get("endAnchorage") or {}
    return a, pv


def lng_deliveries(token, cache, near_events, visits_per_vessel, ais_len, start, end, test=False):
    """Katram LNG kuģa kandidātam ielasa visus gada ostu apmeklējumus un saskaita Klaipēdas reisus.
    Atgriež (lielās piegādes, mazie LNG kuģi)."""
    here = (KLAIPEDA_LNG["lat"], KLAIPEDA_LNG["lon"])
    cands = {}
    for e in near_events:
        v = e.get("vessel") or {}
        info = cache.get(v.get("id")) or {}
        name = (v.get("name") or info.get("name") or "").upper()
        dur = (e.get("port_visit") or {}).get("durationHrs") or 0
        length = (ais_len.get(str(v.get("ssvid"))) or {}).get("length") or info.get("length") or 0
        if dur < 6 or dur > 24 * 20:
            continue
        if is_lng_candidate(name, info, v.get("flag") or "", visits_per_vessel.get(v.get("id"), 0), length):
            cands.setdefault(name, {"id": v.get("id"), "mmsi": v.get("ssvid"), "flag": v.get("flag"),
                                    "gt": info.get("gt") or 0, "imo": info.get("imo"), "length": length,
                                    "fsru": anchor_min_km(e, here) <= 0.5, "ais_type": (ais_len.get(str(v.get("ssvid"))) or {}).get("type")})
    # papildus: LNG kuģi, ko redzam paši AIS (ceļā uz Baltiju vai Baltijā)
    extra = []
    for fn, key in (("latest.json", "gas_ships"), ("energy_inbound.json", "ships")):
        pth = Path(__file__).parent / "data" / "ports" / fn
        if pth.exists():
            for g in json.loads(pth.read_text()).get(key, []):
                if (g.get("gas_kind") == "LNG" or g.get("gas")) and (g.get("length") or 0) >= 150 and g.get("imo"):
                    extra.append(g)
    for g in extra:
        nm = (g.get("name") or "").upper()
        if not nm or nm in cands or "INDEPENDENCE" in nm:
            continue
        ck = f"imo:{g['imo']}"
        if ck not in cache:
            try:
                res = call(token, "/vessels/search", {"query": str(g["imo"]), "limit": 3,
                                                      "datasets[0]": "public-global-vessel-identity:latest"})
                ids = [i.get("id") for ent in res.get("entries", []) for i in ent.get("selfReportedInfo") or []
                       if str(i.get("imo")) == str(g["imo"])]
                cache[ck] = ids[0] if ids else None
            except Exception as ex:
                print("search:", ex)
                cache[ck] = None
            time.sleep(0.5)
        if cache.get(ck):
            cands[nm] = {"id": cache[ck], "mmsi": g.get("mmsi"), "flag": None, "gt": 0, "imo": g.get("imo"),
                         "length": g.get("length") or 0}
    print(f"LNG kuģu kandidāti: {len(cands)}: {', '.join(sorted(cands))[:900]}")

    big, small = [], []
    for name, c in cands.items():
        key = f"pv365c:{c['id']}:{end.isoformat()}"
        if key not in cache:
            try:
                res = call(token, "/events", {"limit": 200, "offset": 0, "sort": "-start"},
                           {"datasets": ["public-global-port-visits-c2-events:latest"], "vessels": [c["id"]],
                            "confidences": ["2", "3", "4"], "startDate": start.isoformat(),
                            "endDate": end.isoformat()})
            except Exception as ex:
                print(name, ex)
                continue
            evs = []
            for e in res.get("entries", []):
                a, pv = anch_info(e)
                evs.append({"start": e.get("start"), "end": e.get("end"), "h": round(pv.get("durationHrs") or 0, 1),
                            "port": (a.get("topDestination") or a.get("name") or "").strip(), "cc": a.get("flag"),
                            "aid": a.get("id") or "", "kl_km": round(anchor_min_km(e, KL_PORT), 1),
                            "lng_exp": next((n for n, pp in LNG_EXPORT.items() if anchor_min_km(e, pp[:2]) <= pp[2]), None),
                            "lng_term": next((n for n, pp in LNG_TERM.items() if anchor_min_km(e, pp[:2]) <= pp[2]), None),
                            "fsru_km": round(anchor_min_km(e, here), 2)})
            cache[key] = sorted(evs, key=lambda x: x["start"] or "")
            time.sleep(0.6)
        evs = cache[key]
        gasname = bool(GAS_NAME.search(name))
        exp = [x["lng_exp"] for x in evs if x.get("lng_exp") and x["h"] >= 12]
        gt = c["gt"]
        # LNG pazīmes: nosaukums; vai GT 85–140 tūkst. (LNG kuģiem GT ir liels attiecībā pret izmēru;
        # Aframax/Suezmax naftas tankkuģi ir 55–85 tūkst.); vai reģistrā nav, bet kuģis krauj LNG eksporta terminālī
        if gasname or 85000 <= gt <= 140000:
            ok = True
        elif gt:
            ok = False
        else:
            ok = bool(exp)
        strong = gasname or 85000 <= gt <= 140000
        if c.get("ais_type") and 70 <= c["ais_type"] <= 79:
            ok = False  # AIS: kravas kuģis
        if not ok:
            continue
        groups, cur = [], None
        for ev in evs:
            in_kl = ev["kl_km"] <= 30 or ev["aid"].startswith("ltu-klaipeda")
            if in_kl:
                if cur and (datetime.fromisoformat(ev["start"][:19]) -
                            datetime.fromisoformat(cur["end"][:19])).total_seconds() < 3 * 86400:
                    cur["end"] = ev["end"]
                    cur["hours"] += ev["h"]
                    cur["fsru"] = cur["fsru"] or ev["fsru_km"] <= 0.5
                else:
                    prev, src = None, None
                    t0 = datetime.fromisoformat(ev["start"][:19])
                    for pe in reversed([x for x in evs if (x["end"] or "") <= ev["start"]]):
                        if pe["kl_km"] <= 30 or pe["aid"].startswith("ltu-klaipeda"):
                            continue
                        pn = pe["port"].upper()
                        if "SKAGEN" in pn or pe.get("lng_term") == "Skagen (gaida)":
                            continue  # gaidīšana pie Skāgenas
                        if any(t in pn for t in TRANSIT) and pe["h"] < 20:
                            continue
                        if pe["h"] < 3:
                            continue
                        prev = {"port": pe.get("lng_exp") or pe.get("lng_term") or pe["port"].title(),
                                "country": pe["cc"], "end": pe["end"], "lng_export": bool(pe.get("lng_exp"))}
                        if (t0 - datetime.fromisoformat(pe["end"][:19])).days <= 60:
                            src = pe.get("lng_exp") or pe.get("lng_term")
                        break
                    cur = {"start": ev["start"], "end": ev["end"], "hours": ev["h"], "fsru": ev["fsru_km"] <= 0.5,
                           "from": prev, "src": src}
                    groups.append(cur)
            else:
                cur = None
        cap = lng_cap(c["length"], c["gt"])
        for g in groups:
            if g["hours"] < 8 or g["hours"] > 240:
                continue
            if not strong and not g["src"]:
                continue  # pirms Klaipēdas nav bijis LNG terminālī: visticamāk nav LNG krava
            row = {"start": g["start"], "end": g["end"], "hours": round(g["hours"], 1), "name": name,
                   "mmsi": c["mmsi"], "flag": c["flag"], "imo": c["imo"], "gt": c["gt"],
                   "length": c["length"] or None, "volume": round(cap * 0.95, -2), "at_fsru_seen": g["fsru"],
                   "from": g["from"], "lng_source": g["src"]}
            (small if cap <= 30000 else big).append(row)
        if test or groups:
            print(f"  {name}: Klaipēdā {len(groups)} reisi, garums {c['length']}, ~{cap} m³, eksports: {sorted(set(exp))}")
    big.sort(key=lambda r: r["start"])
    small.sort(key=lambda r: r["start"])
    return big, small


def summarize_calls(calls, kind):
    by_month, by_country = {}, {}
    for c in calls:
        m = c["start"][:7]
        g = by_month.setdefault(m, {"calls": 0, "volume": 0})
        g["calls"] += 1
        g["volume"] += c.get("volume") or 0
        cc = (c.get("from") or {}).get("country") or "nav zināms"
        h = by_country.setdefault(cc, {"calls": 0, "volume": 0})
        h["calls"] += 1
        h["volume"] += c.get("volume") or 0
    starts = sorted(c["start"] for c in calls)
    gaps = [(datetime.fromisoformat(b[:19]) - datetime.fromisoformat(a[:19])).total_seconds() / 86400
            for a, b in zip(starts, starts[1:])]
    return {"calls": len(calls), "by_month": dict(sorted(by_month.items())),
            "by_country": dict(sorted(by_country.items(), key=lambda x: -x[1]["calls"])),
            "avg_gap_days": round(sum(gaps) / len(gaps), 1) if gaps else None,
            "total_volume": sum(c.get("volume") or 0 for c in calls), "unit": "t" if kind == "crude" else "m3"}


def lng_level_sim(deliveries, days=365):
    """Krātuves aizpildījuma simulācija pa dienām.
    Piegāde pievieno kuģa kravu (krātuve nevar pārsniegt 100 %, pārpalikums paliek kuģī un tiek pārsūknēts
    nākamajās dienās). Izsūtīšana tīklā: vidējais ātrums (gada piegādes / dienas), ko pielāgo līmenim –
    pilnākā krātuvē izsūta vairāk, tukšākā mazāk (kā operators to dara praksē). Sākuma līmenis: ~1 mēneša iesildīšana."""
    if not deliveries:
        return None
    cap = FSRU_CAPACITY_M3
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    ev = sorted((datetime.fromisoformat(d["start"][:19]).replace(tzinfo=timezone.utc), d["volume"] or 0)
                for d in deliveries)
    span_days = max((end - max(start, ev[0][0])).total_seconds() / 86400, 30)
    total = sum(v for t, v in ev if t >= start)
    rate = total / span_days

    def run(level):
        pts, pending, t, i = [], 0.0, start, 0
        while t <= end:
            while i < len(ev) and ev[i][0] < t + timedelta(days=1):
                pending += ev[i][1] if ev[i][0] >= start else 0
                i += 1
            move = min(pending, cap - level, 120000.0)   # pārsūknēšana ≤ ~5 000 m³/h
            level += move
            pending -= move
            out = rate * max(0.1, min(1.6, level / (0.55 * cap)))
            out = min(out, max(0.0, level - 0.05 * cap))     # ~5 % paliek kā "papēdis" (heel)
            level -= out
            pts.append([t.strftime("%Y-%m-%d"), level / cap * 100])
            t += timedelta(days=1)
        return pts, level

    pts, last = run(0.5 * cap)
    pts, _ = run(sum(p[1] for p in pts[-60:]) / 60 / 100 * cap)   # sākums = tipiskais līmenis
    return {"rate_m3_day": round(rate), "rate_mcm_day": round(rate * 585 / 1e6, 2),
            "series": [[d, round(v, 1)] for d, v in pts], "now_pct": round(pts[-1][1], 1),
            "assumptions": "izsūtīšana = vidējā no gada piegādēm, pielāgota līmenim (0,1–1,6×), ≥5 % paliek krātuvē; pārsūknēšana ≤ 120 tūkst. m³/d"}


def main():
    token = os.environ.get("GFW_TOKEN")
    if not token:
        sys.exit("Nav GFW_TOKEN")
    OUT.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    end = date.today()
    start = end - timedelta(days=365)
    test = "--test" in sys.argv

    # --- Klaipēdas FSRU precīzā vieta
    lat0, lat1, lon0, lon1 = KLAIPEDA_LNG["search_box"]
    kl_all = port_visits_in(token, box(lat0, lat1, lon0, lon1), start.isoformat(), end.isoformat())
    print(f"Klaipēdas ostas apmeklējumi: {len(kl_all)}")
    if test and kl_all:
        print(json.dumps(kl_all[0])[:1500])
    fsru = [e for e in kl_all if "INDEPENDENCE" in ((e.get("vessel") or {}).get("name") or "").upper()]
    if fsru:
        p = fsru[0].get("position") or {}
        KLAIPEDA_LNG["lat"], KLAIPEDA_LNG["lon"] = p.get("lat", KLAIPEDA_LNG["lat"]), p.get("lon", KLAIPEDA_LNG["lon"])
        print(f"FSRU INDEPENDENCE vieta: {KLAIPEDA_LNG['lat']:.4f}, {KLAIPEDA_LNG['lon']:.4f}")
    else:
        print("FSRU INDEPENDENCE apmeklējumi nav atrasti, izmanto aptuveno vietu")

    here = (KLAIPEDA_LNG["lat"], KLAIPEDA_LNG["lon"])
    # LNG kuģu kandidāti: kuģi, kas pēdējo 3 gadu laikā stāvējuši tieši pie FSRU
    start3 = end - timedelta(days=3 * 365)
    kl3 = port_visits_in(token, box(lat0, lat1, lon0, lon1), start3.isoformat(), end.isoformat())
    kl_all = [e for e in kl3 if anchor_min_km(e, here) <= 0.5]
    print(f"Klaipēdas FSRU apgabala apmeklējumi 3 gados: {len(kl3)}, pie FSRU: {len(kl_all)}")
    # GFW bieži piesaista LNG kuģa apmeklējumu vispārējai Klaipēdas enkurvietai vai ārējam reidam
    roads = []
    for bx in ((55.720, 55.732, 21.085, 21.100), (55.74, 55.86, 20.70, 21.02)):
        roads += port_visits_in(token, box(*bx), start.isoformat(), end.isoformat())
    print(f"Klaipēdas reida/enkurvietu apmeklējumi gadā: {len(roads)}")

    # --- Būtiņģe
    b = BUTINGE
    d = 0.06
    bt_all = port_visits_in(token, box(b["lat"] - d, b["lat"] + d, b["lon"] - 2 * d, b["lon"] + 2 * d),
                            start.isoformat(), end.isoformat())
    print(f"Būtiņģes apgabala apmeklējumi: {len(bt_all)}")
    if test and bt_all:
        print(json.dumps(bt_all[0])[:1500])

    ids = list({(e.get("vessel") or {}).get("id") for e in bt_all + kl_all + roads if (e.get("vessel") or {}).get("id")})
    vessel_info(token, ids, cache)
    ais_path = Path(__file__).parent / "data" / "ports" / "tankers_cache.json"
    ais_len = json.loads(ais_path.read_text()) if ais_path.exists() else {}
    visits_per_vessel = {}
    for e in kl_all:
        vid = (e.get("vessel") or {}).get("id")
        visits_per_vessel[vid] = visits_per_vessel.get(vid, 0) + 1

    def build(events, site, kind):
        calls = []
        for e in events:
            v = e.get("vessel") or {}
            pos = e.get("position") or {}
            if not pos or anchor_min_km(e, (site["lat"], site["lon"])) > site["r_km"]:
                continue
            info = cache.get(v.get("id")) or {}
            name = (v.get("name") or info.get("name") or "").upper()
            gt = info.get("gt") or 0
            dur = ((e.get("port_visit") or {}).get("durationHrs") or 0)
            if kind == "crude":
                if gt < 20000 or dur < 8 or "INDEPENDENCE" in name:
                    continue
                dwt = gt * 1.85
                vol = round(dwt * 0.95, -2)
            else:
                # GFW reģistrā LNG kuģiem bieži nav GT un tips ir "OTHER", tāpēc atlase pēc izslēgšanas:
                # pie pašas FSRU piestātnes (≤0,5 km), stāvēja ≥ 8 h, nav vietējais/servisa/kravas kuģis
                gtypes = " ".join((info.get("geartypes") or []) + (info.get("shiptypes") or [])).upper()
                gasname = any(k in name for k in ("LNG", "LPG", "GAS", "HOEGH", "FLEX", "CLIPPER"))
                dkm = anchor_min_km(e, (site["lat"], site["lon"]))
                ais = ais_len.get(str(v.get("ssvid"))) or {}
                length = ais.get("length") or info.get("length") or 0
                if "INDEPENDENCE" in name or not name or dur < 8 or dur > 24 * 20 or dkm > 0.5:
                    continue
                if not gasname:
                    if any(t in gtypes for t in ("FISH", "TRAWL", "PASSENGER", "SEISMIC", "CARGO", "CONTAINER",
                                                 "REEFER", "CARRIER", "TUG", "DREDGE", "PILOT", "BUNKER")):
                        continue
                    if (v.get("flag") or "") == "LTU" or "PILOT" in name or name.startswith("LT-"):
                        continue  # vietējie velkoņi, loči, robežsardze
                    if visits_per_vessel.get(v.get("id"), 0) > 12:
                        continue  # bieži atgriežas = vietējais kuģis
                    if gt and gt < 3000 or (length and length < 90):
                        continue
                if length >= 260 or gt > 80000:
                    cap = 170000
                elif length >= 200 or gt > 40000:
                    cap = 140000
                elif length >= 120 or gt > 8000:
                    cap = 30000
                elif length:
                    cap = 7500
                elif gt:
                    cap = gt * (1.5 if gt > 50000 else 1.25)
                else:
                    cap = 150000  # nezināms izmērs: tipisks LNG tankkuģis
                vol = round(cap * 0.95, -2)
            frm = previous_port(token, v.get("id"), e.get("start") or "", (site["lat"], site["lon"]), cache)
            calls.append({"start": e.get("start"), "end": e.get("end"), "hours": round(dur, 1),
                          "name": v.get("name"), "mmsi": v.get("ssvid"), "flag": v.get("flag"),
                          "imo": info.get("imo"), "gt": gt, "volume": vol, "from": frm})
        calls.sort(key=lambda c: c["start"] or "")
        merged = []
        for c in calls:
            if merged and merged[-1]["name"] == c["name"] and \
                    (datetime.fromisoformat(c["start"][:19]) - datetime.fromisoformat(merged[-1]["end"][:19])).days < 3:
                merged[-1]["end"] = c["end"]
                merged[-1]["hours"] = round(merged[-1]["hours"] + c["hours"], 1)
                continue
            merged.append(c)
        return merged

    bt_calls = build(bt_all, BUTINGE, "crude")
    kl_calls, kl_small = lng_deliveries(token, cache, kl_all + roads, visits_per_vessel, ais_len, start, end, test)
    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period": [start.isoformat(), end.isoformat()],
        "source": "Global Fishing Watch (ostu apmeklējumi, kuģu reģistrs); apjomi ir aplēses",
        "butinge": {**{k: BUTINGE[k] for k in ("name", "lat", "lon")}, "calls": bt_calls,
                    "summary": summarize_calls(bt_calls, "crude"),
                    "discharge_rate_m3h": 4932},
        "klaipeda_lng": {**{k: KLAIPEDA_LNG[k] for k in ("name", "lat", "lon")}, "calls": kl_calls,
                         "summary": summarize_calls(kl_calls, "lng"), "capacity_m3": FSRU_CAPACITY_M3,
                         "small_scale": kl_small,
                         "level_sim": lng_level_sim(kl_calls)},
    }
    (OUT / "latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    today = end.isoformat()
    cache = {k: v for k, v in cache.items() if not (k.startswith("pv365") and not (k.startswith("pv365c:") and k.endswith(today)))}
    CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    for nm, calls in (("Būtiņģe", bt_calls), ("Klaipēdas LNG", kl_calls)):
        print(f"{nm}: {len(calls)} piegādes")
        for c in calls[-25:]:
            print(f"  {c['start'][:10]} {c['hours']:>5}h {c['name'] or '?':<22} {c['flag']} GT {c['gt']} "
                  f"~{c['volume'] or 0:.0f}  no {(c['from'] or {}).get('port')} {(c['from'] or {}).get('country')}")
    print(f"Mazie LNG kuģi Klaipēdā (izved/pārkrauj): {len(kl_small)}")
    if out["klaipeda_lng"]["level_sim"]:
        ls = out["klaipeda_lng"]["level_sim"]
        print(f"LNG simulācija: {ls['now_pct']} %, izsūtīšana ~{ls['rate_m3_day']} m³/d (~{ls['rate_mcm_day']} mlj. m³ gāzes/d)")


if __name__ == "__main__":
    main()
