# PDF Translator RO

Aplicație Windows (Python + interfață grafică) care traduce automat fișiere PDF din orice limbă în
**limba română**, păstrând aspectul paginii. Este gândită pentru **fișe de catalog și fișe tehnice de
produse electrice**, unde exactitatea contează: codurile de produs, numerele, unitățile de măsură și
standardele nu au voie să se schimbe.

![Pictogramă](resources/icon.png)

## Ce face

| Funcție | Detalii |
|---|---|
| **Traducere cu aspect păstrat** | Textul original este scos din PDF și traducerea este pusă în aceeași casetă, cu aceeași mărime, culoare, îngroșare, aliniere și rotire. Imaginile, tabelele, fundalurile și liniile rămân intacte. |
| **Exactitate tehnică** | Înainte de traducere, numerele, unitățile (`16 A`, `2.5 mm²`, `-25 °C`), codurile de produs (`A9F74216`, `iC60N`, `IP20`), standardele (`IEC/EN 60898-1:2019`), adresele web/e-mail și simbolurile electrice (`Icu`, `Uimp`, `AC/DC`) sunt **protejate** și reintroduse neschimbate. După traducere, toate cifrele din sursă sunt comparate cu cele din traducere. |
| **Cuvânt cu cuvânt + corectare contextuală** | Pasul 1: traducere automată segment cu segment (Google / DeepL). Pasul 2 (opțional): **post-editare cu Claude**, care corectează sensul, gramatica, acordul și terminologia folosind contextul întregii pagini, fără să adauge sau să omită informații. |
| **Glosar tehnic** | Peste 300 de termeni electrotehnici (EN/DE/FR/IT/ES → RO) incluși, editabili din aplicație, cu import/export CSV. Termenii marcați „păstrează” (mărci, game de produse) nu se traduc. Termenii sunt transmiși motorului Claude și verificați în raport. |
| **DOCX bilingv** | Tabel sursă / traducere pentru fiecare segment, cu observațiile de verificare evidențiate – util pentru revizia umană. |
| **Raport de calitate (HTML)** | Lista segmentelor care trebuie verificate manual: numere diferite, marcaje pierdute, termeni de glosar neaplicați, text micșorat mult. |
| **PDF comparativ** | Opțional, paginile originale și cele traduse alternate în același fișier. |
| **Memorie de traducere** | Segmentele identice („Rated current”, „Order no.”) se traduc o singură dată, consecvent, și se refolosesc între fișiere. |
| **Linie de comandă** | `PDFTranslatorRO.exe fisa.pdf --engine deepl --post-edit` pentru procesare în lot. |

### Motoare de traducere

| Motor | Cost | Cheie API | Observații |
|---|---|---|---|
| **Google Translate (gratuit)** | gratuit | nu | Prin biblioteca `deep-translator`. Bun pentru volume mici/medii; la volume mari Google poate limita temporar cererile (aplicația reîncearcă automat; se poate seta o pauză între cereri). |
| **DeepL** | plan Free: 500.000 caractere/lună | da – [deepl.com/pro-api](https://www.deepl.com/pro-api) | Calitate foarte bună pentru limbile europene. Dacă limba sursă este cunoscută, glosarul este trimis și către DeepL. |
| **Claude (Anthropic)** | plată pe utilizare | da – [platform.claude.com](https://platform.claude.com/) | Traducere directă cu înțelegerea contextului tehnic, sau **post-editare** peste Google/DeepL (recomandat pentru cea mai bună calitate). Modele: `claude-sonnet-5-5` (implicit), `claude-haiku-5-5` (mai ieftin), `claude-opus-5-5`. |
| Test | – | nu | Nu traduce; servește la verificarea păstrării aspectului. |

> Recomandare pentru fișe tehnice: **DeepL sau Google + post-editare Claude**. Primul pas dă traducerea literală, al doilea corectează frazele și terminologia în context, iar protejarea tokenilor garantează că datele tehnice rămân identice.

## Instalare rapidă (utilizator)

1. Deschide pagina **Releases** a depozitului GitHub și descarcă `PDFTranslatorRO.exe` (sau ia fișierul din **Actions → ultimul build → Artifacts**).
2. Rulează executabilul. Nu necesită instalare și nu are nevoie de Python.
3. La prima pornire Windows SmartScreen poate avertiza că aplicația nu este semnată: **Mai multe informații → Rulează oricum**.
4. În tab-ul **Setări** introdu cheile API (dacă folosești DeepL/Claude) și apasă **Testează motorul selectat**.
5. În tab-ul **Traducere**: adaugă PDF-urile, alege motorul și rezultatele dorite, apasă **Traduce**.

Rezultatele se salvează lângă fișierul sursă (sau în folderul ales):

```
fisa.pdf
fisa_RO.pdf              <- PDF tradus, cu aspect păstrat
fisa_RO_bilingv.docx     <- tabel sursă / traducere pentru verificare
fisa_RO_raport.html      <- segmente de verificat manual
fisa_RO_comparativ.pdf   <- (opțional) pagini original/traducere alternate
```

Setările, glosarul utilizatorului și memoria de traducere se păstrează în
`%APPDATA%\PDFTranslatorRO\` (buton „Deschide folderul de configurare” în Setări).

## Cum se construiește executabilul prin GitHub (pas cu pas)

Depozitul conține un workflow GitHub Actions (`.github/workflows/build-windows.yml`) care construiește
automat `PDFTranslatorRO.exe` pe un server Windows, fără să ai nevoie de Python pe calculatorul tău.

1. Creează un cont pe [github.com](https://github.com) și un depozit nou (de ex. `pdf-translator-ro`), public sau privat.
2. Încarcă toate fișierele acestui proiect în depozit (prin **Add file → Upload files** sau cu `git`).
   Atenție: folderul `.github` este ascuns în Windows Explorer și poate fi omis la încărcarea prin
   browser – verifică după încărcare că `.github/workflows/build-windows.yml` există în depozit
   (altfel creează-l din **Add file → Create new file**, lipind conținutul). Cu `git` nu există problema:
   ```bash
   git init
   git add .
   git commit -m "PDF Translator RO"
   git branch -M main
   git remote add origin https://github.com/UTILIZATOR/pdf-translator-ro.git
   git push -u origin main
   ```
3. La fiecare `push` pe `main`, GitHub rulează testele și construiește executabilul. Intră în tab-ul
   **Actions**, deschide ultima rulare și descarcă artefactul **PDFTranslatorRO-windows** (un .zip cu .exe).
   Poți porni manual un build și din **Actions → Build Windows executable → Run workflow**.
4. Pentru a publica o versiune descărcabilă de oricine, creează un tag de forma `v1.0.0`:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
   Workflow-ul atașează automat `PDFTranslatorRO.exe` la o pagină **Release**.

> Observație: `permissions: contents: write` din workflow este necesar pentru publicarea Release-urilor.
> Dacă depozitul este într-o organizație, verifică în **Settings → Actions → General** că workflow-urile au drept de scriere.

## Rulare din sursă / dezvoltare

Necesită Python 3.10+ (pe Windows, instalatorul oficial include Tkinter).

```bash
pip install -r requirements.txt
python main.py                     # interfața grafică
python -m tests.test_units         # teste unitare (fără internet)
python -m tests.test_pipeline      # test complet pe un PDF generat (fără internet)
```

Pe Windows poți folosi `run_dev.bat` (creează un mediu virtual și pornește aplicația) și `build.bat`
(construiește local executabilul cu PyInstaller, în `dist\PDFTranslatorRO.exe`).

### Linie de comandă

```bash
python main.py fisa.pdf                                    # setările salvate, rezultat lângă fișier
python main.py *.pdf --out D:\traduse --engine deepl --post-edit
python main.py fisa.pdf --engine claude --lang de --no-docx --compare
```

## Cum funcționează (pe scurt)

1. **Extragere** – fiecare pagină este citită cu PyMuPDF la nivel de caracter. Liniile sunt despărțite
   în celule acolo unde există spații mari sau linii verticale de tabel; liniile unui paragraf sunt
   unite într-un singur segment (context mai bun), iar elementele de listă rămân separate.
2. **Protejare** – tokenii tehnici sunt înlocuiți cu marcaje `⟦0⟧, ⟦1⟧ …`. Segmentele fără text de
   tradus (doar coduri/numere) nu sunt atinse și își păstrează fontul original.
3. **Traducere** – segmentele unice ale fiecărei pagini sunt trimise în loturi motorului ales; memoria
   de traducere evită repetițiile.
4. **Post-editare** (opțional) – Claude primește pentru fiecare segment sursa și traducerea brută, plus
   glosarul relevant, și returnează versiunea corectată; rezultatul este acceptat doar dacă păstrează
   toate marcajele.
5. **Verificare** – marcajele sunt restaurate; dacă un motor a pierdut un marcaj, segmentul este
   retradus fără protejare și semnalat. Cifrele sursă/țintă sunt comparate; termenii din glosar sunt
   verificați.
6. **Reconstrucție** – textul original este eliminat prin redactare (fără a acoperi fundalul), iar
   traducerea este inserată cu fontul DejaVu Sans (diacritice complete), micșorată automat doar cât
   este nevoie; casetele se pot extinde în spațiul liber din dreapta/jos, deoarece româna este cu
   15–25 % mai lungă decât engleza.

## Limitări cunoscute

- **PDF-uri scanate** (imagini fără strat de text) nu pot fi traduse; paginile respective sunt
  semnalate în raport. Aplică OCR înainte (de ex. cu Adobe Acrobat sau `ocrmypdf`).
- Textul din **imagini**, diagrame rasterizate sau grafică vectorială convertită în contururi nu este
  detectat ca text și rămâne în limba originală.
- Casetele foarte strâmte (celule de tabel înguste) pot primi text micșorat; segmentele micșorate sub
  pragul din Setări apar în raport.
- Google Translate gratuit nu are garanții de disponibilitate; pentru lucru intensiv folosiți DeepL/Claude.
- Nicio traducere automată nu este perfectă: pentru documente oficiale, verificați DOCX-ul bilingv și
  raportul. Aplicația este construită ca să facă această verificare rapidă, nu ca să o înlocuiască.

## Structura proiectului

```
main.py                         punct de intrare (GUI sau linie de comandă)
app/gui.py                      interfața grafică (tkinter)
app/pipeline.py                 fluxul complet pentru un fișier
app/pdf_extract.py              extragerea segmentelor cu informații de aspect
app/pdf_rebuild.py              redactare + reinserare text, PDF comparativ
app/protect.py                  protejarea tokenilor tehnici, verificarea cifrelor
app/engines.py                  Google / DeepL / Claude (traducere și post-editare)
app/glossary.py                 glosar (implicit + utilizator), CSV, verificare
app/tm_cache.py                 memoria de traducere (SQLite)
app/outputs.py                  DOCX bilingv, raport HTML
app/langdetect_lite.py          detectarea limbii sursă (fără dependențe)
app/config.py                   setări, căi, resurse
resources/glossary_default.json glosarul implicit
resources/fonts/                DejaVu Sans (licență inclusă)
tests/                          teste unitare și test complet pe PDF generat
.github/workflows/              build automat Windows (PyInstaller)
```

## Licență

Codul: MIT (vezi `LICENSE`). Fonturile DejaVu: licență proprie, inclusă în `resources/fonts/`.
Serviciile de traducere folosite (Google, DeepL, Anthropic) au propriile condiții de utilizare și costuri.
#   m m m m  
 