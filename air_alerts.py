"""Gaisa trauksmes (LV, EE, LT, PL, FI) un Krievijas apgabalu dronu/raķešu briesmu režīmi.

Ziņas meklē un apkopo Google Gemini (lētākais Flash-Lite modelis ar Google meklēšanu).
Skripts pats pārbauda katru ierakstu: teritoriju kodus, laikus, avota saiti. Ko nevar pārbaudīt — izmet.

Rezultāts: data/airalerts/current.json (to nolasa Robežas sargs), logs data/airalerts/last_run.log.

Vides mainīgie:
  GEMINI_API_KEY  — obligāts (GitHub Secrets). Bez tā skripts neko nedara.
  GEMINI_MODEL    — neobligāts; noklusējums un rezerves modeļi zemāk.

Palaist: python air_alerts.py           # parastā pārbaude
         python air_alerts.py --test    # izdrukā Gemini neapstrādāto atbildi logā
"""
import json, os, re, sys, time, datetime as dt
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data", "airalerts")
CUR = os.path.join(OUT_DIR, "current.json")
LOG = os.path.join(OUT_DIR, "last_run.log")
CODES = json.load(open(os.path.join(OUT_DIR, "codes.json"), encoding="utf-8"))

MODELS = [m for m in [os.environ.get("GEMINI_MODEL", "").strip()] if m] + [
    "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
API = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
OURS = {"LV", "EE", "LT", "PL", "FI"}
KINDS = {"air", "missile", "debris", "warning", "test"}
CHANNELS = {"cb", "app", "siren", "sms", "official"}
KEEP_DAYS = 7
MAX_OURS, MAX_RU = 40, 30

log_lines = []
def log(*a):
    s = " ".join(str(x) for x in a)
    print(s); log_lines.append(s)

def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)

def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else None

def parse_t(s):
    if not s or not isinstance(s, str):
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return t.astimezone(dt.timezone.utc) if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None

def code_list(prefix):
    return ", ".join(k[len(prefix):] for k in CODES if k.startswith(prefix))

def prompt(region, prev_active, t_now):
    riga = (t_now + dt.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    prev = json.dumps([{k: a.get(k) for k in ("id", "cc", "start", "areas", "title")} for a in prev_active], ensure_ascii=False)
    if region == "ours":
        scope = """Latvija, Igaunija, Lietuva, Polija, Somija — oficiāli izsludinātas gaisa trauksmes un iedzīvotājiem izsūtīti brīdinājumi
(šūnu apraide, Alert RCB, lietotnes, sirēnas) par droniem, raķetēm vai gaisa telpas apdraudējumu.
Meklē: Latvija — "gaisa telpas apdraudējums" (LSM, NBS, Delfi, TVNET); Igaunija — "õhuohu hoiatus", "drooniohu" (ERR);
Lietuva — "oro pavojus" (LRT, BNS); Polija — "Alert RCB zagrożenie z powietrza", "odwołano" (gov.pl/web/rcb, RMF24, Polsat News)
ar PRECĪZU apriņķu (powiat) sarakstu; Somija — "ilmahälytys", "vaaratiedote" (Yle).
NEiekļauj: testus, laikapstākļu brīdinājumus, trauksmes Ukrainā vai Krievijā."""
        codes = f"""Kodi (tikai šie):
- visa valsts: LV, EE, LT, PL, FI
- LV-: {code_list('LV-')}
- EE-: {code_list('EE-')}
- LT-: {code_list('LT-')}
- FI-: {code_list('FI-')}
- PL- visa vojevodiste: PL-dolnoslaskie, PL-kujawsko-pomorskie, PL-lodzkie, PL-lubelskie, PL-lubuskie, PL-malopolskie, PL-mazowieckie, PL-opolskie, PL-podkarpackie, PL-podlaskie, PL-pomorskie, PL-slaskie, PL-swietokrzyskie, PL-warminsko-mazurskie, PL-wielkopolskie, PL-zachodniopomorskie
- PL apriņķis: "PL-<vojevodiste>-<powiat bez vārda powiat, mazie burti, bez diakritikas, defises>", piem. PL-podkarpackie-sanocki, PL-lubelskie-zamosc (pilsēta), PL-lubelskie-zamojski (apriņķis)."""
    else:
        scope = """Krievijas rietumu apgabali — gubernatoru vai RSČS izsludināti režīmi "беспилотная опасность" un "ракетная опасность" un to atcelšana ("отбой").
Meklē krieviski: "беспилотная опасность" + Псковская, Ленинградская, Санкт-Петербург, Новгородская, Смоленская, Калининградская, Карелия, Мурманская, Тверская, Брянская;
kopsavilkumi "беспилотная опасность список регионов". Avoti: informpskov.ru, pln-pskov.ru, fontanka.ru, 47news.ru, RIA, TASS, Interfax, AiF.
Ja paziņots tikai rajonam — liec visu apgabalu."""
        codes = "Kodi (tikai šie): " + ", ".join(k for k in CODES if k.startswith("RU-"))
    cc_set = "LV|EE|LT|PL|FI" if region == "ours" else "RU"
    return f"""Tu esi datu vācējs Latvijas drošības informācijas lapai. Tagad ir {riga} pēc Rīgas laika ({iso(t_now)} UTC).
Atrodi ar Google meklēšanu trauksmes, kas bija AKTĪVAS pēdējo 6 stundu laikā vai SĀKĀS pēdējās 24 stundās:
{scope}

Iepriekš zināmās aktīvās trauksmes (pārbaudi, vai tās beigušās): {prev}

{codes}

Atbildi TIKAI ar JSON (bez paskaidrojumiem) šādā formā:
```json
{{"alerts": [{{"id": "iepriekšējais id vai jauns, piem. lv-2026-10-22-0917", "cc": "{cc_set}", "kind": "air|missile|debris|warning", "level": "red|yellow",
"status": "active|ended", "start": "ISO UTC", "end": "ISO UTC vai null", "areas": ["kodi"],
"channel": "cb|app|siren|sms|official", "title": "1 teikums latviski", "text": "ko lika darīt iedzīvotājiem, latviski, ja zināms",
"source": "izdevums", "url": "tiešā raksta saite"}}]}}
```
Noteikumi: neizdomā neko — tikai tas, kas atrodams avotos ar saiti. Laikus pārvērš uz UTC (LV/LT/EE/FI oktobrī–martā UTC+2, vasarā UTC+3; PL UTC+1/+2; Krievija UTC+3, Kaļiņingrada UTC+2).
"level": "red", ja aicina patverties vai apdraudējums apstiprināts; citādi "yellow". Ja nekas nav atrasts: {{"alerts": []}}"""

def call_gemini(text, key, test=False):
    last_err = None
    for m in MODELS:
        body = {"contents": [{"role": "user", "parts": [{"text": text}]}],
                "tools": [{"google_search": {}}],
                "generationConfig": {"temperature": 0.1}}
        for attempt in range(2):
            try:
                r = requests.post(API.format(m=m), params={"key": key}, json=body, timeout=180)
            except requests.RequestException as e:
                last_err = f"{m}: {e}"; time.sleep(5); continue
            if r.status_code == 404:
                last_err = f"{m}: nav pieejams (404)"; break
            if r.status_code in (429, 500, 503):
                last_err = f"{m}: HTTP {r.status_code}"
                if attempt == 0: log(f"  {m}: HTTP {r.status_code} — {r.text[:700]}")
                time.sleep(20); continue
            if r.status_code != 200:
                last_err = f"{m}: HTTP {r.status_code} {r.text[:300]}"; break
            j = r.json()
            parts = (((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
            out = "".join(p.get("text", "") for p in parts)
            usage = j.get("usageMetadata", {})
            log(f"  modelis {m}: {usage.get('promptTokenCount')} + {usage.get('candidatesTokenCount')} tokeni")
            if test:
                log("---- atbilde ----"); log(out[:6000]); log("-----------------")
            return out, m
        log(f"  {last_err}")
    raise RuntimeError(last_err or "Gemini nav atbildējis")

def extract_json(s):
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.S)
    raw = m.group(1) if m else s[s.find("{"): s.rfind("}") + 1]
    try:
        return json.loads(raw)
    except Exception:
        return None

def clean(a, region, t_now):
    """Return a validated alert dict or None, with the reason logged."""
    if not isinstance(a, dict):
        return None
    cc = str(a.get("cc", "")).upper()
    if region == "ours" and cc not in OURS: return None
    if region == "ru": cc = "RU"
    areas = [x for x in (a.get("areas") or []) if isinstance(x, str) and x in CODES and (x.startswith(cc) or x == cc)]
    bad = [x for x in (a.get("areas") or []) if x not in areas]
    if bad: log(f"  izmesti nezināmi kodi: {bad}")
    if not areas:
        log(f"  izmests ieraksts bez derīgām teritorijām: {a.get('title')}"); return None
    url = a.get("url") if isinstance(a.get("url"), str) and re.match(r"https?://", a.get("url") or "") else None
    if not url:
        log(f"  izmests ieraksts bez avota saites: {a.get('title')}"); return None
    start, end = parse_t(a.get("start")), parse_t(a.get("end"))
    if start and start > t_now + dt.timedelta(minutes=30):
        log(f"  izmests ieraksts ar nākotnes laiku: {a.get('title')}"); return None
    if start and start < t_now - dt.timedelta(days=KEEP_DAYS): return None
    status = a.get("status") if a.get("status") in ("active", "ended") else ("ended" if end else "active")
    if status == "active" and end and end <= t_now: status = "ended"
    out = {"id": str(a.get("id") or "")[:60] or f"{cc.lower()}-{(start or t_now).strftime('%Y-%m-%d-%H%M')}",
           "cc": cc, "kind": a.get("kind") if a.get("kind") in KINDS else "air",
           "level": a.get("level") if a.get("level") in ("red", "yellow") else "yellow",
           "status": status, "start": iso(start), "end": iso(end) if status == "ended" else None,
           "areas": areas, "channel": a.get("channel") if a.get("channel") in CHANNELS else "official",
           "title": str(a.get("title") or "")[:240], "text": str(a.get("text") or "")[:300],
           "source": str(a.get("source") or "")[:80], "url": url, "via": "gemini"}
    if out["kind"] == "test": return None
    return out

def same(a, b):
    if a.get("id") and a.get("id") == b.get("id"): return True
    if a.get("cc") != b.get("cc"): return False
    ta, tb = parse_t(a.get("start")), parse_t(b.get("start"))
    if not ta or not tb or abs((ta - tb).total_seconds()) > 1800: return False
    return bool(set(a.get("areas") or []) & set(b.get("areas") or []))

def merge(old, new, t_now):
    res = [dict(x) for x in old]
    for n in new:
        hit = next((o for o in res if same(o, n)), None)
        if hit:
            for k, v in n.items():
                if v not in (None, "", []) and k != "id": hit[k] = v
            if n["status"] == "ended": hit["status"], hit["end"] = "ended", n.get("end") or hit.get("end")
            hit["areas"] = sorted(set(hit.get("areas") or []) | set(n["areas"]))
        else:
            res.append(n)
    for a in res:  # stale actives
        st = parse_t(a.get("start"))
        if a.get("status") == "active" and st and t_now - st > dt.timedelta(hours=6):
            a["status"], a["end"] = "ended", None
            if "(beigas nav paziņotas)" not in (a.get("title") or ""): a["title"] = (a.get("title") or "") + " (beigas nav paziņotas)"
    cutoff = t_now - dt.timedelta(days=KEEP_DAYS)
    res = [a for a in res if (parse_t(a.get("end")) or parse_t(a.get("start")) or t_now) >= cutoff]
    res.sort(key=lambda a: (a.get("status") != "active", -(parse_t(a.get("start")) or cutoff).timestamp()))
    ours = [a for a in res if a.get("cc") != "RU"][:MAX_OURS]
    ru = [a for a in res if a.get("cc") == "RU"][:MAX_RU]
    return ours + ru

def main():
    test = "--test" in sys.argv
    t_now = now()
    os.makedirs(OUT_DIR, exist_ok=True)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    log(f"{iso(t_now)} gaisa trauksmju pārbaude")
    if not key:
        log(f"  (secret GEMINI_API_KEY redzams: {os.environ.get('HAS_SECRET')}, variable: {os.environ.get('HAS_VAR')})")
        log("GEMINI_API_KEY nav iestatīts — neko nedaru. Pievieno to GitHub → Settings → Secrets and variables → Actions.")
        open(LOG, "w", encoding="utf-8").write("\n".join(log_lines) + "\n"); return
    try:
        doc = json.load(open(CUR, encoding="utf-8"))
    except Exception:
        doc = {"alerts": []}
    old = doc.get("alerts") or []
    found, ok = [], []
    for region in ("ours", "ru"):
        prev = [a for a in old if a.get("status") == "active" and ((a.get("cc") == "RU") == (region == "ru"))]
        try:
            txt, model = call_gemini(prompt(region, prev, t_now), key, test)
        except Exception as e:
            log(f"{region}: kļūda — {e}"); continue
        j = extract_json(txt)
        if j is None:
            log(f"{region}: atbildē nav derīga JSON"); continue
        items = [c for c in (clean(a, region, t_now) for a in (j.get("alerts") or [])) if c]
        log(f"{region}: {len(items)} derīgi ieraksti ({model})")
        found += items; ok.append(region)
    alerts = merge(old, found, t_now)
    act = [a for a in alerts if a["status"] == "active"]
    ours_act = [a for a in act if a["cc"] != "RU"]
    note = (f"Aktīvas trauksmes mūsu reģionā: {len(ours_act)}" if ours_act else "Mūsu reģionā aktīvu trauksmju nav") + \
           (f"; Krievijā: {len(act) - len(ours_act)}." if len(act) > len(ours_act) else ".")
    out = {"updatedAt": iso(t_now), "checkedAt": iso(t_now) if ok else doc.get("checkedAt"),
           "note": note, "source": "GitHub Actions + Gemini", "alerts": alerts}
    if ok:
        json.dump(out, open(CUR, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(note)
    open(LOG, "w", encoding="utf-8").write("\n".join(log_lines) + "\n")

if __name__ == "__main__":
    main()
