"""No kuras ostas kuģis nāk: pēdējais ostas apmeklējums pēc Global Fishing Watch.

Enerģijas kuģiem ceļā uz Baltiju (data/ports/energy_inbound.json) atrod GFW kuģa ID pēc IMO/MMSI
un pēdējo ostas apmeklējumu (port visit) pēdējo 120 dienu laikā. Rezultāts tiek kešots:
  data/ports/origins.json  – {IMO vai MMSI: {port, country, start, end, checked}}
Katru kuģi pārbauda ne biežāk kā reizi 3 dienās.

Palaišana:  GFW_TOKEN=... python gfw_origin.py [--test IMO]
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = "https://gateway.api.globalfishingwatch.org/v3"
DATA = Path(__file__).parent / "data" / "ports"
ORIGINS = DATA / "origins.json"
ENERGY = DATA / "energy_inbound.json"
UA = "robezas-sargs (github.com/Toms0078/robezas-sargs-dati2)"


def call(token, path, params=None, body=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                          "User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 503) and attempt < 2:
                time.sleep(20)
                continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")


def vessel_ids(token, imo=None, mmsi=None):
    q = str(imo or mmsi)
    res = call(token, "/vessels/search", {"query": q, "datasets[0]": "public-global-vessel-identity:latest",
                                          "limit": 5})
    ids = []
    for ent in res.get("entries", []):
        for info in ent.get("selfReportedInfo", []) or []:
            if (imo and str(info.get("imo")) == str(imo)) or (mmsi and str(info.get("ssvid")) == str(mmsi)):
                ids.append(info.get("id"))
        if not ids:  # rezerves variants: visi šī ieraksta ID
            ids += [i.get("id") for i in ent.get("selfReportedInfo", []) or [] if i.get("id")]
    return [i for i in dict.fromkeys(ids) if i], res


def last_port_visit(token, ids, days=120):
    end = date.today()
    start = end - timedelta(days=days)
    res = call(token, "/events", {"limit": 10, "offset": 0, "sort": "-start"},
               {"datasets": ["public-global-port-visits-c2-events:latest"], "vessels": ids,
                "confidences": ["3", "4"], "startDate": start.isoformat(), "endDate": end.isoformat()})
    entries = res.get("entries", [])
    entries.sort(key=lambda e: e.get("start") or "", reverse=True)
    for e in entries:
        pv = e.get("port_visit") or e.get("portVisit") or {}
        anch = pv.get("intermediateAnchorage") or pv.get("startAnchorage") or pv.get("endAnchorage") or {}
        name = anch.get("topDestination") or anch.get("name")
        if name:
            return {"port": name.title(), "country": anch.get("flag"), "start": e.get("start"),
                    "end": e.get("end")}, res
    return None, res


def main():
    token = os.environ.get("GFW_TOKEN")
    if not token:
        sys.exit("Nav GFW_TOKEN")
    if len(sys.argv) > 2 and sys.argv[1] == "--test":
        ids, raw = vessel_ids(token, imo=sys.argv[2])
        print("ID:", ids)
        print("search atbilde (sākums):", json.dumps(raw)[:1500])
        if ids:
            pv, raw2 = last_port_visit(token, ids)
            print("pēdējā osta:", pv)
            print("events atbilde (sākums):", json.dumps(raw2)[:2500])
        return
    origins = json.loads(ORIGINS.read_text()) if ORIGINS.exists() else {}
    ships = json.loads(ENERGY.read_text()).get("ships", []) if ENERGY.exists() else []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    done = 0
    for s in ships:
        key = str(s.get("imo") or s.get("mmsi"))
        if not key or key == "0" or (key in origins and origins[key].get("checked", "") >= cutoff):
            continue
        try:
            ids, _ = vessel_ids(token, imo=s.get("imo") or None, mmsi=None if s.get("imo") else s.get("mmsi"))
            pv = last_port_visit(token, ids)[0] if ids else None
        except Exception as e:
            print(f"{s.get('name')}: {e}")
            continue
        origins[key] = {**(pv or {}), "name": s.get("name"),
                        "checked": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        print(f"{s.get('name'):<24} → {s.get('port'):<16} pēdējā osta: {(pv or {}).get('port')} "
              f"({(pv or {}).get('country')}) {((pv or {}).get('end') or '')[:10]}")
        done += 1
        time.sleep(1)
        if done >= 60:
            break
    DATA.mkdir(parents=True, exist_ok=True)
    ORIGINS.write_text(json.dumps(origins, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
