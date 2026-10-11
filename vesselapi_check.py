"""VesselAPI tests: vai maksas/bezmaksas API redz to, ko aisstream un Digitraffic neredz.

Reizi dienā 4 pieprasījumi (bezmaksas plāns: 150 mēnesī):
  1. Rīgas ostas notikumi (ierašanās/aiziešanas) pēdējās 24 h
  2. Ventspils ostas notikumi pēdējās 24 h
  3. Kuģi ceļā uz Būtiņģi (nākamās 72 h)
  4. Kuģi taisnstūrī ap Būtiņģes boju (pēdējās 4 h)

Rezultāts: data/vesselapi/latest.json un dienas kopija.
Palaišana:  VESSELAPI_KEY=... python vesselapi_check.py
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://api.vesselapi.com"
OUT = Path(__file__).parent / "data" / "vesselapi"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def call(key, path, params):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}",
                                               "User-Agent": "robezas-sargs/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return {"ok": True, "status": r.status,
                    "remaining": r.headers.get("X-RateLimitRemaining"),
                    "data": json.loads(r.read() or b"{}")}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        return {"ok": False, "status": e.code, "remaining": e.headers.get("X-RateLimitRemaining"),
                "error": body}
    except Exception as e:
        return {"ok": False, "status": None, "error": f"{type(e).__name__}: {e}"}


def main():
    key = os.environ.get("VESSELAPI_KEY")
    if not key:
        sys.exit("Nav VESSELAPI_KEY (GitHub: Settings → Secrets and variables → Actions)")
    now = datetime.now(timezone.utc)
    day_ago = iso(now - timedelta(hours=24))
    checks = {
        "riga_events": ("/v1/portevents/port/LVRIX",
                        {"time.from": day_ago, "time.to": iso(now), "pagination.limit": 50}),
        "ventspils_events": ("/v1/portevents/port/LVVNT",
                             {"time.from": day_ago, "time.to": iso(now), "pagination.limit": 50}),
        "butinge_inbound": ("/v1/port/LTBOT/inbound",
                            {"filter.etaFrom": iso(now), "filter.etaTo": iso(now + timedelta(hours=72)),
                             "pagination.limit": 50}),
        "butinge_area": ("/v1/location/vessels/bounding-box",
                         {"filter.lonLeft": 20.70, "filter.lonRight": 21.25,
                          "filter.latBottom": 55.90, "filter.latTop": 56.25,
                          "time.from": iso(now - timedelta(hours=4)), "time.to": iso(now),
                          "pagination.limit": 50}),
    }
    result = {"updated": iso(now), "source": "VesselAPI (vesselapi.com)", "checks": {}}
    for name, (path, params) in checks.items():
        r = call(key, path, params)
        result["checks"][name] = r
        n = None
        if r["ok"]:
            d = r["data"]
            n = len(d.get("portEvents") or d.get("vesselETAs") or d.get("vessels") or [])
        print(f"{name:<18} status {r['status']}  ieraksti {n}  atlikums {r.get('remaining')}"
              + ("" if r["ok"] else f"  kļūda: {r.get('error', '')[:200]}"))
    OUT.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, ensure_ascii=False, indent=1)
    (OUT / "latest.json").write_text(text)
    (OUT / f"{now:%Y-%m-%d}.json").write_text(text)


if __name__ == "__main__":
    main()
