"""Vienreizēja pārbaude: kādi ĀTI dati pieejami Eurostat API 7 valstīm."""
import json, requests
from pathlib import Path
B = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
out = {}
def q(name, ds, params):
    try:
        r = requests.get(B + ds, params=params, timeout=90)
        j = r.json()
        dims = {d: list((j.get("dimension", {}).get(d, {}).get("category", {}).get("label", {}) or {}).items())[:60]
                for d in j.get("id", [])}
        vals = j.get("value", {})
        out[name] = {"status": r.status_code, "url": r.url, "size": j.get("size"), "dims": dims,
                     "n_values": len(vals), "sample": list(vals.items())[:10], "error": j.get("error")}
    except Exception as e:
        out[name] = {"error": str(e)[:300]}
q("bop_c6_q_LV_meta", "bop_c6_q", {"geo": "LV", "lastTimePeriod": "1", "currency": "MIO_EUR", "stk_flow": "LIAB"})
q("bop_c6_q_FDI", "bop_c6_q", {"geo": ["LV","LT","EE","PL","FI","SE","NO"], "bop_item": "FA__D__F", "stk_flow": "LIAB",
    "currency": "MIO_EUR", "partner": "WRL_REST", "sector10": "S1", "sectpart": "S1", "s_adj": "NSA", "lastTimePeriod": "8"})
q("bop_fdi6_flow_meta", "bop_fdi6_flow", {"geo": "LV", "lastTimePeriod": "1"})
Path("data").mkdir(exist_ok=True)
Path("data/probe_fdi.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print({k: (v.get("status"), v.get("n_values"), str(v.get("error"))[:200]) for k, v in out.items()})
