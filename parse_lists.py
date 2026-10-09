"""Nolasa lejupielādētos diplomātu sarakstus un saskaita diplomātus pa vēstniecībām.

Ievade:  data/lists/index.json + faili data/lists/<CC>/
Izvade:  data/missions/<CC>/<saraksta datums>.json — viena saraksta momentuzņēmums
         data/missions/latest.json                  — jaunākais stāvoklis visās uzņēmējvalstīs
         data/changes.jsonl                         — izmaiņas starp divām secīgām versijām
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
try:
    import pycountry
except ImportError:  # vietējai pārbaudei bez pycountry
    pycountry = None
from docx import Document

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = DATA / "missions"
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

HOSTS = {
    "LV": {"capital": "Riga", "loc_sep": "tab"},
    "EE": {"capital": "Tallinn", "loc_sep": "titlecase"},
    "PL": {"capital": "Warszawa", "loc_sep": "tab", "heads_only": True},  # Polija publicē tikai vadītājus
    "FI": {"capital": "Helsinki", "loc_sep": "json"},
}

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
HONORIFIC = re.compile(
    r"^\s*(H\.?\s?E\.?\s+)?(Mr|Ms|Mrs|Miss|Dr|Prof|Rev|Msgr|Mgr|Mons|Fr|"
    r"Lt\.?\s*Col|Lt\.?\s*Cdr|Lt|Col|Cdr|Capt|Maj|Brig|Gen|Adm|Rear\s+Adm|Cmdr|Colonel|Lieutenant|"
    r"Commander|Captain|Major|Brigadier|General|Admiral|Sgt|WO)\b\.?", re.I)
SEPARATOR = re.compile(r"^[\s_\-–—…\.]{10,}$")
FOOTER = re.compile(r"^\s*(VM\s*\|\s*VM|\d{1,3})\s*$")
NATDAY = re.compile(r"^\s*national\s+day\s*:", re.I)
MISSION_LINE = re.compile(r"embass|nunciature|high commission|delegation|representation|office of|apostolic", re.I)
DEFENCE = re.compile(r"defen[cs]e|military|naval|air\s*attach|army|armed forces", re.I)
HEAD_AMB = re.compile(r"ambassador extraordinary|^\s*ambassador\b|nuncio|high commissioner", re.I)
HEAD_CDA = re.compile(r"charg[eé]\s*d", re.I)

# Nosaukumi, ko pycountry nepazīst vai sajauc
ALIASES = {
    "RUSSIAN FEDERATION": "RU", "UNITED STATES OF AMERICA": "US", "UNITED KINGDOM": "GB",
    "UNITED KINGDOM OF GREAT BRITAIN AND NORTHERN IRELAND": "GB", "TÜRKIYE": "TR", "TURKEY": "TR",
    "HOLY SEE": "VA", "THE HOLY SEE": "VA", "KOREA": "KR", "REPUBLIC OF KOREA": "KR",
    "PEOPLE'S REPUBLIC OF CHINA": "CN", "CHINA": "CN", "IRAN": "IR", "MOLDOVA": "MD",
    "CZECH REPUBLIC": "CZ", "CZECHIA": "CZ", "VIETNAM": "VN", "VIET NAM": "VN",
    "SOCIALIST REPUBLIC OF VIETNAM": "VN", "PALESTINE": "PS", "KOSOVO": "XK", "LAOS": "LA",
    "LAO PEOPLE'S DEMOCRATIC REPUBLIC": "LA", "SOVEREIGN MILITARY ORDER OF MALTA": "SMOM",
    "BELARUS": "BY", "SLOVAKIA": "SK", "SLOVAK REPUBLIC": "SK", "SYRIA": "SY",
    "ARGENTINE REPUBLIC": "AR", "HELLENIC REPUBLIC": "GR", "ITALIAN REPUBLIC": "IT", "PORTUGUESE REPUBLIC": "PT",
    "SWISS CONFEDERATION": "CH", "FRENCH REPUBLIC": "FR", "UNITED ARAB EMIRATES": "AE", "UNITED MEXICAN STATES": "MX",
    "KINGDOM OF THE NETHERLANDS": "NL", "THE NETHERLANDS": "NL", "NETHERLANDS": "NL", "GABONESE REPUBLIC": "GA",
    "TOGOLESE REPUBLIC": "TG", "KYRGYZ REPUBLIC": "KG", "SYRIAN ARAB REPUBLIC": "SY", "DOMINICAN REPUBLIC": "DO",
    "FEDERATIVE REPUBLIC OF BRAZIL": "BR", "COOPERATIVE REPUBLIC OF GUYANA": "GY", "HASHEMITE KINGDOM OF JORDAN": "JO",
    "REPUBLIC OF THE UNION OF MYANMAR": "MM", "REPUBLIC OF THE PHILIPPINES": "PH", "REPUBLIC OF THE SUDAN": "SD",
    "UNITED REPUBLIC OF TANZANIA": "TZ", "ORIENTAL REPUBLIC OF URUGUAY": "UY", "GERMANY": "DE", "FRANCE": "FR",
    "ESTONIA": "EE", "LATVIA": "LV", "LITHUANIA": "LT", "POLAND": "PL", "FINLAND": "FI", "SWEDEN": "SE",
    "NORWAY": "NO", "DENMARK": "DK", "UKRAINE": "UA", "JAPAN": "JP", "CANADA": "CA", "ITALY": "IT", "SPAIN": "ES",
    "GREECE": "GR", "PORTUGAL": "PT", "SWITZERLAND": "CH", "AUSTRIA": "AT", "BELGIUM": "BE", "HUNGARY": "HU",
    "ROMANIA": "RO", "BULGARIA": "BG", "CROATIA": "HR", "SLOVENIA": "SI", "SERBIA": "RS", "GEORGIA": "GE",
    "ARMENIA": "AM", "AZERBAIJAN": "AZ", "KAZAKHSTAN": "KZ", "UZBEKISTAN": "UZ", "INDIA": "IN", "ISRAEL": "IL",
    "IRELAND": "IE", "LUXEMBOURG": "LU", "AUSTRALIA": "AU", "BRAZIL": "BR", "UNITED ARAB EMIRATES ": "AE",
}
PREFIXES = r"^(THE\s+)?((ISLAMIC|FEDERAL|DEMOCRATIC|SOCIALIST|PEOPLE'?S|ORIENTAL|BOLIVARIAN|PLURINATIONAL|" \
           r"GRAND|ROYAL|SULTANATE|STATE|PRINCIPALITY|KINGDOM|REPUBLIC|COMMONWEALTH|DUCHY)\s+(OF\s+)?(THE\s+)?)+"


def norm_country(name):
    raw = " ".join(name.replace("’", "'").split()).upper()
    m = re.match(r"^CONSULATE[\s-]GENERAL OF (.*)$", raw)
    if m:
        code, disp = norm_country(m.group(1))
        return code + "_CG", disp + " (ģenerālkonsulāts)"
    raw = re.sub(r"\s*\(.*?\)\s*$", "", raw)
    if "MALTA" in raw and ("ORDER" in raw or "HOSPITALLER" in raw):
        return "SMOM", "Order of Malta"
    if raw in ALIASES:
        code = ALIASES[raw]
    else:
        short = re.sub(PREFIXES, "", raw).strip() or raw
        code = ALIASES.get(short)
        if not code and pycountry:
            for cand in (raw, short):
                try:
                    code = pycountry.countries.lookup(cand).alpha_2
                    break
                except LookupError:
                    try:
                        code = pycountry.countries.search_fuzzy(cand)[0].alpha_2
                        break
                    except LookupError:
                        pass
    if not code:
        short = re.sub(PREFIXES, "", raw).strip() or raw
        return short, short.title()
    c = pycountry.countries.get(alpha_2=code) if pycountry else None
    return code, ((getattr(c, "common_name", None) or c.name) if c else raw.title())


def read_lines(path):
    if path.suffix == ".docx":
        return [p.text for p in Document(path).paragraphs]
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages).split("\n")


def list_date(lines):
    head = " ".join(l for l in lines[:40] if l.strip())
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d\d)\b", head)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    for pat, fmt in ((rf"(\d{{1,2}})\s+({MONTHS})\s+(\d{{4}})", "%d %B %Y"),
                     (rf"({MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})", "%B %d %Y")):
        m = re.search(pat, head, re.I)
        if m:
            return datetime.strptime(" ".join(m.groups()).title(), fmt).date().isoformat()
    return None


def split_location(line, host):
    """Atdala atrašanās vietu (pilsētu) no vārda vai amata rindas."""
    s = line.rstrip()
    if HOSTS[host]["loc_sep"] == "tab":
        parts = [p.strip() for p in s.split("\t") if p.strip()]
        if len(parts) >= 2 and re.match(r"^[A-Z][a-zà-ž\.\- ]+$", parts[-1]) and len(parts[-1]) < 25:
            return " ".join(parts[:-1]), parts[-1]
        return " ".join(parts), None
    # EE: vārdi ir ar lielajiem burtiem, pilsēta — ar mazajiem ("Mr JOHN SMITH Riga")
    m = re.match(r"^(.*?[A-ZÀ-Ž\.\-']{2,})\s+([A-Z][a-zà-ž]+(?:\s+[A-Z][a-zà-ž]+)?)\s*$", s)
    if m and HONORIFIC.match(s):
        return m.group(1), m.group(2)
    return s, None


def parse(path, host):
    lines = [l for l in read_lines(path) if not FOOTER.match(l)]
    date = list_date(lines)
    nat = [i for i, l in enumerate(lines) if NATDAY.match(l)]
    if not nat:  # Polijas formāts
        nat = [i + 1 for i, l in enumerate(lines[:-1])
               if l.strip() and l.strip().isupper() and not re.search(r"\d", l)
               and re.match(r"^\s*(EMBASSY|APOSTOLIC|DELEGATION|HIGH COMMISSION|MISSION|ROYAL EMBASSY)", lines[i + 1], re.I)]
    starts = []
    for i in nat:  # misijas nosaukums ir dažas rindas virs "National day"
        j, picked = i - 1, None
        for _ in range(4):
            while j >= 0 and not lines[j].strip():
                j -= 1
            if j < 0:
                break
            if MISSION_LINE.search(lines[j]) and not picked and not NATDAY.match(lines[i]) and j == i:
                j -= 1
                continue
            if MISSION_LINE.search(lines[j]) and not picked and NATDAY.match(lines[i]):
                j -= 1
                continue
            picked = j
            break
        if picked is not None:
            # nosaukums var būt divās rindās ("SOVEREIGN MILITARY ... / OF MALTA")
            name = lines[picked].strip()
            if picked > 0 and lines[picked - 1].strip() and lines[picked - 1].strip().isupper() \
                    and not SEPARATOR.match(lines[picked - 1]) and not HONORIFIC.match(lines[picked - 1]) \
                    and len(lines[picked - 1].strip()) < 60 and not MISSION_LINE.search(lines[picked - 1]):
                prev = lines[picked - 1].strip()
                if prev.endswith(("OF", "AND", "THE")) or name.upper().startswith(("OF ", "AND ", "JERUSALEM")):
                    name = prev + " " + name
                    picked -= 1
            starts.append((picked, i, name))

    # Sadaļu beigas: nākamās misijas sākums vai "CONSULATES-GENERAL"/"INTERNATIONAL ORGANISATIONS"
    stop_words = re.compile(r"^\s*(CONSULATES?[\s-]GENERAL|CONSULAR|INTERNATIONAL ORGANI[SZ]ATIONS|HONORARY)", re.I)
    missions = {}
    for k, (s, nat_i, name) in enumerate(starts):
        e = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        for t in range(nat_i, e):
            if stop_words.match(lines[t]) and t > nat_i + 3 and lines[t].strip().isupper():
                e = t
                break
        body = lines[nat_i:e]
        # Adrese ir pirms pēdējās svītras, kas atrodas virs pirmā cilvēka vārda
        first_person = next((t for t, l in enumerate(body) if HONORIFIC.match(l)), len(body))
        seps = [t for t, l in enumerate(body[:first_person]) if SEPARATOR.match(l)]
        sep = seps[-1] if seps else 0
        address = " ".join(body[:first_person])
        people = [l for l in body[sep:] if l.strip() and not SEPARATOR.match(l)]

        dips = []
        for t, l in enumerate(people):
            if not HONORIFIC.match(l):
                continue
            nxt = people[t + 1] if t + 1 < len(people) else ""
            if not nxt or HONORIFIC.match(nxt):
                continue  # aiz vārda nav amata → laulātais
            nm, loc = split_location(l, host)
            rank, rloc = split_location(nxt, host) if HOSTS[host]["loc_sep"] == "tab" else (nxt.strip(), None)
            dips.append({"name": " ".join(nm.split()), "rank": " ".join(rank.split()), "location": loc or rloc})

        cap = HOSTS[host]["capital"]
        resident_mission = cap.lower() in address.lower()
        resident = [d for d in dips if (d["location"] or (cap if resident_mission else "")).lower().startswith(cap.lower())]
        head = "ambassador" if any(HEAD_AMB.search(d["rank"]) for d in dips[:2]) else \
               "chargé" if any(HEAD_CDA.search(d["rank"]) for d in dips[:3]) else "none"
        if re.search(r"\d|…|\.{4}|@|:|HONORARY", name, re.I):
            continue  # satura rādītāja vai kalendāra rinda, nevis vēstniecība
        code, display = norm_country(name)
        key = code
        if key in missions:  # piem., divas misijas vienai valstij — saskaitām kopā
            key = f"{code}#{k}"
        missions[key] = {
            "country": display, "code": code, "raw_name": name,
            "resident_mission": resident_mission, "head": head,
            "diplomats": len(dips), "diplomats_resident": len(resident),
            "defence": sum(1 for d in dips if DEFENCE.search(d["rank"])),
            "staff": dips,
        }
    return {"host": host, "list_date": date, "parsed_at": NOW, "source_file": str(path.relative_to(ROOT)),
            "missions": missions}


def parse_fi_json(path):
    snap = json.loads(path.read_text(encoding="utf-8"))
    missions = {}
    for title, m in snap["missions"].items():
        t = re.sub(r"^(royal\s+)?(embassy|apostolic nunciature|delegation)\s+(of\s+)?(the\s+)?", "", title, flags=re.I)
        name, _, city = t.rpartition(",")
        name, city = (name or t).strip(), city.strip()
        dips = [d for d in m["staff"] if d.get("rank") and d["rank"].lower() != "hidden"]
        resident_mission = city.lower() == "helsinki"
        resident = [d for d in dips if (d.get("location") or "").lower().startswith("helsinki")]
        head = "ambassador" if any(HEAD_AMB.search(d["rank"]) for d in dips[:2]) else \
               "chargé" if any(HEAD_CDA.search(d["rank"]) for d in dips[:3]) else "none"
        code, display = norm_country(name)
        key = code if code not in missions else f"{code}#{len(missions)}"
        missions[key] = {"country": display, "code": code, "raw_name": title, "resident_mission": resident_mission,
                         "head": head, "diplomats": len(dips), "diplomats_resident": len(resident),
                         "defence": sum(1 for d in dips if DEFENCE.search(d["rank"])), "staff": dips}
    return {"host": "FI", "list_date": snap["list_date"], "parsed_at": NOW,
            "source_file": str(path.relative_to(ROOT)), "missions": missions}


def summary(snap):
    return {k: {f: v[f] for f in ("country", "resident_mission", "head", "diplomats", "diplomats_resident", "defence")}
            for k, v in snap["missions"].items()}


def diff(old, new, host):
    """Izmaiņas starp divām secīgām saraksta versijām."""
    ch = []
    o, n = summary(old), summary(new)
    for k in sorted(set(o) | set(n)):
        a, b = o.get(k), n.get(k)
        if a and not b:
            ch.append(("mission_gone", k, a["country"], a, None))
        elif b and not a:
            ch.append(("mission_new", k, b["country"], None, b))
        else:
            fields = ("resident_mission", "head") if HOSTS[host].get("heads_only") else \
                     ("resident_mission", "head", "diplomats_resident", "defence")
            for f in fields:
                if a[f] != b[f]:
                    ch.append((f"mission_{f}", k, b["country"], {f: a[f]}, {f: b[f]}))
    out = []
    for kind, code, country, a, b in ch:
        out.append({"at": NOW, "kind": kind, "country": host, "sender": code, "sender_name": country,
                    "source": f"{old['list_date']} → {new['list_date']}", "old": a, "new": b, "note": ""})
    return out


def main():
    index = json.loads((DATA / "lists" / "index.json").read_text(encoding="utf-8"))
    latest = {}
    for host, entries in index.items():
        if host not in HOSTS:
            continue
        snaps = []
        for e in entries:
            p = ROOT / e["file"]
            try:
                s = parse_fi_json(p) if p.suffix == ".json" else parse(p, host)
            except Exception as ex:
                print("ERR", p, ex)
                continue
            if not s["list_date"] or len(s["missions"]) < 20:
                print("SKIP", p, s["list_date"], len(s["missions"]))
                continue
            snaps.append(s)
            dest = OUT / host / f"{s['list_date']}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        snaps.sort(key=lambda s: s["list_date"])
        # unikāli pēc datuma
        uniq = {}
        for s in snaps:
            uniq[s["list_date"]] = s
        snaps = [uniq[d] for d in sorted(uniq)]
        if not snaps:
            continue

        # izmaiņas starp secīgām versijām, katru pāri ierakstām tikai vienreiz
        done_f = OUT / "processed_pairs.json"
        done = set(json.loads(done_f.read_text()) if done_f.exists() else [])
        new_changes = []
        for a, b in zip(snaps, snaps[1:]):
            pair = f"{host}:{a['list_date']}>{b['list_date']}"
            if pair in done:
                continue
            new_changes += diff(a, b, host)
            done.add(pair)
        if new_changes:
            with (DATA / "changes.jsonl").open("a", encoding="utf-8") as f:
                for c in new_changes:
                    f.write(json.dumps(c, ensure_ascii=False) + "\n")
        done_f.write_text(json.dumps(sorted(done), indent=1))

        cur, prev = snaps[-1], (snaps[-2] if len(snaps) > 1 else None)
        latest[host] = {
            "heads_only": bool(HOSTS[host].get("heads_only")),
            "list_date": cur["list_date"], "previous_list_date": prev["list_date"] if prev else None,
            "missions": summary(cur),
            "previous": summary(prev) if prev else None,
        }
        print(host, cur["list_date"], "misijas:", len(cur["missions"]),
              "diplomāti rezidenti:", sum(m["diplomats_resident"] for m in cur["missions"].values()))
    (OUT / "latest.json").write_text(json.dumps({"updated_at": NOW, "hosts": latest}, ensure_ascii=False, indent=1),
                                     encoding="utf-8")


if __name__ == "__main__":
    main()
