# Daten und Datenschutz

[Zur Projektseite](../README.md)

## Was lokal bleibt

PDF-Dateien werden aus ihrem lokalen Zotero-Pfad gelesen. Zitatlotse speichert Text-Chunks, Metadaten, Sprache, Themenmerkmale, Vektoren und gespeicherte Zitate in einer eigenen SQLite-Datei. Der Suchdienst verändert nicht direkt Zoteros Datenbank.

Embedding-Berechnung, BERTScore und Dokumentgrafik laufen lokal. Die direkte Suche benötigt keinen Cloud-Anbieter. Ein erster Download von Paketen oder Modellgewichten ist trotzdem eine Netzwerkverbindung; dabei wird die Query nicht für eine Suchauswertung an einen Zitatlotse-Server gesendet.

Die Datenbank enthält auch extrahierte Dokumenttexte und lokale Dateipfade. Sie ist durch Zitatlotse nicht zusätzlich verschlüsselt. Zugriffsschutz und Sicherung hängen vom Betriebssystem und deiner eigenen Umgebung ab.

## Was an einen KI-Anbieter gehen kann

Bei OpenAI, Anthropic oder DeepSeek werden deine Frage, Suchformulierungen und abgerufene Originalstellen an den gewählten Anbieter gesendet. Die einstufige Suche übergibt eine begrenzte Auswahl; mehrstufige Suche kann pro Schritt weitere Stellen und bisherige Werkzeugantworten im Kontext übertragen. Der Belegmodus kann viele abgerufene Kandidaten in mehreren Gruppen bewerten.

Ein Verbindungstest verwendet ebenfalls die ausgewählte API. Modellkataloge werden vom Anbieter geladen. Die jeweiligen Datenschutzbedingungen und API-Kosten sind vom Anbieter abhängig.

Ollama wird als lokaler HTTP-Server angesprochen. Seine Modelle müssen installiert sein. Zitatlotse betreibt keinen eigenen Cloud-Suchdienst und verlangt keinen eigenen Account.

## Schlüssel und Sitzungen

- API-Schlüssel: über `keyring` im Anmeldeinformationsspeicher des Betriebssystems.
- Verbindungseinstellungen ohne Schlüssel: lokale `settings.json`.
- Such-/Chatansichten: im Speicher der Zotero-Sitzung, je Bibliothek. Reset oder Zotero-Neustart leert sie.
- Gespeicherte Zitate und Notizen: dauerhaft in SQLite.
- Suchstände im Dienst: begrenzte Lebensdauer; nach Dienstneustart nicht wiederverwendbar.
- Aktivitätsansicht: konkrete Suchereignisse und Queries, keine privaten Modellgedanken.

## Lokale HTTP-Schnittstelle

Der Server bindet an `127.0.0.1:8765`. Schreib-/Suchanfragen verwenden den Client-Header `X-Zitatlotse-Client: 1`; dieser ist **kein geheimes Authentifizierungstoken**. Die Schnittstelle ist für den lokalen Benutzer gedacht und sollte nicht ins Netzwerk veröffentlicht werden.

## Öffentliche Fehlerberichte

Keine Datenbank, PDF-Dateien, Modellgewichte, Schlüssel, vollständigen Anbieterantworten oder unbereinigten Protokolle anhängen. Ein kleiner synthetischer Testfall mit Version, Modellen, Frage, Suchmodus, Bereich und anonymisierter Fehlermeldung ist vorzuziehen. Testausgaben können selbst Dokumenttexte enthalten und müssen vor Weitergabe überprüft werden.
