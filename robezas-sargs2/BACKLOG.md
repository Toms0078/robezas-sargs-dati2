# Robežas sargs 2 — darbu saraksts (patstāvīgajai uzlabošanai)

Šo sarakstu katru dienu apstrādā ieplānotais uzdevums "Robežas sargs · ikdienas uzlabojumi".
Ņem pirmo neizdarīto punktu `[ ]`, izdari to labi, atzīmē `[x]` ar datumu. Ja nav izdarāms — `[!]` ar iemeslu.
Lietotāja (Toms) principi: **vienkārša saskarne, karte centrā, maz teksta, viss rīkā (nevis ārējās saites), svaigi un pārbaudāmi dati,
pasaules līmeņa kvalitāte, strādā bez viņa iesaistes.** Lietotājs pārsvarā skatās no telefona.

## Kā lapa ir uzbūvēta
- Kanoniskais avots: claude.ai artefakts https://claude.ai/artifact/RyNuSPzgsooxbcqqiDVTNn (lapa bez `<html>/<head>` skeleta, ar `window.claude.use("db")`).
- GitHub Pages kopija: `robezas-sargs2/index.html` = `<head>` + artefakta saturs + datu aizstājējs (`<script>` ar "Robežas sargs 2 — GitHub versija",
  lasa `../data/rs/*.json`). Pēc katras izmaiņas atjauno ABAS: publicē artefaktu un pārbūvē GitHub failu (saglabā to pašu head un aizstājēju).

## Darāmais (prioritātes secībā)
- [x] 2026-10-26 Lidmašīnas izvēle, uzspiežot maršruta līnijai vai sākuma punktam.
- [ ] Uzspiežami visi kartes elementi: notikumi, signāli, trauksmju teritorijas, tranzīta maršruti, karaspēka kastes — katrs atver īsu kartīti rīkā.
      Pārbaudi telefona platumā (400 px), ka pieskāriena zonas ir ≥ 40 px.
- [ ] Lidmašīnas kartītē: maršruta garums (km), lidojuma ilgums, augstuma/ātruma mini grafiks no `trace` (ja ir), vai lidmašīna šobrīd tuvojas robežai (< 50 km).
- [ ] Būtiņģes un tankkuģu slānis kartē (dati jau ir `data/butinge/`, `data/ports/` — sk. `butinge/index.html`): kuģa punkts, tips, kravas veids, kartīte.
- [ ] Vienots galvenais pārskats: GitHub (Gemini, `data/rs/reports.json`) un claude.ai (Claude) versijas rāda dažādus posmus. Izlem vienu avotu
      (ieteicams Claude pārskats; GitHub to var nolasīt, ja Claude uzdevums to ieraksta arī repozitorijā) — ja vajag lietotāja lēmumu, ieliec to paziņojumā.
- [ ] Ticamība kartē: apstiprināts / visticamāk / neapstiprināts — atšķirīga punkta forma vai kontūra visiem notikumiem (ne tikai signāliem).
- [ ] Tendence 30 dienās: kartē reģionu iekrāsojums pēc notikumu skaita izmaiņām (pieaug/samazinās), maza leģenda, bez teksta.
- [ ] Posma formula: caurspīdīgs svaru skaidrojums (kuri signāli cik sver), redzams zem "Kāpēc šāds vērtējums" kā mazs joslu grafiks.
- [ ] Lidmašīnu meklēšana: ievades lauks virs kartes (izsaukums, reģ., tips) → pietuvina un atver kartīti.
- [ ] Laika slīdnis lidmašīnu slānim: atskaņot pēdējās 12 h maršrutus (no `trace`).
- [ ] Valodas EN / LV / LT / EE (tikai saskarnes teksti; dati paliek latviski līdz tulkošanas solim).
- [ ] Publiskās versijas pārbaude: GitHub Pages lapa bez claude.ai, ātrums telefonā (< 2 s pirmais attēls), lapas izmērs (kartes ģeometrija atsevišķā failā).

## Idejas (izvērtē, pirms ņem darbā)
- Krievijas civilo reisu "pazušana" (gaisa telpas slēgšana) kā automātisks signāls kartē.
- GPS traucējumu slānis no "Jauni signāli" (ja kind=gps atkārtojas).
- Paziņojumi par konkrētām lidmašīnām (piem. AWACS virs Latvijas) — lietotājs izvēlas, kuras sekot.
