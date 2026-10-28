# Darba žurnāls

Katra automātiskā sesija pievieno ierakstu beigās: datums/laiks (Europe/Riga), ROADMAP punkts, kas izdarīts,
kas palika, problēmas, recenzenta piezīmes.

## Lietotājam
(Šeit aģents raksta tikai to, kas prasa lietotāja rīcību, piem. jaunas API atslēgas reģistrācija.)

- 2026-10-23: lai darbotos gaisa trauksmju vācējs, vajag bezmaksas Gemini API atslēgu → https://aistudio.google.com/apikey,
  tad GitHub → Settings → Secrets and variables → Actions → New repository secret, nosaukums `GEMINI_API_KEY`.

## Ieraksti
- 2026-10-14 10:20 – Izveidotas vadlīnijas `CLAUDE.md`, plāns `ROADMAP.md`, žurnāls. Lapā jau ir: Būtiņģe (piegādes, izkraušanas
  simulācija), LNG termināļi ar ALSI datiem, pazemes krātuves (AGSI), gāzesvadu plūsmas (ENTSOG), Inčukalna "cik dienām pietiek",
  kuģi (AIS), sankciju tankkuģi, SAR, karogi kā SVG, puscaurspīdīgi kartes uzraksti, slāņu pogas zem kartes.
- 2026-10-14 11:30 – 4a 1/5 Naftas bilance (oficiāli): `oil_balance.py` (Eurostat nrg_cb_oilm, 7 valstis, 34–35 mēn.), darbplūsma `oil-balance.yml` (pirmdienās),
  lapas sadaļa `#naftas-bilance` (valstu pogas + "Baltija kopā", KPI, grafiks, bilance pa produktiem, valstu salīdzinājums). Produkta vadītājs izplānoja 5 posmus;
  dizaina recenzents atrada 8 obligātus labojumus – visi izlaboti (konfidenciālās Eurostat vērtības "|C" un 0 šādās sērijās → "—", 12 mēn. summas tikai pilniem
  gadiem, Baltijas summa tikai ja visas 3 valstis, grafika fonts telefonā, krāsas, nepārrakstīt datus ar tukšiem). Nākamais: 2/5 imports pēc izcelsmes + rezerves.
- 2026-10-23 08:45 – Gaisa trauksmes pārceltas uz GitHub Actions + Gemini (lai netērētu Claude limitus): `air_alerts.py`, darbplūsma
  `air-alerts.yml` (ik stundu :23), `data/airalerts/` (codes.json – 575 teritoriju kodi: LV novadi, EE apriņķi, LT pašvaldības, PL vojevodistes
  un apriņķi, FI reģioni, 37 Krievijas apgabali). Claude artefakts tikai pārkopē `current.json`. Gaida `GEMINI_API_KEY`.
- 2026-10-23 10:40 – Gaisa trauksmes: Gemini atslēga (`GEMINI_API`) un norēķini darbojas. Atklāts: Flash-Lite reizēm nemeklē un izdomā
  ierakstus → stundas pārbaude tagad saglabā tikai ierakstus, kuru saites domēns ir starp Gemini meklēšanas avotiem; izņemti 2 izdomāti RU ieraksti.
  Pievienota ātrā pārbaude ik 10 min (`air_alerts_fast.py`, ziņu plūsmas → Gemini bez meklēšanas, saitei jābūt no plūsmas) un atsevišķa lapa
  `trauksmes/` (SVG karte: LV novadi, EE apriņķi, LT pašvaldības, PL vojevodistes+apriņķi, FI reģioni, 37 RU apgabali; pirkstu žesti; automātiska
  atjaunošana ik 2 min). Pārbaudīts headless 1250/400 px, bez kļūdām.

## 2026-10-23 — Robežas sargs pārcelts uz GitHub
- Lapa: `robezas-sargs/index.html` (https://toms0078.github.io/robezas-sargs-dati2/robezas-sargs/), dati `data/rs/`.
- Lidmašīnas: `air_checks.py` + `air-checks.yml` (ik stundu :12, adsb.lol, bez AI).
- Vēstniecības, brīdinājumi, ĀTI: `publish_rs.py` darbplūsmā `collect.yml` (bez AI).
- Vēstniecību un investīciju ziņas: `gemini_rs.py dip inv` (2× dienā), tranzīts `gemini_rs.py transit` (1× dienā, gemini-3.5-flash ar meklēšanu) — `rs-gemini.yml`.
- Galvenais pārskats: `gemini_report.py` + `rs-report.yml` (~07:37 un ~19:37). 4 daļas; katrā vispirms Gemini meklē, tad apvieno ar iepriekšējo;
  saitēm jābūt no meklēšanas domēniem un tām jāatveras (404 = izmet); sadaļas fiksētas (air, russia, osint, official, nordic);
  ceļošanas brīdinājumi no advisories.json; ja daļa neizdodas, paliek iepriekšējā.
- Palika: spēku (forces) un vēstniecību east/side nedēļas atjaunošana vēl ir statiska; push paziņojumi nāk tikai no Claude uzdevuma.

## 2026-10-26 — Lidmašīnu tipu foto
- `type_photos.py` + `type-photos.yml` (ik 6 h :47): tipiem no `data/rs/airchecks.json` atrod angļu Wikipedia raksta galveno attēlu
  Wikimedia Commons, pārbauda licenci (CC/PD), samazina līdz ~520 px JPEG ≤60 KB un saglabā `data/rs/typephotos/<TIPS>.json`
  ({img: data URI, name, author, license, file}). Robežas sarga lapa foto rāda lidmašīnas kartītē, neizejot no rīka; Claude stundas
  uzdevums tos pārkopē artifact datubāzē (kolekcija `photos`). Nekartētie tipi → `typephotos/_missing.json` (papildini `TYPES`).
- 2026-10-26 (papildinājums): `type_photos.py` meklē arī **konkrētās militārās lidmašīnas** foto Commons pēc reģistrācijas
  (faila nosaukumā jābūt reģ. numuram + aviācijas vārdam vai tipa nosaukumam, licence CC/PD) → `typephotos/R_<REĢ>.json` ar lauku `reg`.
  Lapa vispirms rāda konkrētās lidmašīnas foto, citādi tipa foto. Neatrastos reģ. atkārtoti meklē pēc 30 dienām.
- 2026-10-26: **Pilni militāro lidmašīnu maršruti.** `mil_tracks.py` + `mil-tracks.yml` (cilpa ~5 h 40 min, cron ik 2 h :17): ik ~30 s
  nolasa adsb.lol `/v2/mil`, glabā pozīcijas mūsu apgabalā pēdējās 12 h `data/rs/miltracks.json` (taisni posmi vienkāršoti,
  pagriezieni saglabāti). `air_checks.py` jaunākajai pārbaudei pievieno `trace` (≤151 punkts; vecākajām pārbaudēm noņem),
  ko Robežas sarga lapa zīmē kā pilnu maršrutu. Zviedrijas GLF4/S102 ar SVF izsaukumu vai reģ. 102002/102003 tagad apzīmē kā
  S 102B Korpen (signālu izlūkošana).
- 2026-10-26: `mil_tracks.py` seko arī **Krievijas/Baltkrievijas** lidmašīnām (arī civilajām): ik ~60 s 3 apgabali (Kaļiņingradas
  koridors pār Baltijas jūru, Somu līcis/Pēterburga, Pleskava–Baltkrievija); `air_checks.py` pievieno `trace` arī `ruList` ierakstiem.
- 2026-10-26: GitHub `air-checks.yml` grafiks reāli palaižas tikai ik 2–6 h (lapā lidmašīnas bija stundām vecas). Tagad
  `air_checks.py` palaiž arī `mil-tracks.yml` cilpa ik ~10 min. Lapa lidmašīnas kartītē rāda pozīcijas vecumu.
- 2026-10-26: `mil-tracks.yml` cikls saīsināts uz ~4 min (pārbaude un maršruti saglabājas ik ~5 min). GitHub Pages lapa
  `robezas-sargs/` tos lasa ik 3 min; claude.ai artifakts — ik stundu (ieplānotu uzdevumu minimums).
- 2026-10-26: **Robežas sargs 2 GitHub Pages versijā** — `robezas-sargs2/index.html` (karte centrā, maršruti, lidmašīnu foto,
  izmaiņas, datu svaigums, signālu slānis). Tā pati lapa kā claude.ai artefakts, bet `window.claude.use("db")` aizstāts ar
  JSON lasīšanu no `../data/rs/` ik 3 min (`photos/X` → `typephotos/X.json`, `doc().get()` atbalstīts). Pārbaudīts headless
  1250/400 px, bez pageerror. `air_checks.py`: AWACS/izlūki (E3TF, RC-135, P-8, GLF4/S102 u.c.) ar militāru karodziņu vai
  NATO izsaukumu vairs netiek klasificēti kā tankeri.

## 2026-10-28 — lidmašīnu vākšana: rezerves avoti
- Problēma: kopš ~08:05 UTC adsb.lol uz GitHub Actions pieprasījumiem atbildēja HTTP 429 — pārbaudēs izdevās tikai 1/9 apgabali, kartē lidmašīnu gandrīz nebija.
- Labojums: jauns `adsb_src.py` — katrs vaicājums pēc kārtas adsb.lol → airplanes.live → adsb.fi (tas pats readsb formāts, bez atslēgām), ≤1 piepr./s uz avotu, pēc 429 avots 5 min izlaists. Izmanto `air_checks.py` un `mil_tracks.py`; logā un laukā `source` redzams, kuri avoti strādāja.
- Lietotājam: claude.ai ieplānotais uzdevums "Baltijas debesis" (kopē uz artefaktu) 28.10. 12:32 UTC beidzās ar ACCESS_DENIED — jāseko, vai atjaunojas.
