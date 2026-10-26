"""Militāro lidmašīnu blīvi maršruti Robežas sargam (adsb.lol /v2/mil) — bez AI.

Viena palaišana klausās `seconds` sekundes (noklusēti 540) un ik ~30 s nolasa adsb.lol militāro lidmašīnu sarakstu
(viens pieprasījums uz visu pasauli), saglabā pozīcijas mūsu apgabalā un uztur data/rs/miltracks.json:
  {"updatedAt": ISO, "tracks": {"<hex>": {"cs": izsaukums, "t": tips, "p": [[lat, lon, unix_s], ...]}}}
Glabā pēdējās 12 h; taisnus posmus vienkāršo (punkts pagriezienos ≥8° vai ik ~10 min), lai fails paliktu mazs.
air_checks.py no šī faila pievieno jaunākajai pārbaudei lauku "trace", ko lapa zīmē kā pilnu maršrutu.
Lieto: python mil_tracks.py [seconds]
"""
import json, math, os, sys, time, datetime as dt
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "rs", "miltracks.json")
BBOX = (47.0, 71.5, 4.0, 42.0)  # tas pats apgabals, ko air_checks.py
KEEP_S = 12 * 3600
UA = {"User-Agent": "robezas-sargs (+https://github.com/Toms0078/robezas-sargs-dati2)"}

def km(a, b):
    R, t = 6371, math.pi / 180
    h = math.sin((b[0] - a[0]) * t / 2) ** 2 + math.cos(a[0] * t) * math.cos(b[0] * t) * math.sin((b[1] - a[1]) * t / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))

def brg(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2); x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def add_point(tr, p):
    pts = tr["p"]
    if not pts: pts.append(p); return
    last = pts[-1]
    if p[2] <= last[2]: return
    d = km(last, p)
    if d > 80 and (p[2] - last[2]) < 300: return  # nereāls lēciens (kļūdaina pozīcija)
    if len(pts) >= 2:
        turn = abs((brg(pts[-2], last) - brg(last, p) + 180) % 360 - 180)
        if turn < 8 and (p[2] - pts[-2][2]) < 600:
            pts[-1] = p  # gandrīz taisna kustība: pārvieto pēdējo punktu (pagriezieni saglabājas)
            return
    pts.append(p)

def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 540
    try: data = json.load(open(OUT, encoding="utf-8"))
    except Exception: data = {"tracks": {}}
    tracks = data.get("tracks") or {}
    end = time.time() + secs; polls = ok = 0
    while True:
        polls += 1
        try:
            r = requests.get("https://api.adsb.lol/v2/mil", headers=UA, timeout=25)
            j = r.json() if r.status_code == 200 else None
        except Exception as e:
            print("kļūda:", str(e)[:100]); j = None
        if j:
            ok += 1
            now = int(j.get("now", time.time() * 1000) / 1000) if j.get("now", 0) > 1e11 else int(time.time())
            for a in j.get("ac") or []:
                la, lo = a.get("lat"), a.get("lon")
                if la is None or lo is None or a.get("alt_baro") == "ground": continue
                if not (BBOX[0] <= la <= BBOX[1] and BBOX[2] <= lo <= BBOX[3]): continue
                ts = now - int(a.get("seen_pos") or 0)
                tr = tracks.setdefault(a["hex"].lower(), {"cs": "", "t": "", "p": []})
                tr["cs"] = (a.get("flight") or tr["cs"] or "").strip(); tr["t"] = a.get("t") or tr["t"]
                add_point(tr, [round(la, 4), round(lo, 4), ts])
        if time.time() + 30 > end: break
        time.sleep(30)
    cut = int(time.time()) - KEEP_S
    for h in list(tracks):
        tracks[h]["p"] = [p for p in tracks[h]["p"] if p[2] >= cut]
        if not tracks[h]["p"]: del tracks[h]
    data = {"updatedAt": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "tracks": tracks}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    npts = sum(len(t["p"]) for t in tracks.values())
    print(f"{data['updatedAt']} vaicājumi {ok}/{polls}, lidmašīnas {len(tracks)}, punkti {npts}, fails {os.path.getsize(OUT)//1024} KB")

if __name__ == "__main__":
    main()
