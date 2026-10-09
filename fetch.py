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
    "FI": {
        "index": ["https://um.fi/the-helsinki-diplomatic-list"],
        "match": r"diplomatic|helsinki|\.pdf",
        "seeds": [],
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


def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=60, **kw)
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
            if re.search(r"\.pdf|\.docx|download|documents|getfile", href, re.I):
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


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("all", "lists"):
        fetch_lists()
    if what in ("all", "advisories"):
        fetch_advisories()
    save_json(DATA / "last_run.json", run_log)
