"""Pārvērš out/changes.json par diplomacy_events dokumentiem latviski (out/events_batch_*.json)."""
import hashlib, json, sys
from pathlib import Path
from lvnames import lv_name
OUT = Path(__file__).parent / "out"
HN = {"LV": ("Latvijā", "Rīgā"), "EE": ("Igaunijā", "Tallinā"), "FI": ("Somijā", "Helsinkos"), "PL": ("Polijā", "Varšavā"),
      "LT": ("Lietuvā", "Viļņā"), "SE": ("Zviedrijā", "Stokholmā"), "NO": ("Norvēģijā", "Oslo"),
      "RU": ("Krievijā", "Maskavā"), "BY": ("Baltkrievijā", "Minskā")}
HEAD = {"ambassador": "vēstnieks", "chargé": "lietvedis", "none": "nav vadītāja"}
KEY = {"RU", "BY", "US", "GB", "DE", "FR", "CN", "PL", "LT", "LV", "EE", "FI", "SE", "NO", "DK", "UA", "IT", "CA", "JP", "TR"}
SRCN = {"US": "ASV", "UK": "Lielbritānija", "DE": "Vācija", "CA": "Kanāda"}
FIELDN = {"level": "līmenis", "ordered_departure": "obligāta izbraukšana", "authorized_departure": "atļauta izbraukšana",
          "suspended": "vēstniecības darbība apturēta", "alert_status": "brīdinājums", "warning": "ceļošanas brīdinājums",
          "partial_warning": "daļējs brīdinājums", "situation_warning": "situācijas brīdinājums",
          "situation_part_warning": "daļējs situācijas brīdinājums", "advisory_state": "līmenis", "has_regional": "reģionāls brīdinājums"}
ev = []
for c in json.loads((OUT / "changes.json").read_text()):
    k = c["kind"]; h = c["country"]; loc, city = HN.get(h, (h, h))
    s = c.get("sender") or ""; sn = lv_name(s, c.get("sender_name") or s)
    foe = s.split("_")[0] in ("RU", "BY")
    date = (c.get("source") or "").split("→")[-1].strip() if k.startswith("mission") else c["at"][:10]
    o, n = c.get("old") or {}, c.get("new") or {}
    lvl, txt = "green", None
    if k == "mission_diplomats_resident":
        a, b = o["diplomats_resident"], n["diplomats_resident"]
        txt = f"{sn}: diplomāti {city} {a} → {b}"
        if b < a and (foe or s in KEY) and (a - b >= 3 or foe or b == 0): lvl = "yellow"
        if foe and b < a: lvl = "red" if b == 0 else "yellow"
    elif k == "mission_head":
        txt = f"{sn}: vēstniecību {city} tagad vada {HEAD.get(n['head'], n['head'])} (bija {HEAD.get(o['head'], o['head'])})"
        if o["head"] == "ambassador" and n["head"] != "ambassador" and (foe or s in KEY): lvl = "yellow"
    elif k == "mission_gone":
        txt = f"{sn}: vēstniecība {city} vairs nav sarakstā"
        lvl = "red" if (foe or s in KEY) else "yellow"
    elif k == "mission_new":
        txt = f"{sn}: jauna vēstniecība {city} sarakstā"
    elif k == "mission_resident_mission":
        txt = f"{sn}: vēstniecība " + (f"tagad atrodas {city}" if n["resident_mission"] else f"vairs neatrodas {city}")
        if not n["resident_mission"] and (foe or s in KEY): lvl = "yellow"
    elif k == "mission_defence":
        txt = f"{sn}: atašeju skaits {city} {o['defence']} → {n['defence']}"
        if foe and n["defence"] > o["defence"]: lvl = "yellow"
    elif k == "advisory":
        f = next(iter(n)); a, b = o.get(f), n.get(f)
        txt = f"{SRCN.get(c['source'], c['source'])} par {loc}: {FIELDN.get(f, f)} {a} → {b}"
        lvl = "red" if h not in ("RU", "BY") else "yellow"
        s = c["source"]
    if not txt: continue
    did = hashlib.sha1(json.dumps(c, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    ev.append({"op": "set", "collection": "diplomacy_events", "doc_id": did,
               "data": {"date": date, "host": h, "sender": s, "kind": k, "text": txt, "level": lvl,
                        "source": "Oficiālais diplomātu saraksts" if k.startswith("mission") else "Ceļošanas brīdinājumi",
                        "auto": True}})
(OUT / "ev").mkdir(exist_ok=True)
for e in ev:  # viens fails katram notikumam (ArtifactData file_path)
    (OUT / "ev" / f"{e['doc_id']}.json").write_text(json.dumps(e["data"], ensure_ascii=False))
for i in range(0, len(ev), 50):
    (OUT / f"events_batch_{i // 50}.json").write_text(json.dumps(ev[i:i + 50], ensure_ascii=False))
print(len(ev), "notikumi")
for e in ev: print(" ", e["data"]["date"], e["data"]["level"], e["data"]["text"])
