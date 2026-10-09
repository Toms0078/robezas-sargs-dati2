"""Sagatavo GitHub datus Robežas sarga datubāzei (ArtifactData file_path).

Palaiž ieplānotais Claude uzdevums pēc `git pull`:
    python export_db.py
Izvade mapē out/:
    hosts.json        → diplomacy/hosts       (diplomāti pa vēstniecībām katrā uzņēmējvalstī + iepriekšējā versija)
    advisories.json   → diplomacy/advisories  (ASV, UK, Vācijas, Kanādas brīdinājumi 9 valstīm)
    changes.json      → saraksts izmaiņām pēdējās 120 dienās (Claude ieraksta diplomacy_events)
    news_recent.json  → pēdējo 3 dienu ziņu virsraksti, ko Claude klasificē
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lvnames import lv_name

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)
NOW = datetime.now(timezone.utc)

HOST_INFO = {
    "LV": {"name": "Latvija", "city": "Rīga", "status": "ok", "kind": "full"},
    "EE": {"name": "Igaunija", "city": "Tallina", "status": "ok", "kind": "full"},
    "FI": {"name": "Somija", "city": "Helsinki", "status": "ok", "kind": "full"},
    "PL": {"name": "Polija", "city": "Varšava", "status": "ok", "kind": "heads",
           "note": "Polija publicē tikai vēstniecību vadītājus, ne visu personālu."},
    "LT": {"name": "Lietuva", "city": "Viļņa", "status": "unavailable",
           "note": "Lietuva oficiālu diplomātu sarakstu publiski nepublicē; seko ziņām un brīdinājumiem."},
    "SE": {"name": "Zviedrija", "city": "Stokholma", "status": "blocked",
           "note": "Zviedrijas valdības lapa bloķē automātisku lejupielādi."},
    "NO": {"name": "Norvēģija", "city": "Oslo", "status": "blocked",
           "note": "Norvēģijas valdības lapa bloķē automātisku lejupielādi."},
}


def load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def hosts():
    latest = load(DATA / "missions" / "latest.json", {"hosts": {}})
    out = {"updatedAt": NOW.isoformat(timespec="seconds"), "hosts": []}
    for cc, info in HOST_INFO.items():
        h = latest["hosts"].get(cc)
        row = {"code": cc, **info}
        if h:
            prev = h.get("previous") or {}
            ms = []
            for key, m in h["missions"].items():
                if not m["resident_mission"] and m["diplomats_resident"] == 0:
                    continue  # nerezidējošas misijas (vēstnieks citā galvaspilsētā) neinteresē
                p = prev.get(key)
                ms.append({
                    "k": key, "c": lv_name(key, m["country"]), "head": m["head"], "n": m["diplomats_resident"],
                    "def": m["defence"],
                    "pn": p["diplomats_resident"] if p else None,
                    "phead": p["head"] if p else None,
                })
            ms.sort(key=lambda x: (-x["n"], x["c"]))
            row.update({"listDate": h["list_date"], "prevDate": h.get("previous_list_date"),
                        "missions": ms,
                        "total": sum(x["n"] for x in ms)})
        out["hosts"].append(row)
    return out


def advisories():
    a = load(DATA / "advisories.json", {})
    names = {"LV": "Latvija", "EE": "Igaunija", "LT": "Lietuva", "PL": "Polija", "FI": "Somija",
             "SE": "Zviedrija", "NO": "Norvēģija", "RU": "Krievija", "BY": "Baltkrievija"}
    rows = []
    for cc, nm in names.items():
        us = a.get("US", {}).get(cc, {})
        uk = a.get("UK", {}).get(cc, {})
        de = a.get("DE", {}).get(cc, {})
        ca = a.get("CA", {}).get(cc, {})
        uk_lv = 4 if "avoid_all_travel_to_whole_country" in (uk.get("alert_status") or []) else \
                3 if any("avoid_all" in s for s in (uk.get("alert_status") or [])) else \
                2 if uk.get("alert_status") else 1 if uk else None
        de_lv = 4 if de.get("warning") else 3 if de.get("partial_warning") else \
                2 if (de.get("situation_warning") or de.get("situation_part_warning")) else 1 if de else None
        ca_lv = (int(ca["advisory_state"]) + 1) if ca.get("advisory_state") is not None else None
        rows.append({"cc": cc, "c": nm,
                     "us": us.get("level"), "uk": uk_lv, "de": de_lv, "ca": ca_lv,
                     "usFlags": [f for f in ("ordered_departure", "authorized_departure", "suspended") if us.get(f)]})
    return {"updatedAt": a.get("updated_at"), "rows": rows}


def changes():
    out = []
    cut = NOW - timedelta(days=120)
    for line in (DATA / "changes.jsonl").read_text(encoding="utf-8").splitlines() if (DATA / "changes.jsonl").exists() else []:
        try:
            c = json.loads(line)
        except Exception:
            continue
        if datetime.fromisoformat(c["at"]) < cut or c["kind"] == "diplomatic_list_new":
            continue
        out.append(c)
    return out


def news_recent():
    cut = NOW - timedelta(days=3)
    out = []
    p = DATA / "news.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines() if p.exists() else []:
        try:
            it = json.loads(line)
        except Exception:
            continue
        if datetime.fromisoformat(it["seen_at"]) >= cut:
            out.append({k: it.get(k) for k in ("id", "tag", "title", "source", "published", "url")})
    return out


if __name__ == "__main__":
    for name, fn in (("hosts", hosts), ("advisories", advisories), ("changes", changes), ("news_recent", news_recent)):
        obj = fn()
        (OUT / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        size = (OUT / f"{name}.json").stat().st_size
        print(f"{name}: {size} B", len(obj) if isinstance(obj, list) else "")
