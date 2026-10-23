"""Ātrā gaisa trauksmju pārbaude (ik ~10 min), gandrīz bez izmaksām.

1. Nolasa ziņu plūsmas (Google News RSS meklējumi katrā valodā + dažas tiešās plūsmas) — bez maksas.
2. Atlasa tikai JAUNAS ziņas ar trauksmju atslēgvārdiem (piem. "gaisa telpas apdraudējums", "oro pavojus", "Alert RCB",
   "беспилотная опасность") no pēdējām 12 h.
3. Tikai ja tādas ir — Gemini (bez Google meklēšanas, tāpēc lēti/bez maksas) no virsrakstiem izvelk trauksmes.
4. Rezultātu pārbauda un apvieno ar data/airalerts/current.json tāpat kā stundas pārbaude (air_alerts.py).

Palaist: python air_alerts_fast.py [--test]
"""
import hashlib, json, os, re, sys, datetime as dt
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

import air_alerts as A

SEEN = os.path.join(A.OUT_DIR, "fast_seen.json")
FLOG = os.path.join(A.OUT_DIR, "fast_run.log")
UA = {"User-Agent": "Mozilla/5.0 (robezas-sargs; +https://github.com/Toms0078/robezas-sargs-dati2)"}
GN = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{lang}"

QUERIES = [  # (birka, vaicājums, (hl, gl, lang))
    ("lv", '("gaisa telpas apdraudējums" OR "gaisa trauksme" OR "šūnu apraide" OR "gaisa telpas apdraudējumu") when:1d', ("lv", "LV", "lv")),
    ("lt", '("oro pavojus" OR "oro pavojaus" OR "oro pavojų" OR "perspėjimas gyventojams" dronas) when:1d', ("lt", "LT", "lt")),
    ("ee", '(õhuohu OR drooniohu OR "õhuohu hoiatus" OR "ohuteavitus") when:1d', ("et", "EE", "et")),
    ("pl", '("Alert RCB" OR "alarm powietrzny" OR "zagrożenie z powietrza" OR "zagrożenie atakiem z powietrza") when:1d', ("pl", "PL", "pl")),
    ("fi", '(ilmahälytys OR ilmauhka OR "vaaratiedote" drooni) when:1d', ("fi", "FI", "fi")),
    ("ru", '("беспилотная опасность" OR "ракетная опасность" OR "отбой беспилотной" OR "беспилотной опасности") '
           '(Псков OR Ленинград OR Петербург OR Новгород OR Смоленск OR Калининград OR Карели OR Мурманск OR Твер OR Брянск) when:1d',
     ("ru", "RU", "ru")),
    ("en", '("air alert" OR "air raid alert" OR "drone threat" OR "airspace threat") (Latvia OR Lithuania OR Estonia OR Poland OR Finland) when:1d',
     ("en", "US", "en")),
]
DIRECT = [  # tiešās plūsmas (ja kāda nestrādā — logā redzams, pārējās turpina)
    ("err_en", "https://news.err.ee/rss"),
    ("lsm_lv", "https://www.lsm.lv/rss/?lang=lv&catid=20"),
    ("lrt_en", "https://www.lrt.lt/en/news-in-english?rss"),
]
KEY = re.compile(
    r"gaisa telpas apdraud|gaisa trauksm|šūnu apraid|oro pavoj|perspėj|õhuoh|drooniohu|ohuteav|alert rcb|alarm powietrzn|"
    r"zagrożeni\w* (atakiem )?z powietrza|ilmahälyt|ilmauhk|беспилотн\w* опасн|ракетн\w* опасн|отбой|air (raid )?alert|"
    r"drone threat|airspace threat|air threat", re.I)
END_WORDS = re.compile(r"beidzies|beidzās|atcelt|atšaukt|baig|lõpp|odwołan|отбой|отмен|ended|lifted|over\b", re.I)

def fetch(url):
    r = requests.get(url, headers=UA, timeout=40)
    r.raise_for_status()
    return BeautifulSoup(r.content, "xml")

def pubtime(it):
    p = it.find(["pubDate", "published", "updated"])
    t = p.get_text(strip=True) if p else ""
    try:
        d = parsedate_to_datetime(t) if "," in t else dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
        return d.astimezone(dt.timezone.utc)
    except Exception:
        return None

def collect(t_now, test=False):
    items, errors, counts = [], [], {}
    srcs = [(tag, GN.format(q=quote_plus(q), hl=hl, gl=gl, lang=lang)) for tag, q, (hl, gl, lang) in QUERIES] + DIRECT
    for tag, url in srcs:
        try:
            soup = fetch(url)
        except Exception as e:
            errors.append(f"{tag}: {str(e)[:120]}"); continue
        rows = soup.find_all(["item", "entry"]); counts[tag] = len(rows)
        for it in rows:
            title = it.title.get_text(" ", strip=True) if it.title else ""
            summ = it.find(["description", "summary"])
            text = title + " " + (BeautifulSoup(summ.get_text(" ", strip=True), "lxml").get_text(" ", strip=True)[:300] if summ else "")
            if not KEY.search(text):
                continue
            pt = pubtime(it)
            if pt and t_now - pt > dt.timedelta(hours=12):
                continue
            le = it.find("link")
            link = (le.get("href") or le.get_text(strip=True)) if le else ""
            src = it.find("source")
            items.append({"id": hashlib.sha1((link or title).encode()).hexdigest()[:16], "tag": tag, "title": title[:300],
                          "text": text[:500], "url": link, "source": src.get_text(strip=True) if src else tag,
                          "published": A.iso(pt) if pt else None})
    A.log(f"plūsmas: {counts}" + (f"; kļūdas: {errors}" if errors else ""))
    return items

def prompt(news, cur, t_now):
    riga = (t_now + dt.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    recent = [{k: a.get(k) for k in ("id", "cc", "status", "start", "end", "areas", "title")} for a in cur
              if (A.parse_t(a.get("start")) or t_now) > t_now - dt.timedelta(hours=24)]
    lines = "\n".join(f"- [{n['published'] or '?'}] ({n['source']}) {n['text']}  URL: {n['url']}" for n in news)
    return f"""Tu esi datu vācējs Latvijas drošības informācijas lapai. Tagad {riga} Rīgas laikā ({A.iso(t_now)} UTC).
Zemāk ir JAUNAS ziņas (virsraksti) par gaisa trauksmēm. No tām izvelc OFICIĀLI izsludinātas gaisa trauksmes / iedzīvotāju brīdinājumus
(LV, EE, LT, PL, FI) un Krievijas apgabalu "беспилотная/ракетная опасность" režīmus, kā arī ziņas, ka trauksme BEIGUSIES.
Ignorē: testus, vispārīgas ziņas, analīzi, notikumus Ukrainā, vecas trauksmes (ja ziņā skaidri cits datums).

Pēdējo 24 h zināmās trauksmes (ja ziņa ir par tām pašām — atkārto to "id"; ja ziņa saka, ka beigusies — status "ended" ar "end"):
{json.dumps(recent, ensure_ascii=False)}

Ziņas:
{lines}

Teritoriju kodi (TIKAI šie, izvēlies precīzākos, kas minēti ziņā):
- visa valsts: LV, EE, LT, PL, FI
- LV-: {A.code_list('LV-')}
- EE-: {A.code_list('EE-')}
- LT-: {A.code_list('LT-')}
- FI-: {A.code_list('FI-')}
- PL vojevodiste: {", ".join("PL-" + v for v in A.PL_VOIV)}; PL apriņķis "PL-<vojevodiste>-<powiat īpašības vārds bez diakritikas>", piem. PL-podkarpackie-sanocki, pilsēta PL-lubelskie-zamosc
- Krievija: {", ".join(k for k in A.CODES if k.startswith("RU-"))}

Atbildi TIKAI ar JSON:
```json
{{"alerts": [{{"id": "esošais id vai jauns (piem. lv-2026-10-23-0917)", "cc": "LV|EE|LT|PL|FI|RU", "kind": "air|missile|debris|warning",
"level": "red|yellow", "status": "active|ended", "start": "ISO UTC", "end": "ISO UTC vai null", "areas": ["kodi"],
"channel": "cb|app|siren|sms|official", "title": "1 teikums latviski", "text": "ko lika darīt, ja zināms",
"source": "izdevums", "url": "ziņas URL no saraksta"}}]}}
```
Laiks: ja ziņā minēts pulksteņa laiks — pārvērš uz UTC (LV/LT/EE/FI tagad UTC+3 vasarā / UTC+2 ziemā; PL UTC+2/+1; Krievija UTC+3);
ja nav — izmanto ziņas publicēšanas laiku. Neizdomā. Ja nekā derīga: {{"alerts": []}}"""

def call_plain(text, key):
    """Gemini without Google Search (cheap/free)."""
    last = None
    for m in A.MODELS:
        body = {"contents": [{"role": "user", "parts": [{"text": text}]}], "generationConfig": {"temperature": 0.1}}
        for attempt in range(2):
            try:
                r = requests.post(A.API.format(m=m), params={"key": key}, json=body, timeout=120)
            except requests.RequestException as e:
                last = f"{m}: {e}"; continue
            if r.status_code == 404: last = f"{m}: 404"; break
            if r.status_code in (429, 500, 503): last = f"{m}: HTTP {r.status_code}"; import time; time.sleep(15); continue
            if r.status_code != 200: last = f"{m}: HTTP {r.status_code} {r.text[:200]}"; break
            j = r.json(); u = j.get("usageMetadata", {})
            A.log(f"  modelis {m}: {u.get('promptTokenCount')} + {u.get('candidatesTokenCount')} tokeni")
            return "".join(p.get("text", "") for p in (((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])), m
    raise RuntimeError(last or "Gemini neatbild")

def main():
    test = "--test" in sys.argv
    t_now = A.now()
    A.log(f"{A.iso(t_now)} ātrā pārbaude")
    try:
        seen = json.load(open(SEEN, encoding="utf-8"))
    except Exception:
        seen = {}
    cutoff = A.iso(t_now - dt.timedelta(days=3))
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    items = collect(t_now, test)
    new = [n for n in items if n["id"] not in seen]
    uniq = {}
    for n in new:  # one Google News story often appears under several queries
        uniq.setdefault(n["title"].lower()[:120], n)
    new = list(uniq.values())
    A.log(f"atbilstošas ziņas: {len(items)}, jaunas: {len(new)}")
    if test:
        for n in new[:30]: A.log(f"  + [{n['tag']}] {n['title'][:160]}")
    try:
        doc = json.load(open(A.CUR, encoding="utf-8"))
    except Exception:
        doc = {"alerts": []}
    changed = False
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if new and key:
        try:
            txt, model = call_plain(prompt(new[:40], doc.get("alerts") or [], t_now), key)
            if test: A.log("---- atbilde ----\n" + txt[:4000] + "\n-----------------")
            j = A.extract_json(txt) or {}
            got = []
            for a in j.get("alerts") or []:
                region = "ru" if str(a.get("cc", "")).upper() == "RU" else "ours"
                c = A.clean(a, region, t_now)
                if c: c["via"] = "gemini-fast"; got.append(c)
            A.log(f"Gemini: {len(got)} derīgi ieraksti")
            before = json.dumps(doc.get("alerts"), sort_keys=True)
            doc["alerts"] = A.merge(doc.get("alerts") or [], got, t_now)
            changed = json.dumps(doc["alerts"], sort_keys=True) != before
            for n in new: seen[n["id"]] = A.iso(t_now)
        except Exception as e:
            A.log(f"Gemini kļūda: {e} — ziņas paliek neapstrādātas līdz nākamajai reizei")
    elif new:
        A.log("GEMINI_API_KEY nav — ziņas neapstrādātas")
    else:
        # still age out stale actives
        before = json.dumps(doc.get("alerts"), sort_keys=True)
        doc["alerts"] = A.merge(doc.get("alerts") or [], [], t_now)
        changed = json.dumps(doc["alerts"], sort_keys=True) != before
    last_fast = A.parse_t(doc.get("fastCheckedAt"))
    doc["fastCheckedAt"] = A.iso(t_now)
    stale = not last_fast or t_now - last_fast > dt.timedelta(minutes=30)
    if changed or stale:  # avoid a commit every 10 min when nothing happens
        act = [a for a in doc["alerts"] if a.get("status") == "active"]
        ours = [a for a in act if a.get("cc") != "RU"]
        doc["checkedAt"] = A.iso(t_now)
        doc["updatedAt"] = A.iso(t_now) if changed else doc.get("updatedAt")
        doc["note"] = (f"Aktīvas trauksmes mūsu reģionā: {len(ours)}" if ours else "Mūsu reģionā aktīvu trauksmju nav") + \
                      (f"; Krievijā: {len(act) - len(ours)}." if len(act) > len(ours) else ".")
        json.dump(doc, open(A.CUR, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(seen, open(SEEN, "w", encoding="utf-8"))
        A.log("saglabāts" + (" (izmaiņas trauksmēs)" if changed else " (tikai pārbaudes laiks)"))
    else:
        json.dump(seen, open(SEEN, "w", encoding="utf-8"))
    open(FLOG, "w", encoding="utf-8").write("\n".join(A.log_lines) + "\n")

if __name__ == "__main__":
    main()
