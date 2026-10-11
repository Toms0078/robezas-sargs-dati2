"""Global Fishing Watch: satelītu radara (SAR) kuģu atklājumi Baltijas interesējošos apgabalos.

SAR redz kuģus arī tad, ja tie neraida AIS ("tumšie" kuģi). GFW salīdzina katru atklājumu ar AIS:
matched = atrasts AIS, unmatched = AIS nav (iespējams izslēgts).
Dati pieejami ar ~5 dienu nobīdi, satelīts pārlido katru vietu ik pāris dienas.

Rezultāts: data/sar/latest.json (pēdējās 14 dienas pieejamajā periodā)
Palaišana:  GFW_TOKEN=... python gfw_sar.py
Avots: Global Fishing Watch (globalfishingwatch.org), lietošanas noteikumi prasa atsauci.
"""
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).parent / "data" / "sar"
BASE = "https://gateway.api.globalfishingwatch.org/v3/4wings/report"
DATASET = "public-global-sar-presence:latest"

REGIONS = {
    "butinge": ("Būtiņģe un Klaipēda", 55.5, 56.4, 20.4, 21.3),
    "gof_east": ("Somu līča austrumi (Primorska, Ustjluga)", 59.4, 60.7, 26.0, 30.3),
    "gulf_riga": ("Rīgas līcis un Irbe", 56.9, 58.5, 21.0, 24.6),
    "kaliningrad": ("Kaļiņingrada", 54.3, 55.4, 19.2, 21.0),
}


def polygon(lat0, lat1, lon0, lon1):
    ring = [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]
    return {"geojson": {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [ring]}}]}}


def report(token, region, start, end, filt=None):
    params = {"datasets[0]": DATASET, "spatial-resolution": "HIGH", "temporal-resolution": "DAILY",
              "group-by": "VESSEL_ID", "date-range": f"{start},{end}", "format": "CSV"}
    if filt:
        params["filters[0]"] = filt
    url = BASE + "?" + urllib.parse.urlencode(params)
    body = json.dumps(polygon(*region)).encode()
    for attempt in range(4):
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json",
            "User-Agent": "robezas-sargs (github.com/Toms0078/robezas-sargs-dati2)"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                raw = r.read()
            break
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:400]
            if e.code == 429 and attempt < 3:      # cits pārskats vēl top
                print(f"  429, gaida 60 s: {msg}")
                time.sleep(60)
                continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")
    zf = zipfile.ZipFile(io.BytesIO(raw))
    name = next(n for n in zf.namelist() if n.endswith(".csv"))
    text = zf.read(name).decode("utf-8", "replace")
    return list(csv.DictReader(io.StringIO(text)))


def main():
    token = os.environ.get("GFW_TOKEN")
    if not token:
        sys.exit("Nav GFW_TOKEN (GitHub: Settings → Secrets and variables → Actions)")
    end = date.today() - timedelta(days=4)
    start = end - timedelta(days=14)
    out = {"updated": date.today().isoformat(), "period": [start.isoformat(), end.isoformat()],
           "source": "Global Fishing Watch, SAR vessel detections", "regions": {}}
    for rid, reg in REGIONS.items():
        name = reg[0]
        try:
            rows = report(token, reg[1:], start.isoformat(), end.isoformat())
        except Exception as e:
            print(f"{name}: kļūda {e}")
            out["regions"][rid] = {"name": name, "error": str(e)}
            continue
        if rows:
            print(f"{name}: {len(rows)} rindas, kolonnas {list(rows[0])}")
            for r in rows[:3]:
                print("   ", r)
        else:
            print(f"{name}: 0 rindas")
        out["regions"][rid] = {"name": name, "bbox": reg[1:], "rows": rows}
        time.sleep(3)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
