"""Gāzes plūsmas Baltijas robežpunktos – ENTSOG Transparency Platform (bez atslēgas).

Fiziskās plūsmas pa dienām (kWh/d) robežpunktos ap Latviju un Inčukalnu:
Kiemēnai (LT→LV), Karksi (EE↔LV), Balticconnector (FI↔EE), GIPL/Santaka (PL↔LT),
Klaipēdas LNG, Inkoo LNG, Inčukalna krātuve u.c.
Rezultāts: data/gas_flows/latest.json
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = "https://transparency.entsog.eu/api/v1"
OUT = Path(__file__).parent / "data" / "gas_flows"
UA = "robezas-sargs (github.com/Toms0078/robezas-sargs-dati2)"
PAT = re.compile(r"KIEM|KARKSI|BALTICCONNECTOR|SANTAKA|GIPL|KLAIP|INKOO|INČUKALN|INCUKALN|VÄRSKA|VARSKA|"
                 r"NARVA|KOTLOVKA|IMATRA|PAROLE|LATVIA|LITHUANIA|ESTONIA|PUISTOLA|PAKERORT|PALDISKI|HAMINA", re.I)


def get(path, params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            if attempt < 2:
                time.sleep(10)
                continue
            raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]}")


def main():
    test = "--test" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    pts = get("/connectionpoints", {"limit": -1}).get("connectionpoints", [])
    sel = [p for p in pts if PAT.search(p.get("pointLabel") or "")]
    print(f"Robežpunkti: {len(pts)}, atlasīti: {len(sel)}")
    for p in sel:
        print("  ", p.get("pointKey"), "|", p.get("pointLabel"), "|", p.get("pointType"))
    to = date.today()
    frm = to - timedelta(days=21)
    flows = {}
    for p in sel:
        key = p.get("pointKey")
        res = get("/operationaldata", {"pointKey": key, "indicator": "Physical Flow", "periodType": "day",
                                       "from": frm.isoformat(), "to": to.isoformat(), "timezone": "CET", "limit": -1})
        rows = res.get("operationaldata", [])
        if test and rows:
            print(json.dumps(rows[0])[:900])
        for r in rows:
            if r.get("value") in (None, ""):
                continue
            k = f"{key}|{r.get('directionKey')}|{r.get('operatorKey')}"
            f = flows.setdefault(k, {"point": key, "label": r.get("pointLabel") or p.get("pointLabel"),
                                     "direction": r.get("directionKey"), "operator": r.get("operatorLabel"),
                                     "from_country": r.get("tsoEicCode") and None, "adjacent": r.get("adjacentZones"),
                                     "zone": r.get("operatorKey"), "unit": r.get("unit"), "days": {}})
            day = (r.get("periodFrom") or "")[:10]
            f["days"][day] = r.get("value")
        time.sleep(0.5)
    # pagājušās ziemas (dec–feb) patēriņš galapatērētāju punktos
    winter = {}
    y = to.year if to.month >= 3 else to.year - 1
    w_from, w_to = date(y - 1, 12, 1), date(y, 2, 28)
    for p in sel:
        if not (p.get("pointKey") or "").startswith("FNC"):
            continue
        res = get("/operationaldata", {"pointKey": p["pointKey"], "indicator": "Physical Flow", "periodType": "day",
                                       "from": w_from.isoformat(), "to": w_to.isoformat(), "timezone": "CET", "limit": -1})
        vals = {}
        for r in res.get("operationaldata", []):
            if r.get("directionKey") == "exit" and r.get("value") not in (None, ""):
                d = (r.get("periodFrom") or "")[:10]
                vals[d] = max(vals.get(d, 0), float(r["value"]) / 1e6)
        if vals:
            v = list(vals.values())
            winter[p.get("pointLabel")] = {"from": w_from.isoformat(), "to": w_to.isoformat(),
                                           "avg_gwh": round(sum(v) / len(v), 1), "max_gwh": round(max(v), 1),
                                           "total_gwh": round(sum(v))}
            print("ziema", p.get("pointLabel"), winter[p.get("pointLabel")])
        time.sleep(0.5)
    out = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": "ENTSOG Transparency Platform", "flows": list(flows.values()), "winter": winter}
    for f in out["flows"]:
        last = sorted(f["days"].items())[-3:]
        print(f"{f['label'][:40]:<40} {f['direction']:<6} {f['operator'] or '':<30} "
              + "  ".join(f"{d[5:]}: {round(float(v)/1e6, 1)} GWh" for d, v in last))
    (OUT / "latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
