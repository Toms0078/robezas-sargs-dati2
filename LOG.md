# Darba žurnāls

Katra automātiskā sesija pievieno ierakstu beigās: datums/laiks (Europe/Riga), ROADMAP punkts, kas izdarīts,
kas palika, problēmas, recenzenta piezīmes.

## Lietotājam
(Šeit aģents raksta tikai to, kas prasa lietotāja rīcību, piem. jaunas API atslēgas reģistrācija.)

## Ieraksti
- 2026-10-14 10:20 – Izveidotas vadlīnijas `CLAUDE.md`, plāns `ROADMAP.md`, žurnāls. Lapā jau ir: Būtiņģe (piegādes, izkraušanas
  simulācija), LNG termināļi ar ALSI datiem, pazemes krātuves (AGSI), gāzesvadu plūsmas (ENTSOG), Inčukalna "cik dienām pietiek",
  kuģi (AIS), sankciju tankkuģi, SAR, karogi kā SVG, puscaurspīdīgi kartes uzraksti, slāņu pogas zem kartes.
- 2026-10-14 11:30 – 4a 1/5 Naftas bilance (oficiāli): `oil_balance.py` (Eurostat nrg_cb_oilm, 7 valstis, 34–35 mēn.), darbplūsma `oil-balance.yml` (pirmdienās),
  lapas sadaļa `#naftas-bilance` (valstu pogas + "Baltija kopā", KPI, grafiks, bilance pa produktiem, valstu salīdzinājums). Produkta vadītājs izplānoja 5 posmus;
  dizaina recenzents atrada 8 obligātus labojumus – visi izlaboti (konfidenciālās Eurostat vērtības "|C" un 0 šādās sērijās → "—", 12 mēn. summas tikai pilniem
  gadiem, Baltijas summa tikai ja visas 3 valstis, grafika fonts telefonā, krāsas, nepārrakstīt datus ar tukšiem). Nākamais: 2/5 imports pēc izcelsmes + rezerves.
