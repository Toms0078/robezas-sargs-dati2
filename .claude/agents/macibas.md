# Aģentu kopīgās mācības

Šeit aģenti paši pieraksta, ko iemācījušies. Formāts: `- YYYY-MM-DD – mācība – kāpēc` (pēc pārnešanas instrukcijās: `→ pārnests instrukcijās`).
Lietotājs var šeit arī pats ierakstīt vēlmes – aģenti tās ievēro.

## Visiem (no līdzšinējā darba ar lietotāju)
- 2026-10-14 – Lietotājs skatās lapu gan telefonā, gan Windows datorā – karogu emocijzīmes Windows nerāda, tāpēc tikai `emojiOf()` SVG.
- 2026-10-14 – Lietotājs vēlas, lai kartes uzraksti netraucē kartei: puscaurspīdīgs fons, slāņu pogas zem kartes, nevis virs.
- 2026-10-14 – Lietotājs bieži jautā "no kurienes nāk / kur ved" – katram kuģim un plūsmai rādīt izcelsmi un galamērķi.
- 2026-10-14 – Simulācijas lietotājs pieņem, bet grib redzēt arī, ka tās ir aplēses; kad pieejami īsti dati (ALSI, AGSI, ENTSOG) – tie vienmēr pirmie.
- 2026-10-14 – Datu avotus no darba sesijas čaulas bieži nevar sasniegt – testēt caur GitHub Actions ar `--test` režīmu.
- 2026-10-14 – GFW reģistrā LNG kuģiem bieži nav GT un tips ir "OTHER"; LNG kuģus labāk atpazīt pēc iepriekšējās ostas (LNG eksporta terminālis).

## produkta-vaditajs
- 2026-10-14 – Tiešs WebFetch uz `ec.europa.eu/eurostat/api` var palikt bez atļaujas; datu kopu dimensijas un pēdējo periodu ātri pārbauda caur DBnomics (`db.nomics.world/Eurostat/<kods>`), bet precīzos kodus (nrg_bal, siec, cargo) liek izdrukāt skripta `--test` režīmam – kodus no atmiņas nerakstīt kā faktu.
- 2026-10-14 – `energy_inbound.json` laukā `arrived` glabājas tikai pēdējie ~60–80 ieraksti (~3 dienas) bez kravas aplēses – mēneša summām vajag atsevišķu uzkrājošu žurnālu.
- 2026-10-14 – Ostu ierašanās ≠ valsts patēriņš (Ventspils/Klaipēda/Muuga lielākoties tranzīts; LV degvielu daudz ved pa sauszemi no Mažeiķiem) – bilances lapā tas jāpasaka tieši.

## dizaina-recenzents
- 2026-10-14 – Eurostat datos pārbaudīt ar "veselā saprāta" salīdzinājumu (piem. FI rūpnīcu izlaide 12 Mt, bet jēlnaftas imports 0) – konfidenciālās vērtības (statuss `c`) var parādīties kā 0 vai iztrūkt; skriptam jālasa `status` un tās jārāda kā "—"/"konfid." – citādi kopsummas un "uz iedz." ir maldinoši.
- 2026-10-14 – JS kopsummās meklēt `||0` un `x?…:'—'` – pirmais pārvērš trūkstošu par 0, otrais īstu 0 par "—"; abi ir godīguma kļūdas.
- 2026-10-14 – Telefona ekrānuzņēmumā SVG grafikam ar viewBox 600 un font-size 10 uzraksti kļūst ~5 px – prasīt lielāku fontu vai šaurāku viewBox mazā ekrānā. Skaitļi ar `toFixed()` dod punktu, nevis lv komatu.
- 2026-10-14 – Datu skriptiem pārbaudīt, vai pie pilnīgas avota kļūmes tie nepārraksta labo JSON ar tukšu.
