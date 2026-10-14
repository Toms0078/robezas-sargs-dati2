# Robežas sargs – enerģētikas uzraudzības rīks (vadlīnijas aģentiem)

Šis fails ir **galvenās vadlīnijas** ikvienai Claude sesijai, kas strādā šajā repozitorijā.
Lietotājs (Toms, Latvija, strādā Sadales tīklā) vēlas, lai rīks tiktu attīstīts **patstāvīgi, bez viņa iesaistes**.
Neprasi viņam apstiprinājumu ikdienas lēmumiem – pieņem saprātīgāko lēmumu un ieraksti to `LOG.md`.

## Kas tas ir
- Lapa: `butinge/index.html` → https://toms0078.github.io/robezas-sargs-dati2/butinge/ (GitHub Pages, zars `main`).
- Viens HTML fails ar iebūvētu JS/CSS, Leaflet 1.9.4 (unpkg). Dati – JSON faili `data/…`, ko vāc Python skripti GitHub Actions.
- Esošās tēmas: Būtiņģes SPM boja un jēlnafta, tankkuģi/gāzes kuģi Baltijā (AIS), Krievijai piesaistītie/sankciju tankkuģi,
  LNG termināļi (ALSI), pazemes gāzes krātuves (AGSI), gāzesvadu plūsmas (ENTSOG), SAR satelītu radars (GFW), Dānijas šaurumi.

## Aģenti (`.claude/agents/`)
- **produkta-vaditajs** – izlemj, ko būvēt, un dod precīzu uzdevumu (datu avots, kas lapā, pieņemšanas kritēriji). Izsauc darba sākumā.
- **dizaina-recenzents** – pārbauda gatavo darbu (izskats, telefons, godīgums, CLAUDE.md) un dod labojumu sarakstu. Izsauc pirms commit.
Izpildītājs (galvenā sesija) seko vadītāja uzdevumam un izlabo visus recenzenta "obligātos labojumus".
Aģenti **paši uzlabo savas instrukcijas** pēc pieredzes (sk. `.claude/agents/macibas.md`); pamatnoteikumi nav maināmi.

## Darba kārtība katrā sesijā
1. `git pull --rebase origin main`. Izlasi `ROADMAP.md` un `LOG.md` beigas.
2. Izsauc **produkta-vaditajs**, lai saņemtu nākamo uzdevumu (parasti pirmais neizdarītais `ROADMAP.md` punkts). Vienā sesijā – 1 punkts, labi pabeigts.
3. Izveido: datu skriptu (`*.py`), darbplūsmu (`.github/workflows/*.yml`), lapas sadaļu un, ja der, kartes slāni.
4. **Pārbaudi** (sk. zemāk). Tad izsauc **dizaina-recenzents** (iedod izmaiņoto failu sarakstu un ekrānuzņēmumu ceļus) un izlabo obligātos labojumus.
5. Commit + push. Atzīmē punktu `ROADMAP.md` kā `[x]`, ieraksti `LOG.md`: datums, kas izdarīts, kas palika, problēmas.
6. Ja punkts nav izdarāms (nav pieejas, vajag atslēgu), atzīmē `[!]` ar iemeslu un ņem nākamo.

## Git
- Commit: `git -c user.name="Toms0078" -c user.email="toms.calitis@gmail.com" commit -m "…"`, ziņa latviski, beigās:
  ```
  Co-Authored-By: Claude <noreply@anthropic.com>
  ```
- Push: `git pull -q --rebase origin main && git push -q origin HEAD:main` (botu darbplūsmas komitē paralēli – vienmēr rebase).
- Darbplūsmas palaiž ar REST: `gh api -X POST repos/Toms0078/robezas-sargs-dati2/actions/workflows/<fails>.yml/dispatches -f ref=main`
  (GraphQL nav pieejams). Logus lasi no failiem, ko darbplūsma ieraksta repozitorijā (`data/<tēma>/last_run.log`).
- Nekad nedzēs esošās sadaļas, datus vai darbplūsmas. Nekad neizmanto `--force`.

## Tīkls un dati
- Sesijas čaulai ārējais tīkls lielākoties **bloķēts** (atļauts GitHub, pip). Datu avotus testē **caur GitHub Actions**
  (pievieno `--test` režīmu, kas izdrukā atbildes struktūru logā).
- Tikai **bezmaksas un atļauti** avoti ar oficiālu API vai atvērtiem datiem. **Nekādas** MarineTraffic/VesselFinder u.c. vietņu
  nolasīšanas. Ievēro licences un norādi avotu lapā.
- Atslēgas tikai GitHub Secrets: `AISSTREAM_API_KEY`, `VESSELAPI_KEY` (150 pieprasījumi/mēn.), `GFW_TOKEN`, `AGSI_KEY` (der arī ALSI).
  Ja vajag jaunu atslēgu (piem. ENTSO-E), izmanto avotu bez atslēgas, ja tāds ir; citādi atzīmē `[!] vajag atslēgu X` un ieraksti
  `LOG.md` sadaļā "Lietotājam" īsu instrukciju, kur reģistrēties.
- Darbplūsmas: cron ar nobīdītu minūti (ne :00), `concurrency`, `permissions: contents: write`, logs `tee` uz repozitoriju,
  commit tikai `data/<tēma>`. Bezmaksas GitHub cron kavējas – nevajag biežāk par ~1 h (izņemot esošo `butinge.yml` cilpu).

## Lapas izskats (obligāti)
- **Valoda: latviski**, vienkārši, īsi. Skaitļi `toLocaleString('lv-LV')`. Datumi lv formātā.
- Katram skaitlim – **avots un datums**. Aplēses/simulācijas vienmēr atzīmē vārdiem "aplēse"/"simulācija".
- Krāsas: nafta `#c2410c`/`#7c4a1e`, LNG `#0e7490`, pazemes krātuves `#4d7c0f`, gāzes kuģi `#7c3aed`, Krievija/sankcijas sarkans
  `#b91c1c`, LPG `#a16207`, bez datiem pelēks `#9ca3af`, boja `#d61f69`. Elektrībai izmanto dzeltenu/zeltainu `#ca8a04`.
- Lieto esošās CSS klases: `.panel`, `.note`, `.tw`+`table`, `.chips/.chip`, `.live`, `.kpis/.kpi`, `.tank`, `.mbars`, `.cbar`.
  Krāsas tikai caur CSS mainīgajiem (`--panel`, `--ink`, `--muted`, `--line`, `--lbl`), lai strādā gaišais un tumšais režīms.
- Kartes uzraksti: puscaurspīdīgs fons `var(--lbl)`, bez ēnām. Kartes slāņi – pogas zem kartes (`MAP_LAYERS` objekts), nevis Leaflet kontrole.
- Karogi tikai ar `emojiOf(cc)` (SVG no `butinge/flags/`), nevis emocijzīmes.
- Kuģu emblēmas ar `shipIcon(kind,color,rot)`. Animētas plūsmas ar klasi `.gflow`/`.flow` (cieņa `prefers-reduced-motion`).
- Jāstrādā **telefonā** (360–420 px platums, bez horizontālas ritināšanas, izņemot tabulas `.tw` iekšā) un datorā.
- Jaunas sadaļas – `<section class="panel" id="…">` ar `<h2>`, īss skaidrojums `.note`, tad saturs. Neliec vairāk par vienu grafiku sadaļā bez vajadzības.
- Lapa nedrīkst kļūt lēna: dati JSON < ~1 MB katrs, kartē ne vairāk par dažiem simtiem marķieru vienā slānī.

## Pārbaude pirms commit
- `node --check` uz izvilkto `<script>` saturu.
- Headless Playwright (Chromium ir `/opt/pw-browsers`): `python3 -m http.server 8765` repozitorija saknē, Leaflet aizstāj ar lokālu kopiju
  (lejupielādē no GitHub release `Leaflet/Leaflet` v1.9.4 zip), flīzes var bloķēt. Bez `pageerror`. Ekrānuzņēmumi 1250 px un 400 px platumā.
- Pārbaudi, ka visas esošās sadaļas joprojām ielādējas (nav "Cannot access … before initialization" u.tml.).

## Drošība un godīgums
- Nekādu personu datu par privātpersonām. Kuģi, uzņēmumi, infrastruktūra – jā.
- Nespekulē par nodomiem (piem. "sabotāža") – raksti faktus: "kuģis stāvēja X h virs kabeļa, ātrums < 1 kn".
- Ja kaut kas salūzt, atgriez iepriekšējo strādājošo versiju (`git revert`), ieraksti `LOG.md`.
