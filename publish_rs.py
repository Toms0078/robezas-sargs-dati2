"""Publicē GitHub savāktos vēstniecību un investīciju datus Robežas sarga lapai (data/rs/), bez AI.

Palaiž darbplūsma "Vākt datus" pēc fetch.py:  python export_db.py && python to_events.py && python publish_rs.py
  out/hosts.json       → data/rs/diplomacy/hosts.json
  out/advisories.json  → data/rs/diplomacy/advisories.json
  out/fdi.json         → data/rs/investment/fdi.json
  out/ev/*.json        → pievieno data/rs/diplomacy_events.json (automātiskie notikumi no sarakstu/brīdinājumu izmaiņām)
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent
OUT, RS = ROOT / "out", ROOT / "data" / "rs"


def load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(p, obj, compact=False):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(obj, ensure_ascii=False, indent=1),
                 encoding="utf-8")


def main():
    for src, dst in (("hosts", "diplomacy/hosts"), ("advisories", "diplomacy/advisories"), ("fdi", "investment/fdi")):
        obj = load(OUT / f"{src}.json", None)
        if obj:  # never overwrite with empty data
            save(RS / f"{dst}.json", obj)
            print(f"{dst}: ok")
    events = load(RS / "diplomacy_events.json", [])
    have = {e.get("_id") for e in events}
    added = 0
    for f in sorted((OUT / "ev").glob("*.json")) if (OUT / "ev").exists() else []:
        if f.stem in have:
            continue
        e = load(f, None)
        if e:
            e["_id"] = f.stem
            events.append(e); added += 1
    events.sort(key=lambda e: str(e.get("date") or ""), reverse=True)
    save(RS / "diplomacy_events.json", events[:150], compact=True)
    print(f"diplomacy_events: +{added}, kopā {min(len(events), 150)}")


if __name__ == "__main__":
    main()
