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
KLAIPEDA_LNG = {"id": "klaipeda_lng", "name": "Klaipēdas LNG (FSRU Independence)", "lat": 55.64, "lon": 21.13,
                "r_km": 1.5, "search_box": (55.55, 55.76, 21.05, 21.20)}
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
    """Krātuves aizpildījuma simulācija: piegādes (m³) mīnus vienmērīga izsūtīšana.
    Izsūtīšanas ātrums = kopējās piegādes / periods; sākuma līmenis izvēlēts tā, lai minimums būtu 10 %."""
    if not deliveries:
        return None
    end = datetime.now(timezone.utc)
    start = min(datetime.fromisoformat(d["start"][:19]).replace(tzinfo=timezone.utc) for d in deliveries)
    span_days = max((end - start).total_seconds() / 86400, 30)
    total = sum(d["volume"] or 0 for d in deliveries)
    rate = total / span_days  # m³ dienā
    pts, level, t = [], 0.0, start
    ev = sorted((datetime.fromisoformat(d["start"][:19]).replace(tzinfo=timezone.utc), d["volume"] or 0)
                for d in deliveries)
    i = 0
    while t <= end:
        while i < len(ev) and ev[i][0] <= t:
            level += ev[i][1]
            i += 1
        pts.append([t.strftime("%Y-%m-%d"), level])
        level -= rate
        t += timedelta(days=1)
    lo = min(p[1] for p in pts)
    shift = 0.10 * FSRU_CAPACITY_M3 - lo
    series = [[d, max(0.0, min(100.0, (v + shift) / FSRU_CAPACITY_M3 * 100))] for d, v in pts]
    return {"rate_m3_day": round(rate), "rate_mcm_day": round(rate * 585 / 1e6, 2),
            "series": [[d, round(v, 1)] for d, v in series], "now_pct": round(series[-1][1], 1),
            "assumptions": "sākuma līmenis tā, lai minimums = 10 %; izsūtīšana vienmērīga (vidējā no piegādēm)"}


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

    # --- Būtiņģe
    b = BUTINGE
    d = 0.06
    bt_all = port_visits_in(token, box(b["lat"] - d, b["lat"] + d, b["lon"] - 2 * d, b["lon"] + 2 * d),
                            start.isoformat(), end.isoformat())
    print(f"Būtiņģes apgabala apmeklējumi: {len(bt_all)}")
    if test and bt_all:
        print(json.dumps(bt_all[0])[:1500])

    ids = list({(e.get("vessel") or {}).get("id") for e in bt_all + kl_all if (e.get("vessel") or {}).get("id")})
    vessel_info(token, ids, cache)

    def build(events, site, kind):
        calls = []
        for e in events:
            v = e.get("vessel") or {}
            pos = e.get("position") or {}
            if not pos or km((pos.get("lat"), pos.get("lon")), (site["lat"], site["lon"])) > site["r_km"]:
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
                if "INDEPENDENCE" in name or gt < 5000 or dur < 6:
                    continue
                cap = gt * (1.5 if gt > 50000 else 1.25)
                vol = round(cap * 0.95, -2)
            frm = previous_port(token, v.get("id"), e.get("start") or "", (site["lat"], site["lon"]), cache)
            calls.append({"start": e.get("start"), "end": e.get("end"), "hours": round(dur, 1),
                          "name": v.get("name"), "mmsi": v.get("ssvid"), "flag": v.get("flag"),
                          "imo": info.get("imo"), "gt": gt, "volume": vol, "from": frm})
        calls.sort(key=lambda c: c["start"] or "")
        return calls

    bt_calls = build(bt_all, BUTINGE, "crude")
    kl_calls = build(kl_all, KLAIPEDA_LNG, "lng")
    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period": [start.isoformat(), end.isoformat()],
        "source": "Global Fishing Watch (ostu apmeklējumi, kuģu reģistrs); apjomi ir aplēses",
        "butinge": {**{k: BUTINGE[k] for k in ("name", "lat", "lon")}, "calls": bt_calls,
                    "summary": summarize_calls(bt_calls, "crude"),
                    "discharge_rate_m3h": 4932},
        "klaipeda_lng": {**{k: KLAIPEDA_LNG[k] for k in ("name", "lat", "lon")}, "calls": kl_calls,
                         "summary": summarize_calls(kl_calls, "lng"), "capacity_m3": FSRU_CAPACITY_M3,
                         "level_sim": lng_level_sim(kl_calls)},
    }
    (OUT / "latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    for nm, calls in (("Būtiņģe", bt_calls), ("Klaipēdas LNG", kl_calls)):
        print(f"{nm}: {len(calls)} piegādes")
        for c in calls[-12:]:
            print(f"  {c['start'][:10]} {c['hours']:>5}h {c['name']:<22} {c['flag']} GT {c['gt']} "
                  f"~{c['volume']:.0f}  no {(c['from'] or {}).get('port')} {(c['from'] or {}).get('country')}")
    if out["klaipeda_lng"]["level_sim"]:
        ls = out["klaipeda_lng"]["level_sim"]
        print(f"LNG simulācija: {ls['now_pct']} %, izsūtīšana ~{ls['rate_m3_day']} m³/d (~{ls['rate_mcm_day']} mlj. m³ gāzes/d)")


if __name__ == "__main__":
    main()
