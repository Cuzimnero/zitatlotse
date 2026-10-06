# Alle Funktionen

[Zur Projektseite](../README.md)

Stand: **0.26.3**. Die folgende Liste beschreibt implementierte Funktionen. Ihr Vorhandensein ist keine Zusage, dass alle Kombinationen von PDFs, Modellen und Zotero-Versionen bereits zuverlässig getestet sind. Siehe [Teststand](STATUS.md).

## 1. Zotero-Oberfläche

- Ein violettes Anführungszeichen-Symbol in der rechten Leiste öffnet die KI-Suche.
- Ein eigener Zitatlotse-Menüpunkt bietet Zugriff auf Suche, Verbindungen und Verarbeitung.
- Zentrale Ansichten für KI-Suche, direkte Suche, gespeicherte Zitate, Verbindungen und Einstellungen.
- Deutsch und Englisch; Auswahl nach der eingestellten Zotero-Sprache, sonst Englisch.
- Mittiges, an die Fenstergröße angepasstes Suchfenster.
- Öffnungsanimation vom Einstiegssymbol aus; beim erneuten Anklicken umgekehrte Schließanimation.
- Schließen über X oben rechts, Escape oder den Hintergrund.
- Hervorgehobener Rahmen des KI-Chatbereichs; violette Hauptgestaltung.
- Animierte Fortschrittsanzeigen für Suche, Verarbeitung und Verbindungen; blätternde PDF-Seiten unter dem Fragefeld.

## 2. PDFs verarbeiten

- **Diese PDF verarbeiten:** den ausgewählten PDF-Anhang indizieren.
- **Diesen Eintrag verarbeiten:** die PDFs des ausgewählten Literatur-Eintrags indizieren.
- **Alle neuen/geänderten PDFs verarbeiten:** den Bestand der ausgewählten Bibliothek prüfen und fehlende oder geänderte Anhänge verarbeiten.
- Neu hinzugefügte PDF-Anhänge automatisch zur Verarbeitung einreihen.
- Bibliothek, Eintrags- und Anhangskennung, Titel, Autoren, Jahr, Sprache, Sammlungen und PDF-Fundorte dem lokalen Index zuordnen.
- Sprache aus dem Zotero-Feld übernehmen; sonst aus dem Text schätzen.
- Hinweise auf nicht lokal vorhandene oder nicht auslesbare Dateien anzeigen.
- Anzahl verarbeiteter PDFs und erzeugter Chunks sowie Fortschritt des Bibliotheksscans anzeigen.

## 3. Chunks und automatische Themenmerkmale

- PDF-Seiten einzeln auslesen und Leerraum vereinheitlichen.
- Chunks mit höchstens 100 Wörtern und bis zu 20 Wörtern Überlappung erzeugen.
- Möglichst an Satzgrenzen teilen; lange Einzelsätze bei Bedarf innerhalb des Satzes trennen.
- Chunks überschreiten keine PDF-Seitengrenze.
- Bis zu 16 Themenmerkmale je Dokument aus Inhaltswörtern, Wortpaaren und Zotero-Titel erzeugen.
- Normalisierten Mittelwert der Chunk-Vektoren als Themenvektor speichern.
- Merkmale, Metadaten, Text, normalisierte Vektoren und später gespeicherte Zitate in einer eigenen SQLite-Datenbank halten.

Die Themenmerkmale sind ein automatisch erzeugtes lokales Suchhilfsmittel. Sie sind keine vom LLM geprüfte Inhaltszusammenfassung.

## 4. Suchbereich

- Jede Suche verwendet genau eine Zotero-Bibliothek.
- Sammlung auswählen; Untersammlungen einschließen.
- Die aktuellen zugehörigen PDF-Anhänge aus Zotero übernehmen und im Dienst als feste Auswahl prüfen.
- Explizit leere Auswahl liefert einen leeren Bereich und wird nicht zur gesamten Bibliothek erweitert.
- Direkte Suche, KI-Suche, Tool Calls und Dokumentgrafik verwenden denselben gewählten Suchbereich.
- Bei Wechsel des Bereichs laufende Abfragen abbrechen beziehungsweise verspätete Antworten verwerfen.
- Suchstände dürfen nicht in eine andere Bibliothek oder abweichende Dateiauswahl übernommen werden.

## 5. Direkte Suche

- Ohne Cloud-LLM ausführen: sehr grobe Themenvorauswahl, danach Cosinus-Vergleich aller verbleibenden Chunks und BERTScore-Reranking.
- Kurze Begriffe, Akronyme und passende wörtliche Anfragen unabhängig von Groß-/Kleinschreibung behandeln.
- Verschiedene tatsächliche Fundorte eines Wortes erhalten.
- Wiederholte Originalstellen aus überlappenden Chunks bereinigen.
- Lokal als zu schwach bewertete Treffer verwerfen.
- Zitate mit Paper-Titel, PDF-Seite, Originaltext und Suchwerten anzeigen.
- Ergebnisse in Seiten mit höchstens 20 Zitaten aufteilen.
- Bereits geladene Seiten wieder öffnen; Suchstand im Dienst bis zu 15 Minuten halten.

## 6. KI-Suche

- Natürlich formulierte Frage entgegennehmen, beispielsweise auf Deutsch zu englischen Papers.
- Eine Suchanfrage pro Dokumentsprache formulieren; die ursprüngliche Anfrage als zusätzliche Variante erhalten.
- Lokale Suchpipeline für die formulierten Anfragen verwenden.
- Abgerufene Originalstellen vom gewählten Modell beurteilen lassen.
- Kurze Antwort mit Nummernverweisen auf geprüfte Fundstellen erzeugen.
- Nur gültige Quellenreferenzen für die Anzeige übernehmen.
- Standardmäßig die von der KI ausgewählten Zitate anzeigen.
- **Alle Treffer anzeigen** schaltet auf die weiteren bereits abgerufenen Kandidaten um.
- Fehlende belastbare Belege sollen zu keiner ausgewählten Zitatliste führen.
- Bei nicht verfügbarer KI mit Hinweis auf die strengere lokale Suche zurückfallen.

Die KI sieht eine begrenzte Menge abgerufener Kandidaten. **Alle Treffer** bedeutet nicht alle denkbaren Stellen der gesamten Literatur.

## 7. Mehrstufige Suche / Agentic Calls

- Echte Werkzeuge `search_library` und `finish_search` verwenden, wenn der Anbieter und das Modell das unterstützen.
- Nach einem Suchlauf weitere Anfragen formulieren, Ergebnisse zurückgeben und die Suche verfeinern.
- Innerhalb des vom Dienst festgelegten Bibliotheks-/Sammlungsbereichs bleiben.
- Ergebnisse verschiedener Schritte zusammenführen und doppelte Stellen bereinigen.
- Bereits ausgeführte identische Anfragen innerhalb einer Frage wiederverwenden.
- Funktion ein-/ausschalten; höchstens 1–6 Suchschritte, Standard 3.
- Agentenphase auf ein Zeitbudget begrenzen; laufende lokale Berechnung kann dieses Budget überschreiten.
- Bei fehlender Tool-Unterstützung oder ungültigen Antworten mit Hinweis auf den einstufigen Ablauf zurückfallen.
- Optionale Aktivitätsansicht: Anfrage geplant, Modell aufgerufen, lokale Suche gestartet, Ergebnis zurückgegeben, erneuter Tool Call und Abschluss.

Die Aktivitätsansicht zeigt technische Suchereignisse und Abfragen, keine privaten Modellgedanken.

## 8. Belege suchen: Pro und Kontra

- Eine Aussage statt einer offenen Frage eingeben.
- Auch unterstützende und widersprechende Aspekte suchen; mehrstufige Suche verwenden, wenn aktiviert und verfügbar.
- Abgerufene Kandidaten in Gruppen von der KI beurteilen lassen.
- Pro, Kontra und neutral/unklar unterscheiden.
- Direkten Beleg und Beleg zu einem Teilaspekt unterscheiden.
- Kurze Befunde und Begründungen mit Originalzitaten und Paper-Verweisen darstellen.
- Neutrale Kandidaten über die Anzeige aller Treffer erreichbar machen.
- Rot-grünen Balken aus der Anzahl der Pro-/Kontra-Stellen berechnen; neutrale Stellen separat zählen.

Beispiel: 6 Pro, 4 Kontra, 3 neutral ergeben 60 % Pro / 40 % Kontra im Balken und zusätzlich 3 neutrale Stellen. Keine Aussage über Vollständigkeit, Studienqualität oder Wahrheit.

## 9. Geschätzte Dokumentrelevanz

- Nach der Frage den **höchsten Chunk-Cosinus-Wert je verarbeitetem Dokument** bestimmen.
- Dafür alle Chunks im gewählten Bereich betrachten, unabhängig von Zitatfiltern oder der KI-Auswahl.
- Bei verfügbaren KI-Sprachvarianten diese für die betreffenden Dokumentsprachen wiederverwenden.
- Das beobachtete Spektrum in relative Farbgruppen einteilen; Sonderfälle wie gleiche oder fehlende Werte gesondert behandeln.
- Animiertes Ringdiagramm mit Dokumentanzahl und Gruppenanteilen anzeigen.
- Kategorien anklicken und die zugehörigen Dokumente mit Wert und bester PDF-Seite ansehen.
- Identische indizierte Inhalte anhand von Text-/Seiten-/Chunk-Fingerabdrücken zusammenfassen.
- Dokumentliste paginieren und aus ihr das PDF öffnen.
- Aktives Modell und Modell-/Sprachhinweise anzeigen.

Eine Gruppe mit 28 % kann niedrigere Werte enthalten als eine mit 14 %: Die Prozentzahlen zählen Dokumente. Der Ähnlichkeitswert steht beim einzelnen Dokument.

## 10. PDF-Fundort und Zitieren

- **Im PDF öffnen** oder Doppelklick auf den Zitattext öffnet den Zotero-Reader.
- PDF-Seite und, soweit ermittelbar, Rechtecke der Textstelle übergeben.
- Die Stelle vorübergehend hervorheben; keine automatische dauerhafte Zotero-Annotation anlegen.
- Bei fehlenden passenden Textkoordinaten auf die PDF-Seite zurückfallen.
- Originaltext mit Kurzbeleg und PDF-Seitenlocator kopieren.
- In Zotero installierte CSL-Zitierstile in den Einstellungen wählen.

## 11. Gespeicherte Zitate und Sitzungen

- Zitat in der lokalen Datenbank speichern und später erneut öffnen.
- Gespeicherte Zitate der gewählten Bibliothek durchsuchen.
- Notiz hinzufügen oder bearbeiten; Zitat kopieren und entfernen.
- Speicherung bleibt bei Schließen und bei Zotero-Neustart erhalten.
- Chatnachrichten, Entwürfe, direkte Suchanfragen und angezeigte Ergebnisse beim Schließen des Fensters behalten.
- Je Bibliothek einen eigenen Sitzungszustand halten.
- Chat beziehungsweise direkte Suche per Reset leeren; Zotero-Neustart leert diese temporären Ansichten.
- Nach Reset eintreffende alte Antworten nicht wieder einblenden.

## 12. Embedding-Modelle

| Profil | Schwerpunkt |
| --- | --- |
| `intfloat/multilingual-e5-small` | Kompakter mehrsprachiger Standard. |
| `intfloat/multilingual-e5-base` | Größere mehrsprachige Alternative mit höherem Rechenbedarf. |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Kompakte mehrsprachige Satzähnlichkeit. |
| `sentence-transformers/all-MiniLM-L6-v2` | Kleines englisches Modell. |
| `mixedbread-ai/deepset-mxbai-embed-de-large-v1` | Deutsch/Englisch, großer Encoder für Textstellensuche. |
| `BAAI/bge-m3` | Mehrsprachig; in Zitatlotse werden die dichten Vektoren verwendet. |
| `Qwen/Qwen3-Embedding-0.6B` | Mehrsprachige Suche mit Aufgabenbeschreibung, höherer Ressourcenbedarf. |
| `BAAI/bge-small-en-v1.5` | Kompakte englische Textstellensuche. |
| `sentence-transformers/multi-qa-MiniLM-L6-cos-v1` | Kompakte englische Frage-Antwort-Suche. |

- Kurze Erläuterung der Modellvorteile und Ressourcenanforderungen anzeigen.
- Eigenes Modell mit Hugging-Face-Kennung `Organisation/Modell` oder Modellseiten-URL eintragen.
- Eingabeprofil automatisch, Plain, E5, BGE, Qwen oder eigene Query-/Passage-Präfixe wählen.
- Modellrevision und Batchgröße konfigurieren.
- Kompatibilität anhand der Metadaten prüfen; benötigt wird ein unterstützter dichter Text-Encoder, keine beliebige Chat-/Klassifikations-/QA-Architektur.
- Kein fremder Modellcode über `trust_remote_code` aktivieren.
- Darauf hinweisen, dass Encoder und Suchformulierung die verwendeten Dokumentsprachen abdecken müssen.
- Modellwechsel bestätigen lassen, anschließend alle gespeicherten Chunk- und Themenvektoren aller Bibliotheken neu berechnen.
- Bis zum erfolgreichen Abschluss den bisherigen Index aktiv lassen; bei Fehlern zurückfallen.
- Gespeicherte Zitate und Notizen beim Wechsel erhalten.

Die Auswahl ist eine Liste von Vergleichskandidaten, keine Rangliste garantierter Suchqualität. Modellbeschreibungen stehen im Code und sollten mit den jeweiligen Modellkarten abgeglichen werden.

## 13. KI-Anbieter und Modelllisten

- **OpenAI**, **Anthropic**, **DeepSeek** und **Ollama** verbinden.
- API-Schlüssel für Cloud-Anbieter im Anmeldeinformationsspeicher des Betriebssystems halten.
- Beim Anbieterwechsel passende Standardkennung vorschlagen.
- Modellliste vom gewählten Anbieter abrufen und aktualisieren.
- Installierte Ollama-Modelle auswählen.
- Bei nicht abrufbarem Katalog Vorschläge verwenden; Modellkennung weiterhin manuell eingeben.
- Verbindung speichern und testen; ein Cloud-Test verwendet die API und kann Kosten verursachen.
- Agentic-Optionen und Aktivitätsanzeige unabhängig von der Verbindung speichern.
- Keine Zusage, dass jedes im Katalog aufgeführte Modell die benötigten Text-/Tool-Funktionen unterstützt.

## 14. Lokaler Dienst unter Windows

- Installation unter `%USERPROFILE%\.zitatlotse` mit eigener Python-Umgebung, Modellcache und SQLite-Datei.
- Suchserver ausschließlich auf `127.0.0.1:8765` starten.
- Start bei Benutzeranmeldung über Windows-Aufgabe; Registry-Autostart als Installationsfallback.
- Öffnen von Zotero beziehungsweise Suchmenü kann den installierten Launcher direkt ausführen.
- Parallel angeforderte Starts zusammenfassen; Betriebssystem-Sperre gegen doppelte Supervisoren.
- Such-Worker nach Absturz mit ansteigender Wartezeit neu starten.
- Getrennte Installations- und Dienstprotokolle.
- Index und Modelle bei Updates erhalten; bisherige Installation bei Migration als Backup lassen.

**Bekannte Lücke:** Der vollständige Verlust von Supervisor und Worker wurde durch die Windows-Aufgabe im letzten Test innerhalb von 100 Sekunden nicht automatisch behoben. Details: [Status](STATUS.md).
