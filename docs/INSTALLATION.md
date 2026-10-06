# Installation und Updates

[Zur Projektseite](../README.md)

## Voraussetzungen

- Zotero **10.0.x**; das Manifest erlaubt derzeit genau diese Hauptversion.
- Windows für den mitgelieferten Installer und automatischen Dienststart.
- Python **3.10+** als normale lokale Installation. Paketverfügbarkeit für die konkrete Python-Version prüfen.
- Lokal vorhandene PDFs mit lesbarem Text. Zitatlotse führt selbst keine OCR aus.
- Internet für Python-Pakete und erstmalige Modell-Downloads; Arbeitsspeicher und Speicherplatz passend zum gewählten Encoder.
- Optional: laufendes Ollama mit installiertem Modell oder ein API-Schlüssel des gewählten Cloud-Anbieters.

## Lokalen Dienst installieren

Repository herunterladen und vollständig entpacken. Im Projektordner:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-Zitatlotse.ps1
```

Wird Python nicht gefunden, eine konkrete Installation angeben:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-Zitatlotse.ps1 -Python "C:\Pfad\zu\python.exe"
```

Der Installer richtet `%USERPROFILE%\.zitatlotse\backend` ein, erstellt die Python-Umgebung und installiert `backend/requirements.txt`. Die Modelle werden bei ihrer ersten Verwendung geladen. Dies kann Zeit und zusätzlichen Speicherplatz brauchen.

Die Windows-Aufgabe **Zitatlotse Search Service** startet den Launcher nach der Anmeldung des aktuellen Benutzers mit zehn Sekunden Verzögerung. Der Installer prüft anschließend, ob der lokale Dienst antwortet. Bei fehlgeschlagener Aufgabenregistrierung wird ein Benutzer-Autostart eingerichtet.

## XPI installieren

Im Projektordner:

```powershell
python package.py
```

Das erzeugt `dist\Zitatlotse-0.26.3.xpi` sowie ein bereinigtes Quellcode-Archiv. In Zotero **Werkzeuge → Add-ons → Add-on aus Datei installieren** wählen und die XPI öffnen. Zotero neu starten.

Eine XPI enthält nur das Add-on. Sie installiert den Python-Dienst nicht allein. Der vollständige Quellcode und der Installer werden deshalb zusätzlich benötigt.

## Erste Nutzung

1. In Zotero Bibliothek und PDF-Anhang oder Literatur-Eintrag wählen.
2. Im Eintragsbereich **Diese PDF verarbeiten** beziehungsweise **Diesen Eintrag verarbeiten** wählen; alternativ neue/geänderte PDFs der Bibliothek verarbeiten.
3. Das violette Zitatlotse-Symbol rechts öffnen.
4. Für direkte Suche ist kein KI-Schlüssel nötig.
5. Unter **Verbindungen** optional Anbieter und Modell wählen, Schlüssel eingeben oder Ollama verbinden, speichern und testen.
6. Unter **Einstellungen** Zitierstil, Embedding-Modell, mehrstufige Suche und Aktivitätsanzeige konfigurieren.

## Update

Die neue vollständige Quellcode-Version entpacken, den Installer erneut ausführen, die neue XPI installieren und Zotero neu starten. Datenbank und Modellcache unter der festen Installation bleiben erhalten. Ein gewöhnliches Backend-Update ersetzt nicht automatisch alle Embeddings; ein Modellwechsel bietet hierfür einen bestätigten Neuaufbau an.

Vor umfangreichen Änderungen eine Sicherung der eigenen Daten anlegen. Zum konsistenten Kopieren einer SQLite-Datei muss der Dienst beendet sein oder eine SQLite-Backup-Funktion verwendet werden. Eine alte Kopie bei laufender Schreibaktivität ist keine verlässliche Sicherung.

## Pfade und Diagnose

| Inhalt | Ort unter `%USERPROFILE%\.zitatlotse` |
| --- | --- |
| Python-Umgebung | `backend\.venv` |
| Index und gespeicherte Zitate | `backend\data\quotes.sqlite` |
| Modellcache | `backend\data\models` |
| Einstellungen ohne Schlüssel | `backend\data\settings.json` |
| Installationsprotokoll | `backend\data\setup.log` |
| Dienstprotokoll | `backend\data\service.log` |

Schlüssel liegen im Betriebssystem-Anmeldeinformationsspeicher, nicht in der Tabelle oben. Diese Dateien gehören nicht in öffentliche Fehlerberichte.

Den Dienst manuell starten:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.zitatlotse\Start-Zitatlotse.ps1"
```

Erreichbarkeit prüfen:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8765/health'
```

Eine erfolgreiche Antwort bestätigt den laufenden HTTP-Dienst. Sie bestätigt keine bereits abgeschlossene Modellinitialisierung. Die erste Suche kann deutlich länger brauchen.

## Entwicklung ohne Windows-Installation

Für die Arbeit am Backend kann es im Quellcode-Ordner manuell gestartet werden:

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
backend\.venv\Scripts\python.exe backend\launcher.py --supervise
```

Dies ersetzt nicht den Windows-Autostart. Für eine produktive Nutzung mit Zotero ist der feste Installationspfad vorgesehen. Andere Betriebssysteme sind für diese Distribution nicht als vollständiger Installationsweg geprüft.

## Bekannte Startprobleme

Der Launcher kann einen abgestürzten Worker neu starten. Beim vollständigen Ausfall beider Prozesse hat die Windows-Aufgabe im letzten Test keinen automatischen Wiederanlauf innerhalb von 100 Sekunden ausgelöst. Das Menü kann den installierten Dienst erneut starten. Ein tatsächlicher Windows-Neustart ist noch zusätzlich zu prüfen. Siehe [aktueller Teststand](STATUS.md).
