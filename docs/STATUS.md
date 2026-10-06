# Teststand und bekannte Grenzen

[Zur Projektseite](../README.md)

**Stand: 6. Oktober 2026 · Version 0.27.0 · experimenteller Prototyp**

## Neue normale XPI-Installation

- Offizielle eingebettete Python-3.13.16-Laufzeit, CPU-PyTorch und Backend vollständig in der XPI.
- Reale Einrichtung aus dem XPI-Archiv in einem separaten Testordner, mit Python aus dem Suchpfad entfernt und Modell-Downloads deaktiviert: erfolgreich.
- Health-Check des tatsächlich gestarteten Dienstes, leere Bibliothek und Fortschrittsabschluss: erfolgreich.
- Vollständiger Verlust von Supervisor und Worker, erneuter Start aus demselben Paket, Datenbank und zusätzliche Testdatei erhalten: erfolgreich.
- Simulierter Zotero-Start: Erstinstallation, gecachte Laufzeit, ältere Dienstversion, parallele Anfragen, Fehler mit erneutem Versuch und fremder Prozess auf dem Port: erfolgreich.
- 104 Backend-Tests unter der neu enthaltenen Python-Laufzeit: erfolgreich; Plugin- und Sitzungsprüfungen ebenfalls erfolgreich.
- Echte E5-/BERTScore-Prüfung mit einem synthetischen PDF: Verarbeitung, positiver Treffer, Fundort und Bibliotheksgrenze liefen erfolgreich. Ein fachfremder Negativfall liefert dabei einen Treffer. Derselbe Fehler tritt auch mit der bisherigen Laufzeit auf; die neue Installation behebt diese vorhandene Relevanzschwäche nicht. Die vollständige Modell-Smoke-Prüfung gilt damit als fehlgeschlagen.

Zotero übernimmt Start und Einrichtung und prüft den Dienst alle 30 Sekunden. Eine separate Python-Installation, ein manuell gestarteter Dienst oder eine Windows-Aufgabe gehören nicht zum neuen Standardweg.

Ein tatsächlicher PC-Neustart und die vollständige Erstinstallation über den nativen Zotero-Add-on-Manager sind durch diese isolierten Tests noch nicht bestätigt. Die folgenden Startmessungen betreffen den vorherigen Stand 0.26.3.

## Was geprüft wurde

| Prüfung | Beobachtung |
| --- | --- |
| Isolierte Backend-Tests | 104 Tests für Suche, Bereich, Modelle, Anbieterantworten, Belegbilanz, Jobs, Dokumentgrafik, Speicherung und Launcher. |
| Plugin-Tests | Verarbeitung, Locale, Reader-Aufrufe, Bibliotheken/Sammlungen, Modellwahl und Startfunktion in einer simulierten Zotero-Umgebung. |
| Sitzungs-/Anzeige-Tests | Chat, Reset, Filter, Pagination, Dokumentgrafik und Wiederöffnen in einem simulierten Dokumentbaum. |
| Echte lokale Suchpipeline | Modell- und PDF-Smoke-Tests sowie direkte Suchanfragen mit vorhandenem Index. |
| Frühere echte KI-Läufe | Positive DINO-/Distillationsfragen und fachfremder Negativfall mit dem konfigurierten Anbieter geprüft; tatsächliche Resultate in der UI-Logik wiedergegeben. Keine automatische cloudbasierte CI. |

Die isolierten Tests verwenden teilweise simulierte Vektoren und Anbieterantworten. Sie messen keine reale Retrieval-Qualität. Die simulierte Zotero-Umgebung ersetzt keine manuelle Prüfung im nativen Client. Die vorbereitete GitHub-Actions-Datei ist vor Veröffentlichung noch nicht auf GitHub ausgeführt worden.

## Frühere Windows-Kaltstart- und Ausfallprüfung (0.26.3)

Die Tests beendeten nur die installierten Zitatlotse-Prozesse, starteten die Windows-Aufgabe oder die ausgelieferte Menü-Startfunktion und prüften tatsächliche HTTP-Verfügbarkeit.

| Fall | Letzte Beobachtung |
| --- | --- |
| Drei zusätzliche vollständige Kaltstarts | 3/3 erfolgreich; etwa 2,87–2,90 Sekunden bis HTTP-Verfügbarkeit. |
| Weitere registrierte Startprüfung | Erfolgreich; etwa 5,16 Sekunden. |
| Zwei gleichzeitige Startanfragen aus dem Menü | Erfolgreich; ein Launcher-Start. |
| Zurückgebliebene Sperrdatei | Verhindert den neuen Start nicht, wenn kein alter Prozess mehr lebt. |
| Absturz nur des Workers | Wiederanlauf unter gleichem Supervisor; etwa 4,84–5,22 Sekunden. |
| Vorübergehend gesperrte Datenbank beim Start | Worker beendet sich früh; nach Freigabe Wiederanlauf unter gleichem Supervisor. |
| Echter automatischer Zeittrigger | Start erfolgreich; etwa 4,01 Sekunden nach Aufgabenausführung. |
| Vollständiger Verlust von Supervisor und Worker | **Fehlgeschlagen: kein automatischer Wiederanlauf durch Windows innerhalb von 100 Sekunden.** |

Der vollständige Ausfall wurde auch mit explizitem Fehlercode 1 und nach automatischem Zeitstart beobachtet. Die Wiederholungseinstellungen der Aufgabe waren vorhanden; die Ursache des fehlenden Wiederanlaufs wurde noch nicht isoliert. Der reguläre Dienst wurde nach den Tests wieder gestartet und die temporäre Aufgabe entfernt.

**Nicht ausgeführt:** tatsächlicher PC-Neustart, Abmeldung/Anmeldung, Zurücksetzen des Windows-Dateicaches und Netzwerkänderungen während des Bootens. Der Zeittrigger prüft automatische Ausführung, nicht den tatsächlichen Anmeldetrigger.

## Reale direkte Suche nach Prozessneustart

Messungen aus einem kleinen lokalen Bestand mit 11 PDF-Anhängen, 1.611 Chunks und Multilingual E5 Small. Sie sind Beispiele auf einem einzelnen PC, kein allgemeiner Benchmark.

| Anfrage / Bereich | Treffer insgesamt | Dauer |
| --- | ---: | ---: |
| `Average`, gesamte Testbibliothek | 44 | 83,02 s |
| DINO-Momentum-Lehrer, passendes Test-PDF | 22 | 3,67 s |
| Fachfremde klinische Migräne-Frage, abgegrenzte Paper-Auswahl | 0 | 26,16 s |

Die erste Anfrage enthält Modellinitialisierung und Suche; diese Zeiten wurden nicht getrennt gemessen. Ein schneller Health-Check bedeutet nicht, dass die erste Suche schnell ist. Index- und Zitatanzahl blieben bei der Ausfallprüfung erhalten.

## Bekannte Grenzen

- **Dienstverlust:** neuen Zotero-Wiederanlauf bei realem Booten und über längere Sitzungen prüfen.
- **Kaltstart:** sichtbarer Modellladezustand und gezieltes Vorladen können die erste Suche verständlicher machen.
- **Retrieval:** Schwellenwerte hängen von Modell, Sprache und Query ab. Es gibt bisher keinen breiten Recall-/Precision-Benchmark.
- **Große Bestände:** linearer exakter Cosinus-Scan, zusätzlicher BERTScore-Aufwand, kein ANN-Index.
- **PDFs:** kein eingebautes OCR; Tabellen, Formeln, Spalten und ungewöhnliche Textextraktion können Zitate oder Koordinaten beeinträchtigen.
- **Seiten:** PDF-Seitenlocator kann von gedruckter Paginierung abweichen.
- **KI:** begrenzter Kandidatenkontext; Modell kann Belege übersehen oder falsch einordnen. Tool-Unterstützung muss zum Anbieter und Modell passen.
- **Grafiken:** relative Ähnlichkeitsgruppen und Mengen gefundener Stellen sind keine Wahrscheinlichkeiten oder Qualitätsbewertungen.
- **Oberfläche:** native Prüfung im kleinen Zotero-Fenster, Dropdowns, Reader-Navigation und Animationen bleibt erforderlich.
- **Installation:** vollständiger Windows-Weg; andere Plattformen nicht als fertige Distribution geprüft.
- **Updates:** kein automatisches Add-on-Update.
- **Reproduzierbarkeit:** Release-Laufzeit enthält die exakten Paketversionen in `PACKAGES.json`; Änderungen am Laufzeit-Build separat erneut prüfen.

## Sinnvolle nächste Schritte

1. Supervisor-Wiederanlauf und echte Windows-Neustarts zuverlässig absichern.
2. Kleine referenzierte Testbibliothek mit geprüften erwarteten Fundstellen, fehlenden Belegen und Sprachvarianten aufbauen.
3. Retrieval-Qualität und Laufzeit pro Modell/Bestandsgröße messen; Schwellenwerte daraus ableiten.
4. PDF-Navigation und Fensterbedienung automatisiert im nativen Zotero prüfen.
5. ANN-Index und Batch-/Cache-Verbesserungen erst anhand gemessener Engpässe auswählen.
6. Für eine stabile Release-Distribution Abhängigkeiten, Modelldaten, Installationswege und Lizenzhinweise reproduzierbar festhalten.
