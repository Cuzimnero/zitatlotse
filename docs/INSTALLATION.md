# Installation und Updates

[Zur Projektseite](../README.md)

## Voraussetzungen

- Zotero **10.0.x** unter **Windows x64**.
- Lokal vorhandene PDFs mit lesbarem Text. Zitatlotse führt selbst keine OCR aus.
- Platz für die enthaltene CPU-Laufzeit und die gewählten Modelle.
- Internet beim erstmaligen Download eines Suchmodells.
- Optional: Ollama mit installiertem Modell oder eigener API-Schlüssel.

## Normale Installation: nur die XPI

1. **Zitatlotse-0.27.0.xpi** aus den [Releases](https://github.com/Cuzimnero/zitatlotse/releases) herunterladen. Das erste öffentliche Release ist noch in Vorbereitung.
2. In Zotero **Werkzeuge → Add-ons → Add-on aus Datei installieren** wählen und die XPI öffnen.
3. Zotero neu starten. Die Erweiterung richtet ihre mitgelieferte lokale Laufzeit im Benutzerprofil ein und startet den Suchdienst automatisch.
4. Das violette Symbol öffnen. Der Fortschrittsbalken zeigt Einrichtung, Prüfung und Start. Bei einer fehlgeschlagenen Einrichtung **Suchdienst prüfen** zum Wiederholen wählen.
5. Eine PDF oder einen Eintrag verarbeiten. Beim ersten Verarbeiten werden das gewählte Embedding-Modell und das BERTScore-Modell heruntergeladen.

**Keine separate Python-Installation, kein zusätzliches Installationsskript und kein manueller Dienststart.** Die XPI enthält Python, CPU-Bibliotheken und Backend-Code. Die Laufzeit wird aus dem installierten Add-on entpackt. Modelle bleiben wegen ihrer Größe und freien Auswahl separate Downloads.

Direkte Suche braucht keinen KI-Schlüssel. Für KI-Suche unter **Verbindungen** Anbieter und Modell wählen. Ollama selbst ist ein optionales externes Programm.

## Updates

Die neue XPI installieren und Zotero neu starten. Die Erweiterung erkennt die neue Backend-Version und aktualisiert ihren Code automatisch. Datenbank, Einstellungen, Modellcache und gespeicherte Zitate bleiben unter dem bisherigen Datenpfad erhalten. Ein Modellwechsel bietet zusätzlich einen bestätigten Neuaufbau der Embeddings an.

Die Anwendung startet während eines Code-Updates ihren eigenen Dienst neu. Deshalb ein Update nicht während einer laufenden Verarbeitung oder KI-Abfrage beginnen.

## Start und Wiederanlauf

- Start beim Laden der Erweiterung in Zotero.
- Erneute Prüfung beim Öffnen des Suchfensters oder bei einer unterbrochenen Verbindung.
- Ein gemeinsames Startversprechen verhindert doppelte Starts durch gleichzeitige UI-Anfragen.
- Während Zotero läuft: Erreichbarkeit alle 30 Sekunden prüfen und einen verlorenen Prozessbaum erneut starten.
- Der Supervisor startet einen abgestürzten Worker selbst neu.
- Eine fehlgeschlagene Einrichtung wird sichtbar gemeldet; **Suchdienst prüfen** startet einen neuen Versuch.

Die normale Installation benötigt keine Windows-Aufgabe und keine Administratorrechte. Der alte manuelle Installer bleibt als Entwickler-/Legacy-Weg im Quellcode erhalten. Eine bereits früher eingerichtete Windows-Aufgabe wird durch die XPI nicht automatisch gelöscht.

## Pfade und Diagnose

| Inhalt | Ort unter `%USERPROFILE%\.zitatlotse` |
| --- | --- |
| Mitgelieferte Python-Laufzeit | `runtime\<Paketkennung>` |
| Installierte Version und Startpfade | `installation.json` |
| Einrichtungsfortschritt | `setup-state-0.27.0.json` |
| Index und gespeicherte Zitate | `backend\data\quotes.sqlite` |
| Modellcache | `backend\data\models` |
| Einstellungen ohne Schlüssel | `backend\data\settings.json` |
| Prüfung der Laufzeit | `runtime-check.log`, `runtime-error.log` |
| Dienstprotokoll | `backend\data\service.log` |

Schlüssel liegen im Betriebssystem-Anmeldeinformationsspeicher. Diagnoseprotokolle und Datenbanken nicht ungeprüft öffentlich teilen.

Ein erfolgreicher Health-Check bestätigt einen laufenden Dienst. Die Modelle werden anschließend bei Bedarf geladen; die erste Suche kann deshalb länger dauern.

## Release selbst bauen

Nur Entwickler benötigen Python und Node.js:

```powershell
python build_runtime.py
python package.py
```

Der Windows-Build lädt das offizielle, per SHA-256 geprüfte eingebettete Python und die Bibliotheken, prüft ihre Imports und erstellt die komplette XPI. Paketversionen und Lizenzdateien liegen in der enthaltenen Laufzeit. `python package.py --source-only` erstellt nur das Quellcode-Archiv. Ein Oberflächenpaket ohne Laufzeit wird nicht als fertige Release-XPI gebaut.

Andere Betriebssysteme sind mit dieser Distribution noch nicht als vollständiger Installationsweg unterstützt.
