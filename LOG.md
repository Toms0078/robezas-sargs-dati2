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
