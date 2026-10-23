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


def search(prompt, key):
    """1. solis: Gemini ar Google meklēšanu atrod faktus (īss vaicājums bez JSON — tā modelis drošāk meklē)."""
    base = list(A.MODELS)
    try:
        for first in MODEL_ORDER:
            A.MODELS[:] = [first] + [x for x in base if x != first]
            txt, m, nq, doms = A.call_gemini(prompt, key)
            if doms:
                return txt, m, doms
        return "", m, set()
    finally:
        A.MODELS[:] = base


def ask(search_prompt, merge_prompt, key):
    """2. solis: bez meklēšanas apvieno atrastos faktus ar iepriekšējo variantu JSON formā."""
    facts, m, doms = search(search_prompt, key)
    if not doms:
        return None, m, doms
    import air_alerts_fast as F
    txt, m2 = F.call_plain(merge_prompt.replace("<<FAKTI>>", facts[:30000]), key)
    return A.extract_json(txt), m, doms


_alive = {}
def alive(u):
    """Gemini dažkārt izdomā ticamu saiti uz īstu vietni — pārbauda, vai raksts eksistē (404/410/nav vietnes = izdomāts)."""
    if u in _alive: return _alive[u]
    import requests
    ok = True
    try:
        r = requests.get(u, timeout=20, allow_redirects=True, stream=True,
                         headers={"User-Agent": "Mozilla/5.0 (robezas-sargs link check)"})
        ok = r.status_code not in (404, 410); r.close()
    except requests.exceptions.ConnectionError:
        ok = False
    except Exception:
        ok = True
    _alive[u] = ok
    return ok


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
     """Vispirms meklē (vairākus vaicājumus ar šodienas un vakardienas datumu), tad atrodi drošības jaunumus pēdējās ~24 h (kopš iepriekšējā pārskata) Latvijai un kaimiņiem: gaisa telpas incidenti un brīdinājumi (LV, LT, EE,
PL, FI), droni, Krievijas/Baltkrievijas karaspēka pārvietošana, mācības pie robežām, robežas incidenti, kritiskās infrastruktūras incidenti
(kabeļi, cauruļvadi), oficiāli paziņojumi (NBS, VDD, AM, Lietuvas/Igaunijas iestādes), vēstniecības, Ziemeļvalstis un Gotlande.
Meklē vairākās valodās (latviski, lietuviski, igauniski, poliski, krieviski, angliski).
"sections": TIEŠI tās pašas 5 sadaļas ar tiem pašiem key (air, russia, osint, official, nordic) un title; katrā 2–5 jaunākie "items" (date, source, text, url) un īss "summary", "level".
"events": līdz 15 kartes notikumiem (date, kind: airspace|border|drone|exercise|infra|military|statement, lat, lon, approx true ja vieta aptuvena,
level, short ≤ 25 zīmes, title, source, url; dronu/gaisa telpas notikumiem arī origin: russia|belarus|ukraine|unknown, originConf, originNote).
Vecākus par 7 dienām notikumus izmet. "headline": 1 teikums (sāc ar "Rīta pārskats:" vai "Vakara pārskats:"). "summary": 2–4 teikumi.
"level": kopējais. "sources": 5–10 svarīgākās saites (title, url)."""),
    ("valstu vadītāji", ["leaders"],
     """Vispirms meklē katra cilvēka vārdu ar šodienas/vakardienas datumu (piem. "Rinkēvičs vizīte", "Nausėda", "Michal", "Stubb", "Orpo",
"Kristersson", "Støre", aizsardzības ministri, bruņoto spēku komandieri). Atjauno "leaders.people" — tie paši cilvēki: vai viņi ir savā valstī
(status: home|likely_home|abroad|unknown, where — kur, ja ārzemēs), pēdējā publiskā aktivitāte (text, date, source, url).
Ja par kādu jaunu ziņu neatradi — atstāj iepriekšējo ierakstu."""),
    ("drošības posms", ["safety"],
     """Vispirms meklē: "Latvija drošība šodien", "NBS paziņojums", "VDD brīdinājums", "Baltic security news today", "Russia NATO Baltic".
Atjauno "safety": "stage" (1 = Ikdiena … 5), "text" (2–3 teikumi: vai dzīvot Latvijā joprojām ir droši un kāpēc), "signals" (3–6 svarīgākie
signāli ar saitēm: oficiāli paziņojumi, ceļošanas brīdinājumi, vēstniecību rīcība). Nemaini posmu bez skaidra iemesla no ziņām."""),
    ("infrastruktūra", ["infra"],
     """Vispirms meklē: "Nord Pool Latvia price", "degvielas cenas Latvijā", "Inčukalns gāze", "Baltic subsea cable", "robežpāreja Latvija".
Atjauno "infra.indicators" (tie paši key: power, gas, fuel, cables, money, meds, food, comms, border, exits): katram value, level, text,
date, source, url, un "countries" (c, level, value) — elektrības biržas cena (Nord Pool), gāzes apgāde, degvielas cenas un pieejamība,
zemūdens kabeļu/cauruļvadu stāvoklis, maksājumi/bankas, zāles, pārtika, sakari, robežpārejas, izbraukšanas iespējas (lidojumi, prāmji).
"infra.level" un "infra.summary" (1–2 teikumi)."""),
]


LBL = {1: "Parasta piesardzība", 2: "Paaugstināta piesardzība", 3: "Pārdomāt braucienu", 4: "Nebraukt"}


def travel_from_advisories(rep, prev, riga):
    """ASV un Kanādas līmeņi no data/rs/diplomacy/advisories.json (fetch.py, bez AI)."""
    adv = {r.get("c"): r for r in (load(RS / "diplomacy" / "advisories.json", {}) or {}).get("rows") or []}
    rows = ((prev.get("travel") or {}).get("rows")) or []
    if not adv or not rows: return
    today, ch = riga.strftime("%d.%m.%Y"), 0
    for r in rows:
        a = adv.get(r.get("c"))
        if not a: continue
        for k in ("us", "ca"):
            lv = a.get(k)
            if isinstance(lv, int) and isinstance(r.get(k), dict) and str(r[k].get("level")) != str(lv):
                r[k].update(level=lv, label=LBL.get(lv, str(lv)), date=today); ch += 1
    rep["travel"] = {"rows": rows, "updatedAt": A.iso(A.now()), "source": "travel.state.gov, travel.gc.ca (pārbauda GitHub Actions)"}
    A.log(f"ceļošanas brīdinājumi: no advisories.json, izmaiņas {ch}")


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
        when = riga.strftime('%d.%m.%Y %H:%M')
        sp = (f"Tagad {when} (Rīgas laiks). Izmanto Google meklēšanu un atrodi jaunākās ziņas (pēdējās 24–48 h). {task}\n"
              f"Atbildi ar faktu sarakstu latviski: katram faktam datums, īss apraksts, izdevums un pilna raksta saite (URL). Neizdomā neko.")
        mp = (f"Tagad {when} (Rīgas laiks). Tu gatavo {kind.lower()} pārskatu Latvijas iedzīvotājam \"Vai palikt Latvijā?\" — daļa: {name}.\n"
              f"Uzdevums: {task}\n\nSvaigi fakti no Google meklēšanas (izmanto tikai tos un iepriekšējo variantu):\n<<FAKTI>>\n\n{RULES}\n\n"
              f"Iepriekšējais variants ({prev.get('generatedAt')}):\n```json\n{json.dumps(part_prev, ensure_ascii=False)}\n```")
        try:
            j, m, doms = ask(sp, mp, key)
        except Exception as e:
            A.log(f"{name}: kļūda — {e}; paturu iepriekšējo"); continue
        if not doms or not isinstance(j, dict) or not all(k in j for k in keys):
            A.log(f"{name}: nav derīgas atbildes ar meklēšanu ({'avoti ' + str(len(doms)) if doms else 'nemeklēja'}); paturu iepriekšējo")
            continue
        ok = lambda u: str(u) in prev_urls or ((lambda h: bool(h) and any(h == d or h.endswith("." + d) or d.endswith("." + h) for d in doms))(host(u)) and alive(str(u)))
        stat = {"drop": 0}
        j = scrub({k: j[k] for k in keys}, ok, stat)
        fix_levels(j)
        if "sections" in j:  # sadaļas paliek tās pašas (lapa tās rāda pēc key); trūkstošās — no iepriekšējā
            got = {x.get("key"): x for x in j["sections"] if isinstance(x, dict)}
            j["sections"] = [dict(got[x["key"]], key=x["key"], title=x.get("title")) if x.get("key") in got and got[x["key"]].get("items") else x
                             for x in prev.get("sections") or []]
        if "level" in j and j["level"] not in LEVELS: j["level"] = prev.get("level", "yellow")
        rep.update(j)
        used.append(m)
        A.log(f"{name}: atjaunots ({m}, avoti {len(doms)}, izmesti nepārbaudāmi ieraksti: {stat['drop']})")
    if not used:
        A.log("neviena daļa netika atjaunota — jaunu pārskatu nesaglabāju")
        LOGF.write_text("\n".join(A.log_lines) + "\n", encoding="utf-8"); return
    travel_from_advisories(rep, prev, riga)
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
