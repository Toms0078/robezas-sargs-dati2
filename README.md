# Robežas sargs — diplomātiskā monitoringa dati

Automātiski vāc datus Robežas sarga sadaļai "Vēstniecības". Darbojas GitHub Actions, bez manuālas iejaukšanās.

**Uzņēmējvalsts puse** — oficiālie diplomātu saraksti (Latvija, Igaunija, Somija, Zviedrija, Norvēģija). Jauna versija tiek lejupielādēta, tiklīdz tā parādās, un saglabāta `data/lists/<valsts>/`.

**Vēstniecību valstu puse** — ceļošanas brīdinājumi (ASV, Lielbritānija, Vācija, Kanāda) par Baltiju, Poliju, Ziemeļvalstīm, Krieviju un Baltkrieviju. Pašreizējais stāvoklis: `data/advisories.json`.

**Izmaiņas** — katra būtiska maiņa vienā rindā `data/changes.jsonl`.
**Pēdējās palaišanas atskaite** — `data/last_run.json`.

Palaist ar roku: Actions → "Vākt datus" → Run workflow.
