# Mitwirken

Danke für reproduzierbare Fehlerberichte und nachvollziehbare Verbesserungen. Das Projekt befindet sich im Prototypstadium.

## Lokaler Einstieg

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m unittest discover -s backend -p "test_*.py"
node test_plugin.js
node test_search_session.js
python package.py
```

Für tatsächliche Modellberechnung `backend/requirements.txt` verwenden. Für Zotero den Windows-Installer ausführen. [Testanleitung](docs/TESTING.md)

## Suchänderungen prüfen

Vor und nach einer Änderung denselben Fragenbestand verwenden. Positive Fälle, ein klar fachfremder Negativfall, andere Bibliothek und leere Sammlung müssen enthalten sein. KI-Änderungen auch mit einem echten genehmigten Anbieterablauf einschließlich Auswahl und Anzeige prüfen. Reine Mock-Tests beweisen keine Retrieval-Qualität.

Frage, Modus, Suchbereich, Modelle, Trefferzahl, ausgewählte Quellen, Laufzeit, Warnungen und Erfolg dokumentieren. Private Ergebnisse unter `outputs/` speichern und vor einer öffentlichen Zusammenfassung bereinigen. Keine Schlüssel, Rohantworten oder privaten Modellgedanken veröffentlichen.

Cloud-Läufe benötigen eine bewusste Entscheidung des ausführenden Nutzers für die konkreten Dokumente und möglichen Kosten. Bestehende Tests oder Autorisierung eines anderen Nutzers sind keine allgemeine Zustimmung zur Datenübertragung.

## Änderungen einreichen

- Kleine, verständliche Änderungen mit Anlass und Testnachweis einreichen.
- Datenbank-/Modelländerungen müssen vorhandene Zitate und Notizen erhalten oder eine ausdrückliche Migration anbieten.
- Bibliotheks- und Sammlungsgrenzen in allen Suchwegen wahren.
- Zusätzliche UI-Beschriftungen in Deutsch und Englisch ergänzen.
- Fehlerberichte mit Zotero-/Windows-/Addon-Version, reproduzierbaren Schritten und bereinigten Fehlermeldungen erstellen.
- Keine privaten PDFs, Indexdateien, Credentials oder Modellgewichte einchecken.

## Sicherheit

Für mögliche Credential-Leaks oder unerlaubte Datenübertragung siehe [SECURITY.md](SECURITY.md). Gewöhnliche Bugs können als Issue gemeldet werden. Dieses Projekt bietet derzeit keine garantierte Reaktionszeit.
