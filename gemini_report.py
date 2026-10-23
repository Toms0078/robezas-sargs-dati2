"""Robežas sarga galvenais pārskats "Vai palikt?" ar Google Gemini + Google meklēšanu (aizstāj Claude ieplānoto uzdevumu).

  python gemini_report.py         # izveido jaunu pārskatu → data/rs/reports.json (jaunākais pirmais, glabā 10)
Pārskats tiek veidots 3 daļās (ziņas; vadītāji+ceļošana+drošība; infrastruktūra). Katrai daļai par pamatu ņem iepriekšējo pārskatu.
Godīgums: katram ierakstam ar saiti tā jābūt no Gemini meklēšanas avotiem vai jau no iepriekšējā pārskata, citādi ierakstu izmet.
Ja daļai Gemini nemeklēja vai atbilde nederīga — šo daļu paņem no iepriekšējā pārskata nemainītu (un logā to atzīmē).
Lidmašīnas ņem no data/rs/airchecks.json (air_checks.py, bez AI).
"""
import json, os, re, sys, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import air_alerts as A

ROOT = Path(__file__).parent
RS = ROOT / "data" / "rs"
FILE, LOGF = RS / "reports.json", RS / "gemini_report.log"
KEEP = 10
LEVELS = {"green", "yellow", "red"}
MODEL_ORDER = ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]

RULES = """Noteikumi (obligāti):
- Raksti latviski, īsi, faktus. Datumi DD.MM.GGGG. Nespekulē par nodomiem; ja izcelsme nav apstiprināta, raksti "nav apstiprināts".
- Katram ierakstam: "source" (izdevums) un "url" (konkrēta raksta saite, ko atradi meklējot). Neizdomā saites, skaitļus, vārdus.
- Ja par kādu ierakstu jaunas informācijas nav — atstāj iepriekšējo ierakstu nemainītu (ar to pašu saiti).
- Līmeņi: green = parasti; yellow = jāseko (incidents, brīdinājums, saspīlējums); red = tiešs apdraudējums Latvijai/kaimiņiem.
- Atbildi TIKAI ar vienu JSON objektu ```json ... ```, tieši tādā pašā struktūrā kā dotais iepriekšējais variants (tās pašas atslēgas)."""


def load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def host(u):
    return re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*", r"\1", str(u or "")).lower())


def ask(prompt, key):
    base = list(A.MODELS)
    try:
        for first in MODEL_ORDER:
            A.MODELS[:] = [first] + [x for x in base if x != first]
            txt, m, nq, doms = A.call_gemini(prompt, key)
            if doms:
                return A.extract_json(txt), m, doms
        return None, m, set()
    finally:
        A.MODELS[:] = base


def urls_of(o, acc):
    if isinstance(o, dict):
        if o.get("url"): acc.add(str(o["url"]))
        for v in o.values(): urls_of(v, acc)
    elif isinstance(o, list):
        for v in o: urls_of(v, acc)
    return acc


def scrub(o, ok, stat):
    """Izmet sarakstu elementus (dict), kuru saite nav pārbaudāma."""
    if isinstance(o, list):
        out = []
        for v in o:
            if isinstance(v, dict) and v.get("url") and not ok(v["url"]):
                stat["drop"] += 1; continue
            out.append(scrub(v, ok, stat))
        return out
    if isinstance(o, dict):
        return {k: scrub(v, ok, stat) for k, v in o.items()}
    return o


def fix_levels(o):
    if isinstance(o, dict):
        if "level" in o and isinstance(o["level"], str) and o["level"] not in LEVELS and not o["level"].isdigit():
            o["level"] = "yellow"
        for v in o.values(): fix_levels(v)
    elif isinstance(o, list):
        for v in o: fix_levels(v)


PARTS = [
    ("ziņas", ["headline", "level", "summary", "sections", "events", "sources"],
     """Atrodi drošības jaunumus pēdējās ~24 h (kopš iepriekšējā pārskata) Latvijai un kaimiņiem: gaisa telpas incidenti un brīdinājumi (LV, LT, EE,
PL, FI), droni, Krievijas/Baltkrievijas karaspēka pārvietošana, mācības pie robežām, robežas incidenti, kritiskās infrastruktūras incidenti
(kabeļi, cauruļvadi), oficiāli paziņojumi (NBS, VDD, AM, Lietuvas/Igaunijas iestādes), vēstniecības, Ziemeļvalstis un Gotlande.
Meklē vairākās valodās (latviski, lietuviski, igauniski, poliski, krieviski, angliski).
"sections": saglabā tās pašas sadaļas (key, title); katrā 2–5 jaunākie "items" (date, source, text, url) un īss "summary", "level".
"events": līdz 15 kartes notikumiem (date, kind: airspace|border|drone|exercise|infra|military|statement, lat, lon, approx true ja vieta aptuvena,
level, short ≤ 25 zīmes, title, source, url; dronu/gaisa telpas notikumiem arī origin: russia|belarus|ukraine|unknown, originConf, originNote).
Vecākus par 7 dienām notikumus izmet. "headline": 1 teikums (sāc ar "Rīta pārskats:" vai "Vakara pārskats:"). "summary": 2–4 teikumi.
"level": kopējais. "sources": 5–10 svarīgākās saites (title, url)."""),
    ("vadītāji, ceļošana, drošība", ["leaders", "travel", "safety"],
     """Atjauno: "leaders.people" — tie paši cilvēki (Baltijas, Polijas, Somijas, Zviedrijas, Norvēģijas valsts vadītāji): vai viņi ir savā valstī
(status: home|likely_home|abroad|unknown, where — kur, ja ārzemēs), pēdējā publiskā aktivitāte (text, date, source, url).
"travel.rows" — ASV (travel.state.gov) un Kanādas (travel.gc.ca) ceļošanas brīdinājumu līmeņi šīm 7 valstīm (level, label latviski, date, url).
"safety" — "stage" (1 = Ikdiena … 5), "text" (2–3 teikumi: vai dzīvot Latvijā joprojām ir droši un kāpēc), "signals" (3–6 svarīgākie signāli ar saitēm).
Nemaini posmu bez skaidra iemesla no ziņām."""),
    ("infrastruktūra", ["infra"],
     """Atjauno "infra.indicators" (tie paši key: power, gas, fuel, cables, money, meds, food, comms, border, exits): katram value, level, text,
date, source, url, un "countries" (c, level, value) — elektrības biržas cena (Nord Pool), gāzes apgāde, degvielas cenas un pieejamība,
zemūdens kabeļu/cauruļvadu stāvoklis, maksājumi/bankas, zāles, pārtika, sakari, robežpārejas, izbraukšanas iespējas (lidojumi, prāmji).
"infra.level" un "infra.summary" (1–2 teikumi)."""),
]


def main():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        A.log("GEMINI_API_KEY nav"); return
    arr = load(FILE, [])
    if not arr:
        A.log("nav iepriekšējā pārskata"); return
    prev = arr[0]
    t_now = A.now()
    riga = t_now.astimezone(ZoneInfo("Europe/Riga"))
    kind = "Rīta" if riga.hour < 14 else "Vakara"
    A.log(f"{A.iso(t_now)} {kind.lower()} pārskats (iepriekšējais {prev.get('_id')})")
    prev_urls = urls_of(prev, set())
    rep = {k: v for k, v in prev.items() if k != "_id"}
    used = []
    for name, keys, task in PARTS:
        part_prev = {k: prev.get(k) for k in keys}
        prompt = (f"Tagad {riga.strftime('%d.%m.%Y %H:%M')} (Rīgas laiks). Tu gatavo {kind.lower()} pārskatu Latvijas iedzīvotājam "
                  f"\"Vai palikt Latvijā?\" — daļa: {name}.\nOBLIGĀTI izmanto Google meklēšanu (vairākus vaicājumus).\n{task}\n\n{RULES}\n\n"
                  f"Iepriekšējais variants ({prev.get('generatedAt')}):\n```json\n{json.dumps(part_prev, ensure_ascii=False)}\n```")
        try:
            j, m, doms = ask(prompt, key)
        except Exception as e:
            A.log(f"{name}: kļūda — {e}; paturu iepriekšējo"); continue
        if not doms or not isinstance(j, dict) or not all(k in j for k in keys):
            A.log(f"{name}: nav derīgas atbildes ar meklēšanu ({'avoti ' + str(len(doms)) if doms else 'nemeklēja'}); paturu iepriekšējo")
            continue
        ok = lambda u: str(u) in prev_urls or (lambda h: bool(h) and any(h == d or h.endswith("." + d) or d.endswith("." + h) for d in doms))(host(u))
        stat = {"drop": 0}
        j = scrub({k: j[k] for k in keys}, ok, stat)
        fix_levels(j)
        if "level" in j and j["level"] not in LEVELS: j["level"] = prev.get("level", "yellow")
        rep.update(j)
        used.append(m)
        A.log(f"{name}: atjaunots ({m}, avoti {len(doms)}, izmesti nepārbaudāmi ieraksti: {stat['drop']})")
    if not used:
        A.log("neviena daļa netika atjaunota — jaunu pārskatu nesaglabāju")
        LOGF.write_text("\n".join(A.log_lines) + "\n", encoding="utf-8"); return
    ac = load(RS / "airchecks.json", [])
    if ac:
        rep["aircraft"] = {k: v for k, v in ac[0].items() if k != "_id"}
    if not str(rep.get("headline", "")).startswith(kind):
        rep["headline"] = re.sub(r"^(Rīta|Vakara) pārskats:\s*", "", str(rep.get("headline", ""))).strip()
        rep["headline"] = f"{kind} pārskats: {rep['headline']}"
    rep["generatedAt"] = t_now.strftime("%Y-%m-%dT%H:%M:%SZ")
    rep["via"] = "Gemini (" + ", ".join(sorted(set(used))) + ") ar Google meklēšanu, GitHub Actions"
    rep["_id"] = riga.strftime("%Y-%m-%d-%H%M")
    arr = [rep] + [x for x in arr if x.get("_id") != rep["_id"]]
    FILE.write_text(json.dumps(arr[:KEEP], ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    A.log(f"saglabāts {rep['_id']}: {rep['headline'][:200]}")
    LOGF.write_text("\n".join(A.log_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
