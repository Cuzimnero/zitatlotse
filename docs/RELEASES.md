# Release-Downloads

[Zur Projektseite](../README.md)

Das öffentliche Repository und erste Release sind derzeit **noch nicht veröffentlicht**. Die lokale Vorschau kann vorab geprüft werden.

## Geplante Dateien pro Release

| Datei | Inhalt |
| --- | --- |
| `Zitatlotse-0.27.0.xpi` | Installierbares Zotero-Add-on einschließlich Windows-x64-Python-Laufzeit, CPU-Bibliotheken und Backend. |
| `Zitatlotse-0.27.0-source.zip` | Bereinigter eigener Quellcode, Tests und Dokumentation. |
| `third-party-sources.zip` | Entsprechender unveränderter Quellcode der mitgelieferten AGPL-PDF-Bibliothek. |
| `SHA256SUMS.txt` | SHA-256-Prüfsummen der Downloads. |

Zur normalen Nutzung genügt die **XPI**. Quellcode-Archive sind für Entwicklung, Nachvollziehbarkeit und Lizenzrechte vorhanden.

## Veröffentlichung

Der manuell auslösbare Workflow **Build a draft release** baut und prüft das vollständige Paket. Er erstellt ausschließlich einen unveröffentlichten Vorab-Release-Entwurf. Die Dateien werden als Assets angehängt; die XPI ist nach Veröffentlichung direkt über den Release-Bereich downloadbar. Ein gewöhnlicher Push veröffentlicht kein Release.

Der angegebene Tag muss mit `plugin/manifest.json` übereinstimmen. Ein schon vorhandener Release wird nicht überschrieben. [Release-Text für 0.27.0](releases/v0.27.0.md)
