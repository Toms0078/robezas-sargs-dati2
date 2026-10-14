"""Naftas bilance reģionā – Eurostat nrg_cb_oilm (mēneša dati, tūkst. t, bez atslēgas).

Rezultāts: data/oil_balance/official.json
Palaišana: python oil_balance.py [--test]
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
OUT = Path(__file__).parent / "data" / "oil_balance"
UA = "robezas-sargs (github.com/Toms0078/robezas-sargs-dati2)"
GEOS = ["LV", "LT", "EE", "FI", "PL", "SE", "DK"]
SIEC = {"O4100_TOT": "jēlnafta", "O4600": "naftas produkti kopā", "O4671": "dīzelis un gāzeļļa", "O46711": "autodīzelis",
        "O4652": "benzīns", "O4661": "aviodegviela", "O4630": "LPG", "O4680": "mazuts"}
BAL = {"IPRD": "ražošana (ieguve)", "IMP": "imports", "EXP": "eksports", "STK_CHG": "krājumu izmaiņa",
       "INTMARB": "kuģu bunkurēšana", "INTAVI_E": "starptautiskā aviācija", "GID_OBS": "iekšzemes piegādes",
       "GID_CAL": "iekšzemes piegādes (aprēķins)", "TO_RPI_RO": "naftas pārstrādes rūpnīcu izlaide",
       "RI_OBS": "pārstrādei saņemts", "FC_TRA_ROAD_E": "autotransports"}


def get(code, params):
    q = urllib.parse.urlencode([("format", "JSON"), ("lang", "EN")] + params)
    url = API + code + "?" + q
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read()[:400]
            if attempt < 2 and e.code in (429, 500, 502, 503):
                time.sleep(15)
                continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")


def unpack(js):
    """JSON-stat 2.0 → saraksts ar (dims dict, vērtība)."""
    ids, sizes = js["id"], js["size"]
    cats = []
    for d in ids:
        idx = js["dimension"][d]["category"]["index"]
        inv = sorted(idx, key=lambda k: idx[k]) if isinstance(idx, dict) else idx
        cats.append(inv)
    out = []
    status = js.get("status") or {}
    vals = js.get("value", {})
    if isinstance(vals, list):
        vals = {str(i): v for i, v in enumerate(vals) if v is not None}
    for k, v in vals.items():
        st = status.get(k) if isinstance(status, dict) else None
        if st and "c" in str(st).lower():   # "|C" = konfidenciāls – nav īstā vērtība
            v = None
        k = int(k)
        coord = {}
        for i in range(len(ids) - 1, -1, -1):
            coord[ids[i]] = cats[i][k % sizes[i]]
            k //= sizes[i]
        out.append((coord, v))
    return out


def labels(js, dim):
    return js["dimension"][dim]["category"].get("label", {})


def main():
    test = "--test" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    since = f"{date.today().year - 3}-{date.today().month:02d}"
    out = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": "Eurostat nrg_cb_oilm (tūkst. t)",
           "source_url": "https://ec.europa.eu/eurostat/databrowser/view/nrg_cb_oilm/default/table",
           "labels": {"siec": SIEC, "nrg_bal": BAL}, "countries": {}}
    for geo in GEOS:
        try:
            js = get("nrg_cb_oilm", [("geo", geo), ("unit", "THS_T"), ("sinceTimePeriod", since)])
        except Exception as e:
            print(geo, e)
            continue
        if test:
            from collections import Counter
            print(geo, "statusi:", Counter((js.get("status") or {}).values()), "statusu nozīmes:",
                  (js.get("extension") or {}).get("status", {}).get("label"))
        if test and geo == "FI":
            stt = js.get("status") or {}
            ids, sizes = js["id"], js["size"]
            cats = [sorted(js["dimension"][d]["category"]["index"], key=lambda k: js["dimension"][d]["category"]["index"][k]) for d in ids]
            seen = set()
            for k in list(stt)[:400]:
                n = int(k); coord = {}
                for i in range(len(ids) - 1, -1, -1):
                    coord[ids[i]] = cats[i][n % sizes[i]]; n //= sizes[i]
                seen.add((coord["siec"], coord["nrg_bal"]))
            print("FI konfidenciāli (siec, nrg_bal):", sorted(seen)[:60])
            print("FI vērtība pie statusa piemērs:", [(k, (js.get("value") or {}).get(k)) for k in list(stt)[:5]])
        if test and geo == "LV":
            print("dimensijas:", js["id"], js["size"])
            for dim in ("nrg_bal", "siec"):
                for c, l in labels(js, dim).items():
                    print(f"  {dim} {c}: {l}")
        cube = {}
        months = set()
        for c, v in unpack(js):
            m = c["time"]
            months.add(m)
            if c["siec"] in SIEC and c["nrg_bal"] in BAL:
                cube.setdefault(c["siec"], {}).setdefault(c["nrg_bal"], {})[m] = round(v, 1) if v is not None else None
        ms = sorted(months)
        out["countries"][geo] = {"months": ms, "data": {s: {b: [vals.get(m) for m in ms] for b, vals in bs.items()}
                                                        for s, bs in cube.items()}}
        print(f"{geo}: {len(ms)} mēn. ({ms[0] if ms else '-'} – {ms[-1] if ms else '-'}), produkti {len(cube)}, "
              f"pozīcijas {len({b for bs in cube.values() for b in bs})}")
        if test and geo == "LV" and ms:
            for s in list(cube)[:6]:
                for b in list(cube[s])[:12]:
                    print("   ", s, b, [cube[s][b].get(m) for m in ms[-3:]])
        time.sleep(1)
    prev = OUT / "official.json"
    old_n = len(json.loads(prev.read_text()).get("countries", {})) if prev.exists() else 0
    if not out["countries"] or len(out["countries"]) < old_n:
        print(f"Kļūda: saņemtas tikai {len(out['countries'])} valstis (bija {old_n}) – vecos datus nepārrakstu")
        sys.exit(1)
    prev.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print("izmērs KB:", round((OUT / "official.json").stat().st_size / 1024))


if __name__ == "__main__":
    main()
