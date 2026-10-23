"""Robežas sarga ziņu daļas ar Google Gemini (aizstāj Claude ieplānotos uzdevumus).

  python gemini_rs.py dip      # vēstniecību ziņas → data/rs/diplomacy_events.json  (no out/news_recent.json, bez meklēšanas)
  python gemini_rs.py inv      # investīciju ziņas → data/rs/investment/news.json     (no out/news_recent.json, bez meklēšanas)
  python gemini_rs.py transit  # tranzīts → data/rs/transit/current.json (Gemini ar Google meklēšanu, tikai esošo maršrutu atjaunošana)
Pirms tam: python export_db.py (izveido out/news_recent.json).
Katru Gemini ierakstu pārbauda: saitei jābūt no dotā ziņu saraksta vai no Gemini meklēšanas avotiem; lauku vērtībām — no atļautajām.
"""
import json, re, sys, datetime as dt
from pathlib import Path

import air_alerts as A          # Gemini izsaukums ar meklēšanu, JSON izvilkšana
import air_alerts_fast as F     # Gemini izsaukums bez meklēšanas

ROOT = Path(__file__).parent
RS, OUT = ROOT / "data" / "rs", ROOT / "out"
LOGF = RS / "gemini_rs.log"
LEVELS = {"green", "yellow", "red"}


def load(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return d


def save(p, o, compact=False):
    p.write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")


def key():
    import os
    return os.environ.get("GEMINI_API_KEY", "").strip()


def news(tags_pred):
    return [n for n in load(OUT / "news_recent.json", []) if tags_pred(n.get("tag") or "")]


# ------------------------------------------------------------------ vēstniecības
def dip():
    items = news(lambda t: not t.startswith("inv"))
    events = load(RS / "diplomacy_events.json", [])
    have = {e.get("_id") for e in events}
    todo = [n for n in items if "n-" + n["id"] not in have][:60]
    A.log(f"dip: ziņas {len(items)}, jaunas {len(todo)}")
    if not todo:
        return
    lines = "\n".join(f"- id={n['id']} [{n.get('published') or '?'}] ({n.get('source')}) {n['title']}  URL: {n.get('url')}" for n in todo)
    prompt = f"""Tu atlasi ziņas Latvijas drošības lapas sadaļai "Vēstniecības un diplomāti". No zemāk esošajiem virsrakstiem atlasi TIKAI reālus
diplomātiskās klātbūtnes vai vēstniecību drošības notikumus, kas skar Latviju, Igauniju, Lietuvu, Poliju, Somiju, Zviedriju, Norvēģiju vai
Krieviju/Baltkrieviju: diplomātu izraidīšana (persona non grata), vēstniecības/konsulāta slēgšana vai darbības apturēšana, atvēršana no jauna,
vēstnieka atsaukšana vai iecelšana, pāreja uz lietvedi, personāla samazināšana, ģimeņu/personāla evakuācija, aicinājums pilsoņiem izbraukt,
uzbrukums vēstniecībai, ceļošanas brīdinājuma maiņa. Ignorē citus reģionus (Tuvie Austrumi, Āzija), ja vien nav par Krievijas/Baltkrievijas
vēstniecībām mūsu 7 valstīs vai mūsu valstu vēstniecībām Krievijā/Baltkrievijā. Ignorē ikdienišķus paziņojumus (svētki, vīzas, pasākumi).

Ziņas:
{lines}

Līmeņi: red = masveida izraidīšana, NATO valsts vēstniecības slēgšana/evakuācija mūsu reģionā, aicinājums pilsoņiem pamest kādu no 7 valstīm,
"ordered/authorized departure"; yellow = atsevišķa izraidīšana, vēstnieka atsaukšana, konsulāta slēgšana, personāla samazinājums, uzbrukums vēstniecībai;
green = rotācija, jauna vēstnieka akreditācija.
Atbildi TIKAI ar JSON: ```json {{"events": [{{"id": "ziņas id no saraksta", "date": "YYYY-MM-DD", "host": "LV|EE|LT|PL|FI|SE|NO|MOSCOW|MINSK",
"sender": "valsts ISO kods, piem. RU, US", "kind": "expel|close|reopen|recall|appoint|charge|staff|evacuate|leave|attack|advisory|other",
"text": "1 teikums latviski", "level": "green|yellow|red", "source": "izdevums"}}]}} ``` Ja nekā derīga: {{"events": []}}"""
    txt, m = F.call_plain(prompt, key())
    j = A.extract_json(txt) or {}
    by = {n["id"]: n for n in todo}
    add = 0
    for e in j.get("events") or []:
        n = by.get(str(e.get("id")))
        if not n or e.get("level") not in LEVELS or e.get("host") not in {"LV", "EE", "LT", "PL", "FI", "SE", "NO", "MOSCOW", "MINSK"}:
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(e.get("date") or "")):
            e["date"] = (n.get("published") or "")[:10] or A.now().strftime("%Y-%m-%d")
        events.append({"_id": "n-" + n["id"], "date": e["date"], "host": e["host"], "sender": str(e.get("sender") or "")[:6].upper(),
                       "kind": str(e.get("kind") or "other")[:20], "text": str(e.get("text") or n["title"])[:240], "level": e["level"],
                       "source": str(e.get("source") or n.get("source") or "")[:60], "url": n.get("url"), "auto": False, "via": "gemini"})
        add += 1
    events.sort(key=lambda e: str(e.get("date") or ""), reverse=True)
    save(RS / "diplomacy_events.json", events[:150], compact=True)
    A.log(f"dip: pievienoti {add} notikumi ({m})")


# ------------------------------------------------------------------ investīcijas
def inv():
    items = news(lambda t: t.startswith("inv"))
    doc = load(RS / "investment" / "news.json", {"items": []})
    have = {i.get("url") for i in doc.get("items") or []}
    todo = [n for n in items if n.get("url") not in have][:50]
    A.log(f"inv: ziņas {len(items)}, jaunas {len(todo)}")
    if not todo:
        return
    lines = "\n".join(f"- id={n['id']} [{n.get('published') or '?'}] ({n.get('source')}) {n['title']}  URL: {n.get('url')}" for n in todo)
    prompt = f"""No zemāk esošajiem virsrakstiem atlasi ziņas par ārvalstu investīcijām Latvijā, Lietuvā, Igaunijā, Polijā, Somijā, Zviedrijā, Norvēģijā:
lielas jaunas investīcijas (≥ ~20 milj. EUR vai ≥100 darba vietu), ārvalstu uzņēmumu aiziešana/projektu apturēšana (īpaši drošības dēļ),
reitingu izmaiņas ar ģeopolitisku pamatojumu un ĀTI apjoma kritums (centrālās bankas, statistika). Ignorē pārējo.
Ziņas:
{lines}
Atbildi TIKAI ar JSON: ```json {{"items": [{{"id": "ziņas id", "date": "DD.MM.YY", "c": "valsts latviski", "kind": "in|out|drop|other",
"level": "green|yellow|red", "text": "1 teikums latviski (kas, cik, kur)", "source": "izdevums"}}]}} ```
Līmeņi: green = jauna investīcija; yellow = kritums, aiziešana, reitinga pazemināšana; red = vairāki lieli investori aiziet drošības dēļ vai ≥50 % kritums drošības dēļ."""
    txt, m = F.call_plain(prompt, key())
    j = A.extract_json(txt) or {}
    by = {n["id"]: n for n in todo}
    new = []
    for it in j.get("items") or []:
        n = by.get(str(it.get("id")))
        if not n or it.get("level") not in LEVELS or it.get("kind") not in {"in", "out", "drop", "other"}:
            continue
        new.append({"date": str(it.get("date") or "")[:8], "c": str(it.get("c") or "")[:20], "kind": it["kind"], "level": it["level"],
                    "text": str(it.get("text") or n["title"])[:240], "source": str(it.get("source") or n.get("source") or "")[:60], "url": n.get("url")})
    doc["items"] = (new + (doc.get("items") or []))[:40]
    doc["updatedAt"] = A.iso(A.now())
    save(RS / "investment" / "news.json", doc)
    A.log(f"inv: pievienotas {len(new)} ziņas ({m})")


# ------------------------------------------------------------------ tranzīts
def transit():
    doc = load(RS / "transit" / "current.json", None)
    if not doc or not doc.get("routes"):
        A.log("transit: nav bāzes dokumenta"); return
    t_now = A.now()
    brief = [{k: r.get(k) for k in ("key", "name", "status", "level", "value", "trend", "date")} for r in doc["routes"]]
    prompt = f"""Tagad {A.iso(t_now)}. OBLIGĀTI izmanto Google meklēšanu (vairākus vaicājumus, arī krieviski, lietuviski, latviski, poliski, somiski)
un atrodi JAUNUMUS pēdējās 7 dienās par Krievijas un Baltkrievijas kravu tranzītu caur Latviju, Lietuvu (Kaļiņingradas tranzīts),
Igauniju, Poliju, Somiju, Norvēģiju un Baltijas jūru (ēnu flote, naftas eksports caur Primorsku/Ustjlugu), robežpāreju slēgšanu vai ierobežojumus.
Esošie maršruti: {json.dumps(brief, ensure_ascii=False)}
Atjauno TIKAI tos maršrutus, par kuriem atradi jaunu informāciju ar avotu. Neizdomā skaitļus.
Atbildi TIKAI ar JSON: ```json {{"updates": [{{"key": "esošā maršruta key", "status": "open|restricted|closed|unknown", "level": "green|yellow|red",
"value": "īss skaitlis vai stāvoklis", "trend": "up|down|flat|", "text": "1–2 teikumi latviski", "source": "izdevums", "url": "raksta saite",
"date": "DD.MM.YYYY"}}], "events": [{{"date": "DD.MM.YY", "level": "green|yellow|red", "text": "1 teikums latviski", "source": "izdevums", "url": "saite"}}],
"headline": "1 teikums par svarīgāko (vai tukšs, ja nav jaunumu)"}} ```"""
    txt, m, nq, doms = A.call_gemini(prompt, key())
    j = A.extract_json(txt) or {}
    if not doms:
        A.log(f"transit: Gemini nemeklēja (0 avotu) — nekas netiek mainīts"); return
    def okurl(u):
        h = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*", r"\1", str(u or "")).lower())
        return bool(h) and any(h == d or h.endswith("." + d) or d.endswith("." + h) for d in doms)
    keys = {r["key"]: r for r in doc["routes"]}
    nu = 0
    for u in j.get("updates") or []:
        r = keys.get(u.get("key"))
        if not r or not okurl(u.get("url")) or u.get("level") not in LEVELS:
            continue
        for f in ("status", "level", "value", "trend", "text", "source", "url", "date"):
            if u.get(f) not in (None, ""):
                r[f] = str(u[f])[:300]
        nu += 1
    ne = [dict(e, text=str(e.get("text"))[:240]) for e in (j.get("events") or []) if okurl(e.get("url")) and e.get("level") in LEVELS]
    doc["events"] = (ne + (doc.get("events") or []))[:30]
    if nu or ne:
        if j.get("headline"): doc["headline"] = str(j["headline"])[:240]
        rank = {"green": 1, "yellow": 2, "red": 3}
        doc["level"] = max((r.get("level") for r in doc["routes"]), key=lambda x: rank.get(x, 0))
    doc["updatedAt"] = A.iso(t_now)
    save(RS / "transit" / "current.json", doc)
    A.log(f"transit: atjaunoti {nu} maršruti, {len(ne)} notikumi ({m}, meklējumi {nq}, avoti {len(doms)})")


if __name__ == "__main__":
    if not key():
        A.log("GEMINI_API_KEY nav"); sys.exit(0)
    for part in sys.argv[1:] or ["dip", "inv"]:
        try:
            {"dip": dip, "inv": inv, "transit": transit}[part]()
        except Exception as e:
            A.log(f"{part}: kļūda — {e}")
    LOGF.write_text("\n".join(A.log_lines) + "\n", encoding="utf-8")
