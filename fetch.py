"""Robežas sargs — diplomātiskā monitoringa datu vācējs.

Palaiž GitHub Actions ik stundu. Divas puses:
  1. Uzņēmējvalstu diplomātu saraksti (PDF) — lejupielādē jaunu versiju, kad tā parādās.
  2. Vēstniecību valstu ceļošanas brīdinājumi (US, UK, DE, CA) — fiksē stāvokli un izmaiņas.

Raksta:
  data/lists/<CC>/<datums>_<hash>.pdf   — oriģinālie saraksti (vēsture)
  data/lists/index.json                 — kuri saraksti ir lejupielādēti
  data/advisories.json                  — pašreizējais brīdinājumu stāvoklis
  data/changes.jsonl                    — katra izmaiņa vienā rindā (žurnāls)
  data/last_run.json                    — kas izdevās/neizdevās pēdējā palaišanā
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LISTS = DATA / "lists"
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,lv;q=0.8",
}

# Valstis, kas ir Robežas sargā (ISO kods → nosaukumi dažādos avotos)
WATCH = {
    "LV": {"uk": "latvia", "de": "LV", "name": "Latvia"},
    "LT": {"uk": "lithuania", "de": "LT", "name": "Lithuania"},
    "EE": {"uk": "estonia", "de": "EE", "name": "Estonia"},
    "PL": {"uk": "poland", "de": "PL", "name": "Poland"},
    "FI": {"uk": "finland", "de": "FI", "name": "Finland"},
    "SE": {"uk": "sweden", "de": "SE", "name": "Sweden"},
    "NO": {"uk": "norway", "de": "NO", "name": "Norway"},
    # Otrs virziens: vai Rietumi paliek Krievijā un Baltkrievijā
    "RU": {"uk": "russia", "de": "RU", "name": "Russia"},
    "BY": {"uk": "belarus", "de": "BY", "name": "Belarus"},
}

# Diplomātu sarakstu avoti. index = lapa, kurā meklēt jaunāko PDF saiti;
# seeds = zināmas tiešās saites (ja indeksa lapu neizdodas nolasīt).
LIST_SOURCES = {
    "LV": {
        "index": ["https://www.mfa.gov.lv/en/about-the-ministry/state-protocol",
                  "https://www.mfa.gov.lv/en/diplomatic-list"],
        "match": r"diplomatic\s*list",
        "seeds": ["https://www.mfa.gov.lv/en/media/23256/download"],
    },
    "EE": {
        "index": ["https://vm.ee/en/diplomatic-portal"],
        "match": r"diplomatic\s*list",
        "seeds": ["https://www.vm.ee/sites/default/files/documents/2026-04/The%20Tallinn%20Diplomatic%20List%20-%2023%20April%202026.pdf"],
    },
    "PL": {
        "index": ["https://www.gov.pl/web/diplomacy/diplomatic-protocol"],
        "match": r"list of diplomatic missions",
        "seeds": ["https://www.gov.pl/attachment/f5a342bb-0ef6-482b-b9ec-a3f57fbc8c75"],
    },
    "SE": {
        "index": ["https://government.se/government-of-sweden/ministry-for-foreign-affairs/diplomatic-portal/the-stockholm-diplomatic-list/"],
        "match": r"diplomatic\s*list|\.pdf",
        "seeds": [],
    },
    "NO": {
        "index": [],
        "match": r"oslo-diplomatic-list|missions-accredited",
        "seeds": ["https://www.regjeringen.no/contentassets/3818fa2f0ec449689f40fd6fbeb99df2/the-oslo-diplomatic-list-march-2026.pdf",
                  "https://www.regjeringen.no/contentassets/18034c600ad5476fb3b7434525620f25/all-missions-accredited-to-norway-24-june-2026.pdf"],
    },
}

run_log = {"run_at": NOW, "sources": {}}


def log(source, ok, **info):
    run_log["sources"][source] = {"ok": ok, **info}
    print(("OK  " if ok else "ERR ") + source, info, flush=True)


def get(url, polite=0, **kw):
    """GET ar atkārtojumu, ja serveris prasa palēnināt (429)."""
    import time
    for wait in (0, 10, 30, 60):
        if wait:
            time.sleep(wait)
        if polite:
            time.sleep(polite)
        r = requests.get(url, headers=UA, timeout=60, **kw)
        if r.status_code not in (429, 503):
            break
    r.raise_for_status()
    return r


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def record_change(kind, country, source, old, new, note=""):
    DATA.mkdir(exist_ok=True)
    with (DATA / "changes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": NOW, "kind": kind, "country": country, "source": source,
                            "old": old, "new": new, "note": note}, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 1. saraksti
def find_pdf_links(cc, cfg):
    links = []
    for page in cfg["index"]:
        try:
            soup = BeautifulSoup(get(page).text, "html.parser")
        except Exception as e:
            run_log["sources"].setdefault(f"list_index_{cc}", {"ok": False, "errors": []})["errors"].append(f"{page}: {e}")
            continue
        found_here, sample = 0, []
        for a in soup.find_all("a", href=True):
            text = " ".join(a.get_text(" ").split())
            href = urljoin(page, a["href"])
            hay = f"{text} {href}"
            if re.search(r"\.pdf|\.docx|download|documents|getfile|/attachment/", href, re.I):
                sample.append(f"{text[:60]} -> {href}")
                if re.search(cfg["match"], hay, re.I):
                    links.append(href)
                    found_here += 1
        if not found_here:  # atkļūdošanai: kādas dokumentu saites lapā vispār ir
            run_log["sources"].setdefault(f"list_index_{cc}", {"ok": False, "errors": []}).update(
                {"page": page, "page_bytes": len(soup.text), "doc_links_sample": sample[:15]})
    links += cfg["seeds"]
    # unikāli, saglabājot secību (indeksa lapas saites vispirms = jaunākās)
    return list(dict.fromkeys(links))


def fetch_lists():
    index = load_json(LISTS / "index.json", {})
    for cc, cfg in LIST_SOURCES.items():
        known = {e["sha256"] for e in index.get(cc, [])}
        tried, new_files, errors = 0, [], []
        for url in find_pdf_links(cc, cfg)[:6]:
            tried += 1
            try:
                r = get(url)
            except requests.HTTPError as e:
                resp = e.response
                errors.append(f"{url}: HTTP {resp.status_code} server={resp.headers.get('server')} "
                              f"cf={resp.headers.get('cf-ray')} body={resp.text[:120]!r}")
                continue
            except Exception as e:
                errors.append(f"{url}: {e}")
                continue
            body = r.content
            if body.startswith(b"%PDF"):
                ext = "pdf"
            elif body.startswith(b"PK") and "word" in r.headers.get("content-type", "") or url.lower().endswith(".docx"):
                ext = "docx"   # Latvija publicē sarakstu kā Word failu
            else:
                errors.append(f"{url}: nezināms formāts ({r.headers.get('content-type')})")
                continue
            h = hashlib.sha256(body).hexdigest()
            if h in known:
                continue
            fn = LISTS / cc / f"{NOW[:10]}_{h[:10]}.{ext}"
            fn.parent.mkdir(parents=True, exist_ok=True)
            fn.write_bytes(body)
            known.add(h)
            entry = {"file": str(fn.relative_to(ROOT)), "url": url, "sha256": h,
                     "bytes": len(body), "downloaded_at": NOW}
            index.setdefault(cc, []).append(entry)
            new_files.append(entry["file"])
            record_change("diplomatic_list_new", cc, url, None, entry["file"], "Jauna saraksta versija")
        log(f"list_{cc}", bool(new_files) or (tried > 0 and len(errors) < tried),
            tried=tried, new=new_files, errors=errors[:5])
    save_json(LISTS / "index.json", index)


FI_INDEX = "https://um.fi/representation-of-foreign-states-in-finland-or-in-the-nearest-country-to-finland"
FI_HONORIFIC = re.compile(r"^(H\.?E\.?\s+)?(Mr|Ms|Mrs|Miss|Dr|Prof|Col|Lt|Cdr|Capt|Maj|Brig|Gen|Rev|Msgr|Colonel|Commander|Captain)\b", re.I)


def fetch_fi():
    """Somija: katras vēstniecības lapā ir sadaļa "Personnel" (vārds, amats, vieta)."""
    errors = []
    try:
        soup = BeautifulSoup(get(FI_INDEX).text, "html.parser")
    except Exception as e:
        log("list_FI", False, errors=[f"{FI_INDEX}: {e}"])
        return
    links = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(FI_INDEX, a["href"])
        t = " ".join(a.get_text(" ").split())
        if "contactInfoOrganization/id/" in href and re.search(r"embassy|nunciature|delegation", t, re.I):
            links[href.split("?")[0]] = t
    missions = {}
    for href, title in links.items():
        try:
            page = BeautifulSoup(get(href, polite=2).text, "html.parser")
        except Exception as e:
            errors.append(f"{href}: {e}")
            continue
        main = page.find("main") or page
        lines = [l.strip() for l in main.get_text("\n").split("\n") if l.strip()]
        try:
            start = next(i for i, l in enumerate(lines) if l.lower() == "personnel")
        except StopIteration:
            start = None
        staff = []
        if start is not None:
            body = lines[start + 1:]
            i = 0
            while i < len(body):
                l = body[i]
                if re.match(r"^(share|print|back|top|feedback|contact information)$", l, re.I):
                    break
                if FI_HONORIFIC.match(l) and not l.startswith("-"):
                    rank = body[i + 1] if i + 1 < len(body) else ""
                    loc = body[i + 2] if i + 2 < len(body) else ""
                    if FI_HONORIFIC.match(rank) or rank.startswith("-"):
                        i += 1
                        continue
                    if loc.startswith("("):  # "(Consular Affairs)" ir amata precizējums, ne vieta
                        rank, loc = f"{rank} {loc}", body[i + 3] if i + 3 < len(body) else ""
                        i += 1
                    if FI_HONORIFIC.match(loc) or loc.startswith("-") or len(loc) > 30:
                        loc = ""
                    staff.append({"name": l, "rank": rank, "location": loc or None})
                    i += 3 if loc else 2
                    continue
                i += 1
        missions[title] = {"url": href, "staff": staff}
    snap = {"host": "FI", "list_date": NOW[:10], "source": FI_INDEX, "missions": missions}
    body = json.dumps(snap["missions"], ensure_ascii=False, sort_keys=True).encode()
    h = hashlib.sha256(body).hexdigest()
    index = load_json(LISTS / "index.json", {})
    known = {e["sha256"] for e in index.get("FI", [])}
    new = []
    if missions and h not in known:
        fn = LISTS / "FI" / f"{NOW[:10]}_{h[:10]}.json"
        save_json(fn, snap)
        index.setdefault("FI", []).append({"file": str(fn.relative_to(ROOT)), "url": FI_INDEX, "sha256": h,
                                           "bytes": len(body), "downloaded_at": NOW})
        save_json(LISTS / "index.json", index)
        new.append(str(fn.relative_to(ROOT)))
        record_change("diplomatic_list_new", "FI", FI_INDEX, None, new[0], "Jauna saraksta versija")
    log("list_FI", bool(missions), missions=len(missions),
        with_staff=sum(1 for m in missions.values() if m["staff"]), new=new, errors=errors[:5])


# ------------------------------------------------------- 2. brīdinājumi
def adv_uk():
    out = {}
    for cc, v in WATCH.items():
        try:
            j = get(f"https://www.gov.uk/api/content/foreign-travel-advice/{v['uk']}").json()
            d = j.get("details", {})
            out[cc] = {
                "alert_status": sorted(d.get("alert_status") or []),
                "updated": j.get("public_updated_at"),
                "change": (d.get("change_description") or "")[:400],
                "url": f"https://www.gov.uk/foreign-travel-advice/{v['uk']}",
            }
        except Exception as e:
            out[cc] = {"error": str(e)[:200]}
    return out


def adv_de():
    j = get("https://www.auswaertiges-amt.de/opendata/travelwarning").json()
    resp = j.get("response", j)
    entries = [e for k, e in resp.items() if isinstance(e, dict) and k != "contentList"]
    by_cc = {}
    for e in entries:
        code = (e.get("countryCode") or e.get("iso3CountryCode") or "").upper()
        if code in WATCH:
            by_cc[code] = {
                "warning": bool(e.get("warning")),
                "partial_warning": bool(e.get("partialWarning")),
                "situation_warning": bool(e.get("situationWarning")),
                "situation_part_warning": bool(e.get("situationPartWarning")),
                "updated": e.get("lastModified"),
                "title": e.get("title"),
            }
    return by_cc


US_FEEDS = ["https://travel.state.gov/_res/rss/TAsTWs.xml",
            "https://travel.state.gov/_res/rss/rss_advisories.xml"]


def adv_us():
    last_err = None
    for url in US_FEEDS:
        try:
            soup = BeautifulSoup(get(url).content, "xml")
            items = soup.find_all("item")
            if not items:
                raise ValueError("plūsmā nav ierakstu")
            out = {}
            for it in items:
                title = it.title.get_text(strip=True) if it.title else ""
                for cc, v in WATCH.items():
                    if re.match(rf"^{v['name']}\b", title, re.I):
                        m = re.search(r"Level\s*(\d)", title)
                        desc = it.description.get_text(" ", strip=True) if it.description else ""
                        out[cc] = {
                            "level": int(m.group(1)) if m else None,
                            "title": title,
                            "ordered_departure": bool(re.search(r"ordered departure", desc, re.I)),
                            "authorized_departure": bool(re.search(r"authorized departure", desc, re.I)),
                            "suspended": bool(re.search(r"suspended (?:its )?operations", desc, re.I)),
                            "updated": it.pubDate.get_text(strip=True) if it.pubDate else None,
                            "url": it.link.get_text(strip=True) if it.link else None,
                        }
            out["_feed"] = url
            return out
        except Exception as e:
            last_err = f"{url}: {e}"
    raise RuntimeError(last_err)


def adv_ca():
    j = get("https://data.international.gc.ca/travel-voyage/index-alpha-eng.json").json()
    data = j.get("data", j)
    out = {}
    for code, e in data.items():
        cc = (e.get("country-iso") or code or "").upper()
        if cc in WATCH:
            out[cc] = {
                "advisory_state": e.get("advisory-state"),
                "has_regional": e.get("has-regional-advisory"),
                "updated": e.get("date-published", {}).get("date") if isinstance(e.get("date-published"), dict) else e.get("date-published"),
                "text": (e.get("eng", {}) or {}).get("advisory-text") if isinstance(e.get("eng"), dict) else None,
            }
    return out


# Lauki, kuru maiņa ir signāls (nevis tikai datuma maiņa)
SIGNAL_FIELDS = {
    "US": ["level", "ordered_departure", "authorized_departure", "suspended"],
    "UK": ["alert_status"],
    "DE": ["warning", "partial_warning", "situation_warning", "situation_part_warning"],
    "CA": ["advisory_state", "has_regional"],
}


def fetch_advisories():
    prev = load_json(DATA / "advisories.json", {})
    cur = {"updated_at": NOW}
    for src, fn in (("US", adv_us), ("UK", adv_uk), ("DE", adv_de), ("CA", adv_ca)):
        try:
            res = fn()
            cur[src] = res
            n = len([k for k in res if not k.startswith("_") and "error" not in res[k]])
            log(f"adv_{src}", n > 0, countries=n)
        except Exception as e:
            cur[src] = prev.get(src, {})  # saglabā iepriekšējo, lai nezaudētu stāvokli
            log(f"adv_{src}", False, error=str(e)[:300])
            continue
        old = prev.get(src, {})
        for cc, val in res.items():
            if cc.startswith("_") or "error" in val:
                continue
            o = old.get(cc)
            if o is None or "error" in o:
                continue  # pirmā reize — tas ir sākuma stāvoklis, nevis izmaiņa
            for f in SIGNAL_FIELDS[src]:
                if o.get(f) != val.get(f):
                    record_change("advisory", cc, src, {f: o.get(f)}, {f: val.get(f)},
                                  val.get("title") or val.get("change") or "")
    save_json(DATA / "advisories.json", cur)


# ------------------------------------------------------- 2b. ārvalstu tiešās investīcijas (Eurostat, ceturkšņi)
FDI_GEOS = ["LV", "LT", "EE", "PL", "FI", "SE", "NO"]
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/bop_c6_q"


def _jsonstat_series(j):
    """bop_c6_q JSON-stat → {geo: {quarter: value}} (pārējās dimensijas ir viena vērtība)."""
    ids, size = j["id"], j["size"]
    geo_idx = j["dimension"]["geo"]["category"]["index"]
    t_idx = j["dimension"]["time"]["category"]["index"]
    gi, ti = ids.index("geo"), ids.index("time")
    stride = [1] * len(ids)
    for k in range(len(ids) - 2, -1, -1):
        stride[k] = stride[k + 1] * size[k + 1]
    out = {}
    for geo, g in geo_idx.items():
        for t, tt in t_idx.items():
            v = j.get("value", {}).get(str(g * stride[gi] + tt * stride[ti]))
            if v is not None:
                out.setdefault(geo, {})[t] = v
    return out


def fetch_fdi():
    res, errors = {}, []
    for partner in ("WRL_REST", "RU"):
        params = {"geo": FDI_GEOS, "bop_item": "FA__D__F", "stk_flow": "LIAB", "currency": "MIO_EUR",
                  "partner": partner, "sector10": "S1", "sectpart": "S1", "sinceTimePeriod": "2019-Q1"}
        try:
            r = requests.get(EUROSTAT, params=params, timeout=120)
            j = r.json()
            if "error" in j and not j.get("value"):
                raise RuntimeError(str(j["error"])[:200])
            res[partner] = _jsonstat_series(j)
        except Exception as e:
            errors.append(f"{partner}: {e}")
    if res:
        save_json(DATA / "fdi.json", {"updated_at": NOW, "unit": "milj. EUR", "source": "Eurostat bop_c6_q",
                                      "measure": "Ārvalstu tiešās investīcijas valstī (finanšu konts, saistības, plūsma)",
                                      "world": res.get("WRL_REST", {}), "russia": res.get("RU", {})})
    last = max((q for g in res.get("WRL_REST", {}).values() for q in g), default=None)
    log("fdi", bool(res), last_quarter=last, errors=errors)


# ------------------------------------------------------- 3. ziņas
# Google News RSS meklējumi + oficiālās ĀM plūsmas. Claude vēlāk tās klasificē (ieplānotais uzdevums).
from urllib.parse import quote_plus

GN = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{lang}"
NEWS_QUERIES = [
    # (birka, vaicājums, valoda/reģions)
    ("baltic_en", '(Latvia OR Lithuania OR Estonia) (embassy OR ambassador OR diplomats) (expel OR expelled OR "persona non grata" OR closes OR closure OR evacuate OR "ordered departure" OR recall OR "reduce staff") when:3d', ("en", "US", "en")),
    ("nordic_pl_en", '(Poland OR Finland OR Sweden OR Norway) (embassy OR ambassador OR diplomats) (expel OR expelled OR "persona non grata" OR closes OR closure OR evacuate OR recall OR consulate) when:3d', ("en", "US", "en")),
    ("moscow_minsk_en", '("embassy in Moscow" OR "embassy in Minsk" OR "embassy in Belarus" OR "embassy in Russia") (closes OR suspend OR expel OR diplomats OR staff OR reopen OR ambassador) when:3d', ("en", "US", "en")),
    ("ru", 'посольство (высылка OR выслать OR "персона нон грата" OR закрытие OR консульство OR дипломаты) (Латвия OR Литва OR Эстония OR Польша OR Финляндия OR Швеция OR Норвегия) when:3d', ("ru", "RU", "ru")),
    ("by", 'посольство Беларусь (дипломаты OR высылка OR закрытие OR посол OR поверенный) when:3d', ("ru", "BY", "ru")),
    ("lv", '(vēstniecība OR vēstnieks OR diplomāts) (izraida OR izraidīts OR slēdz OR "persona non grata" OR atsauc) when:3d', ("lv", "LV", "lv")),
    ("lt", '(ambasada OR ambasadorius OR diplomatas) (išsiųsti OR išsiunčia OR uždaro OR "persona non grata") when:3d', ("lt", "LT", "lt")),
    ("ee", '(saatkond OR suursaadik OR diplomaat) (välja saadetud OR saadab välja OR sulgeb OR "persona non grata") when:3d', ("et", "EE", "et")),
    ("pl", '(ambasada OR ambasador OR dyplomata OR konsulat) (wydalenie OR wydalony OR zamknięcie OR "persona non grata") when:3d', ("pl", "PL", "pl")),
    ("fi", '(suurlähetystö OR suurlähettiläs OR diplomaatti) (karkottaa OR karkotettu OR sulkee OR "persona non grata") when:3d', ("fi", "FI", "fi")),
    ("se", '(ambassad OR ambassadör OR diplomat) (utvisa OR utvisas OR stänger OR "persona non grata") when:3d', ("sv", "SE", "sv")),
    ("no", '(ambassade OR ambassadør OR diplomat) (utvise OR utvist OR stenger OR "persona non grata") when:3d', ("no", "NO", "no")),
]
OFFICIAL_FEEDS = [
    ("uk_fcdo", "https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=foreign-commonwealth-development-office"),
    ("us_state", "https://www.state.gov/rss-feed/press-releases/feed/"),
] + [(f"us_emb_{cc}", f"https://{cc}.usembassy.gov/feed/") for cc in ("lv", "ee", "lt", "pl", "fi", "se", "no", "ru", "by")]
# Citu valstu vēstniecības (pārbaudīts automātiski; strādājošās paliek, pārējās redzamas last_run.json kļūdās)
UK_LOC = {"lv": "latvia", "ee": "estonia", "lt": "lithuania", "pl": "poland", "fi": "finland", "se": "sweden",
          "no": "norway", "ru": "russia", "by": "belarus"}
RU_EMB = {"lv": "latvia", "ee": "estonia", "lt": "lithuania", "pl": "poland", "fi": "finland", "se": "sweden", "no": "norway"}
OFFICIAL_FEEDS += [(f"uk_emb_{cc}", f"https://www.gov.uk/search/news-and-communications.atom?world_locations%5B%5D={loc}")
                   for cc, loc in UK_LOC.items()]
# Krievijas un Francijas vēstniecību lapām īstu RSS plūsmu nav — to paziņojumus ķer Google News vaicājumi "emb_ru" u.c.

# Vēstniecību paziņojumi Google News (vācu, ķīniešu, Ziemeļvalstu u.c. vēstniecības, kurām nav plūsmu)
NEWS_QUERIES += [
    ("emb_en", '("embassy in Riga" OR "embassy in Tallinn" OR "embassy in Vilnius" OR "embassy in Warsaw" OR "embassy in Helsinki" OR "embassy in Stockholm" OR "embassy in Oslo") (citizens OR alert OR advises OR staff OR closed OR evacuat) when:3d', ("en", "US", "en")),
    ("emb_ru", '("посольство России в Латвии" OR "посольство России в Эстонии" OR "посольство России в Литве" OR "посольство России в Польше" OR "посольство России в Финляндии" OR "посольство Беларуси") when:3d', ("ru", "RU", "ru")),
    ("emb_de", '("Botschaft Riga" OR "Botschaft Tallinn" OR "Botschaft Vilnius" OR "Botschaft Warschau" OR "Botschaft Moskau" OR "Botschaft Minsk") when:3d', ("de", "DE", "de")),
    ("inv_en", '(Latvia OR Lithuania OR Estonia OR Baltic) (investment OR investor OR factory OR plant OR "data center") (announces OR invests OR withdraws OR exits OR halts OR cancels OR relocates) when:3d', ("en", "US", "en")),
    ("inv_lv", '(investīcijas OR investors OR rūpnīca) (Latvijā OR Latvija) (iegulda OR aiziet OR aptur OR pārceļ OR slēdz) when:3d', ("lv", "LV", "lv")),
    ("inv_nordic_pl", '(Poland OR Finland OR Sweden OR Norway) (foreign investment OR investor) (withdraws OR exits OR halts OR relocates OR "security concerns") when:3d', ("en", "US", "en")),
    ("inv_drop_en", '("foreign direct investment" OR FDI OR "foreign investment") (Latvia OR Lithuania OR Estonia OR Baltic OR Poland OR Finland OR Sweden OR Norway) (fell OR fall OR decline OR drop OR outflow OR lowest OR slump) when:7d', ("en", "US", "en")),
    ("inv_drop_lv", '("ārvalstu tiešās investīcijas" OR "ārvalstu investīcijas" OR investīciju) (samazinājās OR kritums OR sarukušas OR aizplūde OR zemākais) when:7d', ("lv", "LV", "lv")),
    ("inv_drop_lt", '("tiesioginės užsienio investicijos" OR "užsienio investicijos") (sumažėjo OR mažėja OR nuosmukis) when:7d', ("lt", "LT", "lt")),
    ("inv_drop_ee", '("välisinvesteeringud" OR "otseinvesteeringud") (vähenesid OR langus OR kahanes) when:7d', ("et", "EE", "et")),
    ("inv_drop_pl", '("inwestycje zagraniczne" OR "bezpośrednie inwestycje zagraniczne") (spadek OR spadły OR odpływ) when:7d', ("pl", "PL", "pl")),
    ("inv_drop_fi", '("ulkomaiset suorat sijoitukset" OR "ulkomaiset investoinnit") (laskivat OR lasku OR vähenivät) when:7d', ("fi", "FI", "fi")),
    ("emb_zh", '(大使馆 OR 使馆) (拉脱维亚 OR 爱沙尼亚 OR 立陶宛 OR 波兰 OR 芬兰) 提醒 when:7d', ("zh-CN", "CN", "zh-Hans")),
]
# ASV vēstniecību paziņojumi: paturam brīdinājumus un visu par personālu/darbību
US_EMB_KEEP = re.compile(r"alert|departure|evacuat|staff|suspend|clos|reduc|ordered|authorized|message to u\.s\. citizens|"
                         r"security|consular services|embassy operations", re.I)
EMB_KEEP_ML = re.compile(r"предупрежд|рекоменд|выезд|эвакуац|закрыт|консульск|безопасн|персонал|высыл|"
                         r"alerte|sécurité|fermeture|évacuation|recommand|consulaire|"
                         r"travel advice|ambassador|embassy|diplomat", re.I)
NEWS_KEYWORDS = re.compile(
    r"embass|ambassad|diplomat|consul|persona non grata|expel|chargé|charge d|ordered departure|authorized departure|"
    r"посол|посольств|дипломат|консул|высыл|vēstn|diplomāt|ambasad|saatkond|suurlähet|utvis|wydal", re.I)
REGION_WORDS = re.compile(
    r"latvia|lithuania|estonia|poland|finland|sweden|norway|baltic|russia|moscow|belarus|minsk|kaliningrad|"
    r"латви|литв|эстон|польш|финлянд|швец|норвег|росси|москв|беларус|минск|калининград", re.I)


def fetch_news():
    path = DATA / "news.jsonl"
    seen, keep = set(), []
    cutoff = datetime.now(timezone.utc).timestamp() - 60 * 86400
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                it = json.loads(line)
            except Exception:
                continue
            if datetime.fromisoformat(it["seen_at"]).timestamp() >= cutoff:
                keep.append(it)
                seen.add(it["id"])
    new, errors, raw_counts = [], [], {}
    sources = [(tag, GN.format(q=quote_plus(q), hl=hl, gl=gl, lang=lang)) for tag, q, (hl, gl, lang) in NEWS_QUERIES]
    sources += OFFICIAL_FEEDS
    for tag, url in sources:
        try:
            soup = BeautifulSoup(get(url, polite=3 if "news.google" in url else 1).content, "xml")
        except Exception as e:
            errors.append(f"{tag}: {str(e)[:150]}")
            continue
        raw_counts[tag] = len(soup.find_all(["item", "entry"]))
        for it in soup.find_all(["item", "entry"]):
            title = (it.title.get_text(" ", strip=True) if it.title else "")
            link_el = it.find("link")
            link = (link_el.get("href") or link_el.get_text(strip=True)) if link_el else ""
            summ = it.find(["description", "summary"])
            text = f"{title} {summ.get_text(' ', strip=True) if summ else ''}"
            if tag in ("uk_fcdo", "us_state") and not (NEWS_KEYWORDS.search(text) and REGION_WORDS.search(text)):
                continue
            if re.match(r"(us|uk|fr|ru)_emb_", tag) and not (US_EMB_KEEP.search(text) or EMB_KEEP_ML.search(text)):
                continue
            src = it.find("source")
            pub = it.find(["pubDate", "published", "updated"])
            try:  # Google News reizēm atgriež vecus rakstus — ņemam tikai pēdējās 7 dienas
                from email.utils import parsedate_to_datetime
                ptxt = pub.get_text(strip=True) if pub else ""
                pdt = parsedate_to_datetime(ptxt) if "," in ptxt else datetime.fromisoformat(ptxt.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - pdt).days > 7:
                    continue
            except Exception:
                pass
            iid = hashlib.sha1((link or title).encode()).hexdigest()[:16]
            if iid in seen:
                continue
            seen.add(iid)
            item = {"id": iid, "tag": tag, "title": title[:300], "url": link,
                    "source": src.get_text(strip=True) if src else tag,
                    "published": pub.get_text(strip=True) if pub else None, "seen_at": NOW}
            new.append(item)
    keep += new
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in keep), encoding="utf-8")
    log("news", len(errors) < len(sources), new=len(new), total=len(keep), errors=errors[:40],
        empty_feeds=[t for t, n in raw_counts.items() if n == 0])


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("all", "lists"):
        fetch_lists()
        fetch_fi()
        fetch_fdi()
    if what in ("all", "advisories"):
        fetch_advisories()
        fetch_news()
    save_json(DATA / "last_run.json", run_log)
