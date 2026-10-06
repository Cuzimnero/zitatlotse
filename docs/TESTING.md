# Tests ausführen

[Zur Projektseite](../README.md) · [Aktueller Teststand](STATUS.md)

## 1. Isolierte Tests ohne KI-Kosten

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s backend -p "test_*.py"
node test_plugin.js
node test_search_session.js
node test_runtime.js
python package.py --source-only
```

Diese Tests nutzen temporäre/synthetische Daten, simulierte Encoder oder Anbieterantworten. Sie prüfen Logik und Fehlerfälle, nicht die tatsächliche Qualität eines Modells. Node.js wird für die Plugin-Tests benötigt. Die Windows-CI führt dieselben Prüfungen aus und lädt keine Modellgewichte. Ein vorab veröffentlichter CI-Erfolg ist damit noch nicht vorhanden.

## XPI-Einrichtung auf einem PC ohne Python im Suchpfad

```powershell
python build_runtime.py
python package.py
.\test_runtime_setup.ps1 -Xpi .\dist\Zitatlotse-0.27.0.xpi -TestRoot .\outputs\runtime-test -Port 18765
```

Die Prüfung richtet die enthaltene Laufzeit in einem separaten Testordner ein, entfernt Python aus dem Suchpfad und verbietet Modell-Downloads. Sie prüft reale Dienstverfügbarkeit, Fortschritt, vollständigen Prozessverlust mit erneutem Start und Erhalt der Testdatenbank. Sie berührt die normale Installation auf Port 8765 nicht und führt keine Cloud-Abfrage aus. Ein tatsächlicher OS-Neustart wird damit nicht ausgeführt.

## 2. Echte lokale Modelle mit synthetischen PDFs

Mit vollständigen Backend-Abhängigkeiten:

```powershell
python -m pip install -r backend\requirements.txt
python backend\smoke_model_catalog.py intfloat/multilingual-e5-small
```

Das Skript erzeugt synthetische PDFs und einen temporären Index. Es prüft echte Modellberechnung, Fundort, Bibliotheksgrenzen, fachfremde Anfrage und erneutes Laden des Index. Fehlende Modellgewichte werden heruntergeladen. `HF_HOME` kann auf einen vorhandenen Cache zeigen; `HF_HUB_OFFLINE=1` verhindert Downloads, falls alle nötigen Gewichte schon vorhanden sind.

Für ein echtes eigenes Embedding-Modell mit synthetischer Datenbank:

```powershell
python backend\smoke_custom_embedding.py --cache .\outputs\model-cache --output .\outputs\custom-model.json
```

Dieses Skript verwendet einen festgelegten kleinen Hugging-Face-Testencoder und eine isolierte Datenbank. Es ersetzt nicht den Modellwechsel in einer realen Nutzerbibliothek.

## 3. Echte KI-Suchläufe

`backend/smoke_ai_search.py` verwendet den **konfigurierten Anbieter** des laufenden Dienstes und kann Dokumenttexte übertragen sowie Kosten verursachen. Nur bewusst ausgewählte Testdokumente verwenden. `--live` ist zwingend.

```powershell
python backend\smoke_ai_search.py --live --library 1 --case dino_teacher --case unrelated --attachment-key YOUR_DINO_KEY --output .\outputs\ai-search.json
```

`YOUR_DINO_KEY` durch den Schlüssel deines verarbeiteten DINO-PDF-Anhangs ersetzen. Die Beispielanfragen erwarten passende DINO-/MiVOLO-/Distillations-Papers; sie sind für eine beliebige Bibliothek kein gültiger Positivtest. Für andere Dokumente neue geprüfte Fälle erstellen.

Für einen UI-Replay des echten Ergebnisses:

```powershell
$env:ZITATLOTSE_LIVE_REPORT = '.\outputs\ai-search.json'
node test_search_session.js
Remove-Item Env:\ZITATLOTSE_LIVE_REPORT
```

Der Bericht kann Originaltexte und Quellenkennungen enthalten. Er ist absichtlich von Git ausgeschlossen und darf nicht ungeprüft veröffentlicht werden. Der Replay verwendet die ausgelieferte UI-Logik in einem simulierten Dokumentbaum, nicht ein echtes Zotero-Fenster.

## 4. Windows-Kaltstarts und Ausfälle

Diese Tests **unterbrechen den installierten Zitatlotse-Dienst** und stellen ihn abschließend wieder her. Sie können minutenlang dauern. Keine eigene Verarbeitung parallel laufen lassen.

```powershell
.\smoke_autostart.ps1 -ColdCycles 3 -TestEarlyCrash -Output .\outputs\cold-start.json
```

Vollständigen Prozessausfall nach automatischer Aufgaben-Ausführung prüfen:

```powershell
.\smoke_autostart.ps1 -SupplementaryOnly -TestSchedulerRecovery -TestScheduledTrigger -Output .\outputs\whole-service-failure.json
```

**Der aktuelle Stand besteht den automatischen Wiederanlaufteil dieses Tests nicht.** Eine separate einmalige Zeitaufgabe wird für die Prüfung erstellt und anschließend entfernt. Der echte PC wird nicht neu gestartet.

Optionale direkte Suche nach Kaltstart mit den eigenen Test-PDFs:

```powershell
.\smoke_autostart.ps1 -SupplementaryOnly -TestLocalSearch -LibraryId 1 -DinoAttachmentKey YOUR_DINO_KEY -TestAttachmentKeys YOUR_DINO_KEY,YOUR_MIVOLO_KEY,YOUR_DISTILLATION_KEY -Output .\outputs\cold-search.json
```

Die Schlüssel beziehen sich auf die **eigenen** indizierten Zotero-Anhänge. Es sind keine persönlichen Schlüssel im Skript hinterlegt. `Average` muss im Testbestand vorkommen; der klinische Negativfall darf dort keine passende Literatur haben.

## 5. Native Zotero-Prüfung

Zusätzlich manuell prüfen:

- XPI installieren und Zotero neu starten.
- Nur ein funktionierendes Symbol rechts; Öffnen/Schließen und kleiner Fensterbereich.
- Dropdowns für Modus, Sammlung und Modell schließen das Fenster nicht unbeabsichtigt.
- Verarbeitung einer PDF, eines Eintrags und aller neuen/geänderten PDFs.
- Direkte, KI- und Pro-/Kontra-Suche im richtigen Bereich.
- Doppelklick auf eine Originalstelle: passende Seite und Hervorhebung.
- Zitierstil, Speichern, Notiz, Suchzeile und Kopieren.
- Schließen/Öffnen erhält den Verlauf; Reset und Zotero-Neustart leeren temporäre Ansichten.
- Modellwechsel bestätigen, erfolgreiche Aktivierung und Fehlerfall mit altem Index prüfen.
- Echten Windows-Neustart mit Anmeldung ausführen und Dienstbereitschaft sowie erste Suche getrennt messen.

Diese Liste beschreibt erforderliche Prüfungen, keine pauschale Bestätigung bereits bestandener nativer Tests.
