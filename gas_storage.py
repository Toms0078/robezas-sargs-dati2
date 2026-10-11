"""Pazemes gāzes krātuves (Inčukalns u.c.) – aizpildījums no GIE AGSI+ (agsi.gie.eu).

AGSI+ katru dienu publicē katras ES krātuves gāzes daudzumu (TWh), aizpildījumu (%),
iesūknēšanu un izņemšanu (GWh/d). Dati par iepriekšējo gāzes dienu parādās ~18:00–19:30 CET.

Ja ir GitHub noslēpums AGSI_KEY, to sūta galvenē "x-key"; bez tā mēģina bez atslēgas.
Rezultāts: data/gas_storage/latest.json
Palaišana:  python gas_storage.py [--test]
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://agsi.gie.eu/api"
OUT = Path(__file__).parent / "data" / "gas_storage"
UA = "robezas-sargs (github.com/Toms0078/robezas-sargs-dati2)"
COUNTRIES = ["LV", "PL", "DK", "SE", "DE"]

# Aptuvenās krātuvju vietas kartei (atslēgvārds nosaukumā → koordinātas)
COORDS = [
    ("INCUKALNS", 57.105, 24.700), ("INČUKALNS", 57.105, 24.700),
    ("KOSAKOWO", 54.590, 18.470), ("MOGILNO", 52.660, 17.950), ("WIERZCHOWICE", 51.380, 17.410),
    ("HUSOW", 50.030, 22.350), ("HUSÓW", 50.030, 22.350), ("STRACHOCINA", 49.620, 22.080),
    ("SWARZOW", 50.170, 21.030), ("SWARZÓW", 50.170, 21.030), ("BRZEZNICA", 49.970, 21.470),
    ("BRZEŹNICA", 49.970, 21.470), ("BONIKOWO", 52.060, 16.630), ("DASZEWO", 53.980, 15.920),
    ("STENLILLE", 55.530, 11.600), ("LILLE TORUP", 56.730, 9.350), ("TORUP", 56.730, 9.350),
    ("SKALLEN", 56.660, 12.870),
    ("REHDEN", 52.600, 8.480), ("ETZEL", 53.450, 7.850), ("JEMGUM", 53.270, 7.400), ("KIEL", 54.270, 10.150),
    ("KRAAK", 53.430, 11.330), ("HARSEFELD", 53.450, 9.500), ("NUTTERMOOR", 53.270, 7.420),
    ("HUNTORF", 53.190, 8.420), ("BERNBURG", 51.800, 11.740), ("STASSFURT", 51.850, 11.580),
    ("KATHARINA", 51.800, 11.900), ("PEISSEN", 51.640, 11.920), ("BIERWANG", 48.030, 12.200),
    ("INZENHAM", 47.860, 12.140), ("HAIDACH", 47.990, 13.180), ("EPE", 51.980, 7.060),
    ("DOTERNHAUSEN", 48.250, 8.800), ("BREITBRUNN", 47.880, 12.380), ("RÜDERSDORF", 52.480, 13.780),
    ("RUDERSDORF", 52.480, 13.780), ("KALLE", 52.570, 8.050), ("XANTEN", 51.660, 6.450),
    ("BAD LAUCHSTÄDT", 51.390, 11.870), ("BAD LAUCHSTADT", 51.390, 11.870), ("STAßFURT", 51.850, 11.580),
    ("ALLMENHAUSEN", 51.250, 10.720), ("HÄHNLEIN", 49.760, 8.520), ("HAHNLEIN", 49.760, 8.520),
    ("REITBROOK", 53.480, 10.150), ("UELSEN", 52.500, 6.880), ("FRANKENTHAL", 49.540, 8.350),
    ("WOLFERSBERG", 48.050, 11.940), ("SCHMIDHAUSEN", 48.200, 11.700), ("EMPELDE", 52.330, 9.640),
    ("ENGE", 52.700, 10.900), ("LESUM", 53.170, 8.700), ("HARBERGEN", 52.900, 9.100),
    ("JEMGUM", 53.270, 7.400), ("ZDP", 53.270, 7.400),
]


# Krātuves tips (vispārzināms) – atslēgvārds nosaukumā
TYPES = [("GSD", "sāls kavernas (Lille Torup) un akvifērs (Stenlille)"), ("INCUKALN", "porains ūdens nesējslānis (akvifērs)"), ("STENLILLE", "akvifērs"),
         ("LILLE TORUP", "sāls kavernas"), ("SKALLEN", "oderēta klinšu kaverna"), ("KAWERNA", "sāls kavernas"),
         ("KOSAKOWO", "sāls kavernas"), ("MOGILNO", "sāls kavernas"), ("WIERZCHOWICE", "izsmelta gāzes atradne"),
         ("SANOK", "izsmeltas gāzes atradnes"), ("ETZEL", "sāls kavernas"), ("KIEL", "sāls kavernas"),
         ("KRAAK", "sāls kavernas"), ("JEMGUM", "sāls kavernas"), ("NÜTTERMOOR", "sāls kavernas"),
         ("HARSEFELD", "sāls kavernas"), ("EMPELDE", "sāls kavernas"), ("RÜDERSDORF", "sāls kavernas"),
         ("LESUM", "sāls kavernas"), ("REHDEN", "izsmelta gāzes atradne"), ("UELSEN", "izsmelta gāzes atradne"),
         ("EPE", "sāls kavernas"), ("STASSFURT", "sāls kavernas"), ("BERNBURG", "sāls kavernas"),
         ("PECKENSEN", "sāls kavernas"), ("VSP NORD", "izsmelta atradne + sāls kavernas")]
NORTH_DE_LAT = 52.3   # Vācijā kartē rāda tikai ziemeļu krātuves (Baltijas reģions)


def ftype(name):
    n = (name or "").upper()
    return next((t for k, t in TYPES if k in n), None)


def call(params, base=BASE):
    url = base + ("?" + urllib.parse.urlencode(params) if params else "")
    headers = {"User-Agent": UA, "Accept": "application/json"}
    key = os.environ.get("ALSI_KEY") if "alsi" in base else None
    key = key or os.environ.get("AGSI_KEY")
    if key:
        headers["x-key"] = key
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 503) and attempt < 2:
                time.sleep(10)
                continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def row(d):
    return {"day": d.get("gasDayStart"), "gas_twh": fnum(d.get("gasInStorage")), "full_pct": fnum(d.get("full")),
            "capacity_twh": fnum(d.get("workingGasVolume")), "injection_gwh": fnum(d.get("injection")),
            "withdrawal_gwh": fnum(d.get("withdrawal")), "trend": fnum(d.get("trend")),
            "inj_cap_gwh": fnum(d.get("injectionCapacity")), "wd_cap_gwh": fnum(d.get("withdrawalCapacity")),
            "cons_full_pct": fnum(d.get("consumptionFull")), "status": d.get("status")}


def coords_for(name):
    n = (name or "").upper()
    for k, la, lo in COORDS:
        if k in n:
            return la, lo
    return None


def lrow(d):
    inv = d.get("inventory") or {}
    dt = d.get("dtmi") or {}
    return {"day": d.get("gasDayStart"),
            "lng_m3": fnum(inv.get("lng")) if isinstance(inv, dict) else fnum(d.get("lngInventory")),
            "inv_gwh": fnum(inv.get("gwh")) if isinstance(inv, dict) else None,
            "sendout_gwh": fnum(d.get("sendOut")),
            "dtmi_m3": fnum(dt.get("lng")) if isinstance(dt, dict) else fnum(dt),
            "dtmi_gwh": fnum(dt.get("gwh")) if isinstance(dt, dict) else None,
            "dtrs_gwh": fnum(d.get("dtrs")), "status": d.get("status")}


def listing():
    url = BASE + "/about?show=listing"
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if os.environ.get("AGSI_KEY"):
        headers["x-key"] = os.environ["AGSI_KEY"]
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        return json.loads(r.read())


def main():
    test = "--test" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    out = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": "GIE AGSI+ (agsi.gie.eu)", "countries": {}, "facilities": []}
    # valstu kopsummas (pēdējās 60 dienas – grafikam)
    for cc in COUNTRIES:
        try:
            res = call({"country": cc, "size": 60})
        except Exception as e:
            print(cc, e)
            continue
        data = res.get("data") or []
        if test and cc == "LV":
            print(json.dumps(res)[:1200])
        if data:
            out["countries"][cc] = {"name": data[0].get("name") or cc, "latest": row(data[0]),
                                    "series": [[d.get("gasDayStart"), fnum(d.get("full"))] for d in reversed(data)]}
            r = out["countries"][cc]["latest"]
            print(f"{cc}: {r['day']} {r['full_pct']}% · {r['gas_twh']} TWh no {r['capacity_twh']} TWh "
                  f"(iesūkn. {r['injection_gwh']}, izņem. {r['withdrawal_gwh']} GWh/d)")
        time.sleep(1)
    # atsevišķās krātuves
    try:
        lst = listing()
    except Exception as e:
        print("listing:", e)
        lst = None
    if test and lst:
        print("listing:", json.dumps(lst)[:1500])
    for cc in COUNTRIES:
        comps = []
        if isinstance(lst, list):
            comps = [c for c in lst if c.get("country") == cc and c.get("type") == "SSO"]
        elif isinstance(lst, dict):
            comps = ((lst.get("SSO") or {}).get("Europe") or {}).get(cc) or lst.get(cc) or []
        for comp in comps:
            for fac in comp.get("facilities") or []:
                if "historical" in (fac.get("name") or "").lower():
                    continue
                if not os.environ.get("AGSI_KEY"):
                    pos = coords_for(fac.get("name"))
                    out["facilities"].append({"country": cc, "name": fac.get("name"), "company": comp.get("name"),
                                              "lat": pos[0] if pos else None, "lon": pos[1] if pos else None,
                                              "full_pct": None})
                    continue
                nm0 = fac.get("name") or ""
                pos0 = coords_for(nm0)
                if cc == "DE" and (not pos0 or pos0[0] < NORTH_DE_LAT or "decommissioned" in nm0.lower()):
                    continue
                try:
                    res = call({"country": cc, "company": comp.get("eic"), "facility": fac.get("eic"), "size": 35})
                except Exception as e:
                    print(fac.get("name"), e)
                    continue
                data = res.get("data") or []
                if not data:
                    continue
                name = fac.get("name") or data[0].get("name")
                pos = coords_for(name)
                ly = None
                try:
                    d0 = datetime.fromisoformat(data[0]["gasDayStart"]).date()
                    r_ly = call({"country": cc, "company": comp.get("eic"), "facility": fac.get("eic"),
                                 "from": (d0.replace(year=d0.year - 1)).isoformat(),
                                 "to": (d0.replace(year=d0.year - 1)).isoformat(), "size": 1})
                    ly = fnum(((r_ly.get("data") or [{}])[0]).get("full"))
                except Exception as e:
                    print("  pērn:", e)
                ser = [[d.get("gasDayStart"), fnum(d.get("full"))] for d in reversed(data)]
                out["facilities"].append({"country": cc, "name": name, "company": comp.get("name"),
                                          "lat": pos[0] if pos else None, "lon": pos[1] if pos else None,
                                          "type": ftype(name), "last_year_pct": ly, "series": ser,
                                          **row(data[0])})
                r = out["facilities"][-1]
                print(f"  {cc} {name}: {r['full_pct']}% {r['gas_twh']} TWh pērn {r['last_year_pct']}% "
                      f"maks. izņem. {r['wd_cap_gwh']} GWh/d {'(nav koordinātu)' if not pos else ''}")
                time.sleep(0.5)
    # --- ALSI: LNG termināļi (Klaipēda u.c.)
    out["lng"] = {}
    for cc in ("LT", "PL", "FI", "DE"):
        try:
            res = call({"country": cc, "size": 120}, "https://alsi.gie.eu/api")
        except Exception as e:
            print("ALSI", cc, e)
            continue
        data = res.get("data") or []
        if not data:
            print("ALSI", cc, "tukšs:", json.dumps(res)[:600])
            try:
                hdr = {"User-Agent": UA, "x-key": os.environ.get("ALSI_KEY") or os.environ.get("AGSI_KEY", "")}
                with urllib.request.urlopen(urllib.request.Request("https://alsi.gie.eu/api/about?show=listing", headers=hdr), timeout=60) as rr:
                    lst = json.loads(rr.read())
                items = lst if isinstance(lst, list) else [x for v in lst.values() for x in (v if isinstance(v, list) else [])]
                for comp in items:
                    if comp.get("country") == cc:
                        for fac in comp.get("facilities") or []:
                            print("   ALSI listing:", comp.get("name"), comp.get("eic"), "|", fac.get("name"), fac.get("eic"))
                            r2 = call({"country": cc, "company": comp.get("eic"), "facility": fac.get("eic"), "size": 120},
                                      "https://alsi.gie.eu/api")
                            data += r2.get("data") or []
                if not items:
                    print("   ALSI listing raw:", json.dumps(lst)[:800])
            except Exception as e:
                print("   ALSI listing:", e)
        if data:
            print("ALSI", cc, json.dumps(data[:1])[:1200])
        if not data:
            continue
        def lrow(d):
            inv = d.get("inventory") or {}
            return {"day": d.get("gasDayStart"),
                    "lng_m3": fnum(inv.get("lng")) if isinstance(inv, dict) else fnum(d.get("lngInventory")),
                    "inv_gwh": fnum(inv.get("gwh")) if isinstance(inv, dict) else None,
                    "sendout_gwh": fnum(d.get("sendOut")), "dtmi_m3": fnum((d.get("dtmi") or {}).get("lng")
                                                                             if isinstance(d.get("dtmi"), dict) else d.get("dtmi")),
                    "dtmi_gwh": fnum((d.get("dtmi") or {}).get("gwh") if isinstance(d.get("dtmi"), dict) else None),
                    "dtrs_gwh": fnum(d.get("dtrs")), "status": d.get("status")}
        rows = [lrow(d) for d in data]
        out["lng"][cc] = {"name": data[0].get("name") or cc, "latest": rows[0], "series": list(reversed(rows))}
        r = rows[0]
        print(f"ALSI {cc}: {r['day']} krājums {r['lng_m3']} (10³ m³?) / {r['inv_gwh']} GWh, max {r['dtmi_m3']} / {r['dtmi_gwh']} GWh, "
              f"izsūtīts {r['sendout_gwh']} GWh/d")
        time.sleep(1)
    # --- ALSI: katrs LNG terminālis atsevišķi (Baltijas reģions)
    out["lng_fac"] = []
    try:
        hdr = {"User-Agent": UA, "x-key": os.environ.get("ALSI_KEY") or os.environ.get("AGSI_KEY", "")}
        with urllib.request.urlopen(urllib.request.Request("https://alsi.gie.eu/api/about?show=listing", headers=hdr),
                                    timeout=60) as rr:
            lst = json.loads(rr.read())
        items = lst if isinstance(lst, list) else [x for v in lst.values() for x in (v if isinstance(v, list) else [])]
        for comp in items:
            if comp.get("country") not in ("LT", "PL", "FI", "DE"):
                continue
            for fac in comp.get("facilities") or []:
                fname = fac.get("name") or ""
                if comp.get("country") == "DE" and not any(k in fname.upper() for k in ("MUKRAN", "LUBMIN", "OSTSEE")):
                    continue
                try:
                    r2 = call({"country": comp.get("country"), "company": comp.get("eic"), "facility": fac.get("eic"),
                               "size": 120}, "https://alsi.gie.eu/api")
                except Exception as e:
                    print("ALSI", fname, e)
                    continue
                rows = [lrow(d) for d in (r2.get("data") or [])]
                if not rows:
                    continue
                out["lng_fac"].append({"country": comp.get("country"), "name": fname, "company": comp.get("name"),
                                       "latest": rows[0], "series": list(reversed(rows))})
                r = rows[0]
                print(f"ALSI terminālis {fname}: {r['day']} {r['lng_m3']} / {r['dtmi_m3']} tūkst. m³, izsūt. {r['sendout_gwh']} GWh/d")
                time.sleep(0.5)
    except Exception as e:
        print("ALSI termināļi:", e)
    out["needs_key"] = not os.environ.get("AGSI_KEY")
    print("krātuves:", [(f["country"], f["name"], f["lat"] is not None) for f in out["facilities"]])
    (OUT / "latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
