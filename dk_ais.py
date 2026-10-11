"""Dānijas Jūras administrācijas AIS arhīvs (aisdata.ais.dk) -> "Baltijas vārtu" žurnāls.

Reizi dienā lejupielādē iepriekšējās dienas failu (CSV zip), atlasa tankkuģus un gāzes kuģus,
kas šķērsoja Dānijas šaurumus (Ēresunds, Lielais Belts / Fehmarnas šaurums), un saglabā:
  data/gates/YYYY-MM-DD.json  – dienas šķērsojumi
  data/gates/log.jsonl        – visi šķērsojumi (viens ieraksts rindā)
  data/gates/summary.json     – pēdējo 30 dienu kopsavilkums pa galamērķiem
  data/gates/recent.json      – pēdējo 7 dienu ienākušie (simulācijas sākumpunktiem)

Palaišana:  python dk_ais.py [YYYY-MM-DD]
"""
import csv
import io
import json
import re
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import butinge_ais as B

OUT = Path(__file__).parent / "data" / "gates"
TMP = Path("/tmp/dk_ais")
CANDIDATES = [
    "http://aisdata.ais.dk/aisdk-{d}.zip",
    "https://aisdata.ais.dk/aisdk-{d}.zip",
    "http://aisdata.ais.dk/{y}/aisdk-{d}.zip",
    "https://aisdata.ais.dk/{y}/aisdk-{d}.zip",
    "http://web.ais.dk/aisdata/aisdk-{d}.zip",
    "https://web.ais.dk/aisdata/aisdk-{d}.zip",
]
UA = {"User-Agent": "robezas-sargs (github.com/Toms0078/robezas-sargs-dati2)"}


def west(lat, lon):   # Kategats, Ziemeļjūra, Ķīles līcis
    return (lat >= 56.0 and lon <= 12.7) or lon <= 10.9


def east(lat, lon):   # Baltijas jūra aiz šaurumiem
    return (lon >= 12.95 and lat <= 55.85) or (lon >= 11.7 and lat <= 54.75)


def find_url(day):
    for pat in CANDIDATES:
        url = pat.format(d=day.isoformat(), y=day.year)
        try:
            req = urllib.request.Request(url, headers=UA, method="HEAD")
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status == 200:
                    print(f"Atrasts: {url} ({r.headers.get('Content-Length')} baiti)")
                    return url
        except Exception as e:
            print(f"  nav: {url} ({type(e).__name__}: {getattr(e, 'code', '')})")
    return None


def show_index():
    """Ja fails nav atrasts, izdrukā arhīva lapas sākumu, lai varētu noskaidrot formātu."""
    for u in ("http://aisdata.ais.dk/", "https://aisdata.ais.dk/"):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
                txt = r.read(20000).decode("utf-8", "replace")
            print(f"--- {u} ---")
            print("\n".join(re.findall(r'(?:href|src)="([^"]+)"', txt))[:3000])
            print(re.sub(r"\s+", " ", txt)[:2000])
            return
        except Exception as e:
            print(f"{u}: {e}")


def parse_time(s):
    for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def process_day(url, day):
    TMP.mkdir(parents=True, exist_ok=True)
    zpath = TMP / f"{day}.zip"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r, open(zpath, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    print(f"Lejupielādēts {zpath.stat().st_size / 1e6:.0f} MB")
    ships = {}
    rows = kept = 0
    with zipfile.ZipFile(zpath) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(name) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
            header = next(csv.reader([text.readline()]))
            col = {h.strip().lstrip("#").strip(): i for i, h in enumerate(header)}
            print("Kolonnas:", list(col))
            need = lambda k: col.get(k)
            i_t, i_mmsi = need("Timestamp"), need("MMSI")
            i_lat, i_lon, i_sog, i_cog = need("Latitude"), need("Longitude"), need("SOG"), need("COG")
            i_imo, i_name, i_type = need("IMO"), need("Name"), need("Ship type")
            i_dr, i_dest, i_eta, i_len = need("Draught"), need("Destination"), need("ETA"), need("Length")
            for line in text:
                rows += 1
                if "Tanker" not in line and "LNG" not in line and "LPG" not in line and "GAS" not in line:
                    continue
                r = next(csv.reader([line]))
                if len(r) < len(col):
                    continue
                stype, nm = r[i_type], r[i_name].strip().upper()
                if stype != "Tanker" and not B.is_gas_ship(nm, None):
                    continue
                lat, lon = fnum(r[i_lat]), fnum(r[i_lon])
                if lat is None or lon is None or not (50 < lat < 62 and 4 < lon < 20):
                    continue
                t = parse_time(r[i_t])
                if not t:
                    continue
                kept += 1
                m = r[i_mmsi]
                sh = ships.setdefault(m, {"mmsi": int(m) if m.isdigit() else m, "first": None, "last": None,
                                          "first_side": None, "last_side": None, "east_time": None,
                                          "west_time": None})
                side = "W" if west(lat, lon) else ("E" if east(lat, lon) else None)
                pt = {"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "lat": lat, "lon": lon,
                      "sog": fnum(r[i_sog]), "cog": fnum(r[i_cog])}
                if sh["first"] is None or pt["t"] < sh["first"]["t"]:
                    sh["first"] = pt
                if sh["last"] is None or pt["t"] > sh["last"]["t"]:
                    sh["last"] = pt
                if side:
                    if sh["first_side"] is None or pt["t"] < sh["first_side"][0]:
                        sh["first_side"] = (pt["t"], side)
                    if sh["last_side"] is None or pt["t"] > sh["last_side"][0]:
                        sh["last_side"] = (pt["t"], side)
                    if side == "E" and (sh["east_time"] is None or pt["t"] < sh["east_time"]):
                        sh["east_time"] = pt["t"]
                    if side == "W" and (sh["west_time"] is None or pt["t"] < sh["west_time"]):
                        sh["west_time"] = pt["t"]
                for k, idx in (("name", i_name), ("imo", i_imo), ("dest", i_dest), ("eta", i_eta)):
                    v = r[idx].strip() if idx is not None else ""
                    if v and v.lower() not in ("unknown", "undefined"):
                        sh[k] = v
                for k, idx in (("draught", i_dr), ("length", i_len)):
                    v = fnum(r[idx]) if idx is not None else None
                    if v:
                        sh[k] = max(v, sh.get(k) or 0)
                sh["gas"] = sh.get("gas") or B.is_gas_ship(nm, None) or stype != "Tanker"
    zpath.unlink(missing_ok=True)
    print(f"Rindas {rows}, tankkuģu/gāzes rindas {kept}, kuģi {len(ships)}")
    sanctions = B.load_sanctions()
    out = []
    for m, sh in ships.items():
        fs, ls = sh["first_side"], sh["last_side"]
        if not fs or not ls or fs[1] == ls[1]:
            continue
        direction = "ienāca" if fs[1] == "W" else "izgāja"
        when = sh["east_time"] if direction == "ienāca" else sh["west_time"]
        dest = sh.get("dest", "")
        port = B.baltic_port_of(dest)
        rec = {
            "date": str(day), "time": when, "direction": direction, "mmsi": sh["mmsi"],
            "name": sh.get("name"), "imo": int(sh["imo"]) if str(sh.get("imo", "")).isdigit() else None,
            "flag": B.flag_of(sh["mmsi"]), "length": sh.get("length"), "draught": sh.get("draught"),
            "destination": dest, "dest_port": port["name"] if port else None,
            "dest_country": port["country"] if port else None, "gas": bool(sh.get("gas")),
            "eta_raw": sh.get("eta"), "last": sh["last"],
        }
        if rec["gas"]:
            rec["cargo_guess"] = "LNG" if (rec["length"] or 0) >= 200 or "LNG" in (rec["name"] or "") else "LPG / gāze"
            t, L = rec.get("draught"), rec.get("length") or 0
            if t and L >= 200:
                rec["cargo_state"] = "pilns (ved gāzi)" if t >= 10.8 else ("tukšs / balastā" if t <= 9.6 else "daļēji")
            elif t and L:
                rec["cargo_state"] = "pilns (ved gāzi)" if t >= 0.051 * L else ("tukšs / balastā" if t <= 0.039 * L else "daļēji")
        else:
            B.cargo_guess(B.load_estimate(rec, {}), port["id"] if port else None)
        tags = set((sanctions.get(str(rec["imo"] or "")) or {}).get("r", "").split(";")) - {""}
        rec["sanctioned"], rec["shadow_listed"] = "sanction" in tags, "mare.shadow" in tags
        rec["ru_linked"] = str(rec["mmsi"])[:3] == "273" or bool(B.ru_port_of(dest))
        out.append(rec)
    out.sort(key=lambda x: x["time"] or "")
    return out


def summarize():
    recs = []
    if (OUT / "log.jsonl").exists():
        recs = [json.loads(l) for l in (OUT / "log.jsonl").read_text().splitlines() if l.strip()]
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    recs = [r for r in recs if r["date"] >= cutoff]
    by = {}
    for r in recs:
        key = r.get("dest_port") or ("for orders / nav zināms" if r["direction"] == "ienāca" else "ārpus Baltijas")
        g = by.setdefault(r["direction"], {}).setdefault(key, {"total": 0, "laden": 0, "gas": 0, "crude": 0,
                                                               "products": 0, "sanctioned_or_shadow": 0})
        g["total"] += 1
        g["laden"] += 1 if (r.get("load_pct") or 0) >= 55 or (r.get("cargo_state") or "").startswith("pilns") else 0
        g["gas"] += 1 if r.get("gas") else 0
        cg = (r.get("cargo_guess") or "")
        g["crude"] += 1 if "jēlnafta" in cg else 0
        g["products"] += 1 if "produkt" in cg else 0
        g["sanctioned_or_shadow"] += 1 if r.get("sanctioned") or r.get("shadow_listed") else 0
    days = sorted({r["date"] for r in recs})
    (OUT / "summary.json").write_text(json.dumps({"days": days, "by_direction": by, "count": len(recs)},
                                                ensure_ascii=False, indent=1))
    cutoff4 = (date.today() - timedelta(days=7)).isoformat()
    recent = [r for r in recs if r["date"] >= cutoff4 and r["direction"] == "ienāca"]
    (OUT / "recent.json").write_text(json.dumps(recent, ensure_ascii=False, indent=1))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    done_file = OUT / "processed.json"
    done = set(json.loads(done_file.read_text())) if done_file.exists() else set()
    if len(sys.argv) > 1:
        days = [date.fromisoformat(sys.argv[1])]
    else:
        today = datetime.now(timezone.utc).date()
        days = [today - timedelta(days=k) for k in (6, 5, 4, 3, 2, 1)]   # arhīvs kavējas ~3 dienas
    any_found = False
    for day in days:
        if str(day) in done:
            continue
        url = find_url(day)
        if not url:
            continue
        any_found = True
        recs = process_day(url, day)
        (OUT / f"{day}.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1))
        with (OUT / "log.jsonl").open("a") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        done.add(str(day))
        done_file.write_text(json.dumps(sorted(done)))
        inn = sum(1 for r in recs if r["direction"] == "ienāca")
        print(f"{day}: {len(recs)} šķērsojumi ({inn} ienāca, {len(recs) - inn} izgāja)")
        for r in recs[:40]:
            print(f"  {r['time'][11:16]} {r['direction']:<7} {r['name'] or r['mmsi']:<22} → "
                  f"{r.get('dest_port') or r['destination'] or '?':<18} {r.get('cargo_guess') or ''} "
                  f"{r.get('cargo_state') or ''} {'SANKC' if r['sanctioned'] else ''}{'ĒNU' if r['shadow_listed'] else ''}")
    if not any_found and not any(str(d) in done for d in days):
        show_index()
    summarize()


if __name__ == "__main__":
    main()
