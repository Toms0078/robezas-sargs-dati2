# Robežas sargs — diplomātiskā monitoringa dati

Automātiski vāc datus Robežas sarga sadaļai "Vēstniecības". Darbojas GitHub Actions, bez manuālas iejaukšanās.

**Uzņēmējvalsts puse** — oficiālie diplomātu saraksti (Latvija, Igaunija, Somija, Zviedrija, Norvēģija). Jauna versija tiek lejupielādēta, tiklīdz tā parādās, un saglabāta `data/lists/<valsts>/`.

**Vēstniecību valstu puse** — ceļošanas brīdinājumi (ASV, Lielbritānija, Vācija, Kanāda) par Baltiju, Poliju, Ziemeļvalstīm, Krieviju un Baltkrieviju. Pašreizējais stāvoklis: `data/advisories.json`.

**Izmaiņas** — katra būtiska maiņa vienā rindā `data/changes.jsonl`.
**Pēdējās palaišanas atskaite** — `data/last_run.json`.

Palaist ar roku: Actions → "Vākt datus" → Run workflow.

## Būtiņģe un Baltijas ostas (AIS)

Darbplūsma "Būtiņģes boja (AIS)" ik 15 min apvieno AIS datus no aisstream.io (atslēga `AISSTREAM_API_KEY`) un
Somijas [Digitraffic](https://www.digitraffic.fi/en/marine-traffic/) (Fintraffic, CC BY 4.0). Sankciju un ēnu flotes
saraksts: [OpenSanctions](https://www.opensanctions.org/datasets/maritime/) (CC BY-NC 4.0). Lapa: `butinge/index.html`.

## Gaisa trauksmes (Gemini)

Darbplūsma "Gaisa trauksmes (Gemini)" ik stundu ar Google Gemini (lētākais Flash-Lite modelis + Google meklēšana) atrod
gaisa trauksmes Latvijā, Igaunijā, Lietuvā, Polijā, Somijā un Krievijas apgabalu dronu/raķešu briesmu režīmus.
Skripts `air_alerts.py` pārbauda katru ierakstu (teritoriju kodi no `data/airalerts/codes.json`, laiks, avota saite).
Rezultāts: `data/airalerts/current.json`, logs `data/airalerts/last_run.log`. Vajag GitHub Secret `GEMINI_API_KEY`
(bezmaksas atslēga: https://aistudio.google.com/apikey). Modeli var mainīt ar repozitorija mainīgo `GEMINI_MODEL`.
