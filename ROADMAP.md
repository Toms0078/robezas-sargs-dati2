# Darba plāns – "pro" enerģētikas rīks

Apzīmējumi: `[ ]` darāms · `[~]` iesākts · `[x]` izdarīts · `[!]` nav izdarāms (iemesls blakus).
Secība = prioritāte. Aģents var sadalīt punktu mazākos, ja tas par lielu vienai sesijai.

## 1. Kopsavilkums un brīdinājumi
- [ ] **Kopsavilkuma panelis lapas augšā** (virs kartes): 6–8 galvenie rādītāji ar mazu tendenci – Inčukalns %, Klaipēdas LNG %,
      nākamā Būtiņģes piegāde, LV gāzes patēriņš, gāzes plūsma LT→LV, elektrības cena LV šodien (kad būs), aktīvo brīdinājumu skaits.
      Katrs rādītājs – saite uz sadaļu.
- [ ] **Brīdinājumu sistēma** (`alerts.py` → `data/alerts/latest.json`, palaiž pēc citām darbplūsmām): noteikumi, piem.
      Inčukalns zem pērnā līmeņa > 5 p.p.; LNG krātuve < 20 %; sankciju tankkuģis Baltijā tuvu LV/LT ostām; kuģis stāv/velk virs kabeļa (sk. 3.);
      plūsma pa savienojumu mainījusi virzienu. Lapā – saraksts ar laiku un smagumu.

## 2. Elektrība (jauna sadaļa "Elektrība Baltijā")
- [ ] **Biržas cenas** (Nord Pool) LV, LT, EE, FI pa stundām šodien un rīt, grafiks + vidējā/min/max. Avots bez atslēgas:
      Elering API (`https://dashboard.elering.ee/api/nps/price?start=…&end=…` atgriež ee/lv/lt/fi). Ja nepieejams – meklē citu atvērtu avotu.
- [ ] **Starpsavienojumu plūsmas** kartē ar animētām līnijām (kā gāzei): Estlink 1/2 (EE–FI), NordBalt (LT–SE), LitPol (LT–PL),
      EE–LV, LV–LT, Harmony Link (ja darbojas). Avots: Elering/AST/Litgrid atvērtie dati vai ENTSO-E (vajag atslēgu – tad `[!]`).
- [ ] **Ražošana un patēriņš Latvijā** pa veidiem (HES, TEC, vējš, saule, imports) – AST atvērtie dati vai Elering bilance.
- [ ] **Tīkla frekvence / sinhronizācija** ar kontinentālo Eiropu (ja ir atvērts avots), citādi `[!]`.

## 3. Zemūdens infrastruktūras uzraudzība (Robežas sargs)
- [ ] Ievadi zemūdens kabeļu un cauruļvadu trases (aptuvenas, publiski zināmas): Estlink 1, Estlink 2, Balticconnector, NordBalt,
      C-Lion1, BCS East-West, Latvija–Gotlande sakaru kabeļi u.c. Kartē – slānis "Zemūdens kabeļi" (plānas līnijas).
- [ ] Brīdinājums, ja kuģis (no esošajiem AIS datiem) **stāv vai brauc < 2 kn** vairāk nekā 1 h ≤ 2 km no kabeļa/caurules,
      vai tā kurss vairākkārt šķērso trasi. Sadaļa ar notikumiem (kuģis, karogs, laiks, attālums, ātrums). Tikai fakti.

## 4. Degviela un nafta
- [ ] **Degvielas cenas** LV/LT/EE/PL/FI katru nedēļu – EK Weekly Oil Bulletin (atvērts XLSX). Grafiks 52 nedēļas, ar/bez nodokļiem.
- [ ] **Brent cena** (atvērts avots bez atslēgas, piem. EIA atvērtie faili vai FRED CSV `DCOILBRENTEU`) – grafiks kopā ar degvielas cenām.
- [ ] **Naftas produktu imports pēc izcelsmes** (Eurostat API, `nrg_ti_oil` vai līdzīgs) LV/LT/EE – pēdējie 12 mēneši, valstis, produkti.
- [ ] **Naftas rezerves dienās** (Eurostat ārkārtas krājumi) LV/LT/EE.

## 5. Gāze – padziļināti
- [ ] Inčukalna vēsture: aizpildījums pa gadiem (pēdējie 5 gadi vienā grafikā, AGSI vēsture).
- [ ] Gāzes cena (atvērts avots, ja ir; citādi `[!]`).
- [ ] Lietuvas un Somijas patēriņš (ENTSOG punkti) – pievienot "cik dienām pietiek" tabulai.
- [ ] Porvo/Somijas ostu LPG/LNG kuģu ienākšanas pēc Fintraffic Digitraffic ostu apmeklējumiem (port calls) – skaits un aplēstais apjoms.

## 6. Kvalitāte
- [ ] Lapas ielādes ātrums: sadaļas, kas zem ekrāna, ielādēt slinki; pārbaudīt JSON izmērus.
- [ ] Navigācija: mazs satura rādītājs (saites uz sadaļām) lapas augšā; lapa sadalīta loģiski (Kopsavilkums → Karte → Nafta → Gāze → Elektrība → Kuģi → Avoti).
- [ ] Sadaļa "Avoti un metodes" lapas apakšā – visi avoti, licences, atjaunošanas biežums, kas ir aplēse.
