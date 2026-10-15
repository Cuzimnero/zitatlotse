# Erweiterter Testaufbau für Zitatlotse

## 1. Was dieser Aufbau aussagt

Die Tests prüfen unterschiedliche Ebenen. Ein bestandenes Testergebnis bedeutet immer nur, dass die beschriebenen Erwartungen unter den angegebenen Bedingungen erfüllt wurden.

| Ebene | Durchführung | Aussage und Grenze |
|---|---|---|
| Komponenten | Python-Tests mit kontrollierten Eingaben | Prüfen Algorithmen, Grenzen, Fehlerfälle und Datenintegrität. Embeddings und Anbieterantworten sind überwiegend Testdoubles. |
| Zusammenspiel | 14 zusätzliche Tests mit erzeugten PDFs, SQLite und echtem lokalen HTTP | Prüfen die vollständigen Wege vom PDF bis zum Treffer/Zitat. Embeddings und KI-Antworten bleiben kontrolliert. |
| Fensterlogik | Drei vorhandene JavaScript-Prüfblöcke mit nachgebildetem Zotero | Prüfen Aktionen, Verlauf, Auswahl und Startsteuerung. Kein Beleg für echtes Rendering, Schriftpositionen oder Animationen. |
| Auslieferung | Manifesttests und Prüfung der angegebenen XPI | Prüfen Installationsfelder, Versionen, CRCs, Paketprüfsummen und Übereinstimmung des Laufzeitcodes mit dem getesteten Quelltext. |
| Start aus dem Paket | Optionaler isolierter Windows-Aufbau aus der XPI | Prüft Einrichtung ohne Python im PATH und Wiederanlauf nach Verlust beider Testprozesse. Führt keinen Betriebssystem-Neustart aus. |
| Modellqualität | Separater, unten beschriebener Versuchsplan | Erfordert echte Modelle und manuell geprüfte Fundstellen. Wird durch die kontrollierten Tests nicht ersetzt. |
| Echte Oberfläche | Manuelle Prüfung in Zotero | Erforderlich für kleinen Bildschirm, Skalierung, Menüausrichtung, Fokus und Animation. Noch separat durchzuführen. |

### Wiederholen

Im Projektordner mit Python inklusive `requirements-dev.txt` und Node.js:

```powershell
python run_tests.py
```

Mit Prüfung einer gebauten XPI und isolierter Startsimulation unter Windows:

```powershell
python run_tests.py --xpi dist/Zitatlotse-0.29.0.xpi --startup
```

Jeder Lauf bekommt einen neuen Ordner unter `outputs/test-runs`. Darin stehen `Testbericht.md`, `report.json`, die Protokolle und gegebenenfalls der separate Startaufbau. Der Prozess endet bei einem fehlgeschlagenen Test mit einem Fehlercode. Vorhandene Ausgabeordner werden nicht wiederverwendet.

Der Python-Lauf nutzt eine temporäre Datenbank, temporäre Einstellungen, einen Schlüsselspeicher im Arbeitsspeicher und ausschließlich lokale Netzwerkverbindungen. Die JavaScript-Prüfungen verwenden nachgebildete Zotero-Funktionen. Der optionale Starttest arbeitet aus einer frisch entpackten XPI mit einem eigenen Port und beendet ausschließlich Prozesse aus seinem eigenen Testverzeichnis. Er installiert nichts in Zotero und verändert die produktive Bibliothek nicht.

## 2. Die 14 neuen Tests: Ablauf und Erwartung

Grundaufbau pro Test: Ein künstliches englisches PDF hat drei Seiten mit unterschiedlichen MAE-Zahlen und Validierungsbefunden. Es wird über `/index` in Bibliothek 71 gespeichert. Ein eigener lokaler HTTP-Server läuft auf einem freien Port. Ein kontrollierter Encoder erzeugt bekannte Vektoren, ein kontrollierter BERT-Scorer bekannte Bewertungen. Deshalb sind Fehler in Filtern, Seitenzuordnung und Datenwegen reproduzierbar.

1. **PDF-Verarbeitung und erneuter Scan:** Status nach dem Import lesen, dasselbe PDF erneut einreichen, Sprache und Themenflags in SQLite prüfen. Erwartet: ein Dokument, drei Seiten-Chunks, `en`, vorhandene Flags und beim zweiten Scan `unchanged`. Prüft doppelte Verarbeitung und fehlende Metadaten; bewertet nicht die inhaltliche Güte der Flags.
2. **Groß-/Kleinschreibung, Seiten und Markierung:** `MAE`, `mae` und `MaE` jeweils mit einer Fundstelle pro Ergebnisseite suchen. Erwartet: alle drei PDF-Seiten genau einmal, jeweils mit Rechtecken und passendem nullbasierten Seitenindex. Prüft frühere Suchausfälle und Seitennavigation; öffnet den echten Zotero-Reader nicht.
3. **Bibliotheken und Sammlungen:** Dasselbe Attachment-Kürzel in zwei Bibliotheken indizieren, eine Sammlung durchsuchen und die Suchsession mit falscher Bibliothek/Sammlung wiederverwenden. Erwartet: Treffer bleiben im Bereich, falsche Session-Zugriffe werden abgewiesen, leere Sammlung und unbekannte Bibliothek bleiben leer.
4. **Gespeicherte Zitate:** Einen echten Treffer zweimal speichern, eine Notiz setzen, über die Notiz suchen, fremde Zugriffe versuchen und das Zitat löschen. Erwartet: dieselbe Zitat-ID statt Duplikat, Notiz auffindbar, Position erhalten, fremde Änderungen abgewiesen, danach leere Liste.
5. **Geändertes PDF:** Zitat speichern und danach ein anderes PDF unter demselben Attachment-Schlüssel indizieren. Erwartet: neue Textmarker auffindbar, alte Chunk-Zeilen ersetzt, gespeichertes Zitat weiterhin vorhanden. Das bewahrt den gespeicherten Wortlaut; dessen Position muss nach einer PDF-Änderung separat erneut geprüft werden.
6. **Daten nach Engine-Neustart:** Index und Notiz anlegen, eine neue Engine auf dieselbe Testdatenbank setzen, erneut suchen und Einstellungen lesen. Erwartet: Index, Notiz und schneller Modus erhalten. Simuliert einen neuen Engine-Lebenszyklus, keinen Windows-Neustart.
7. **Normaler/schneller Modus:** Im schnellen Modus suchen, auf normal umstellen, alte Ergebnisseite laden und eine neue Suche ausführen. Erwartet: alte Seite bleibt schnell und ruft BERT nicht auf; neue normale Suche ruft BERT auf. Prüft Modusübernahme, nicht die Suchqualität echter Modelle.
8. **Keine Treffer und Erholung nach Fehlern:** Eine orthogonale Anfrage senden, kaputtes JSON, ungültige Bibliotheks-ID und unbekannten Endpunkt aufrufen. Erwartet: keine erfundenen Zitate, passende Fehlercodes, anschließend funktionierende Statusabfrage und Suche.
9. **Lokale Anfragekennzeichnung:** Suchanfragen ohne Add-on-Header oder mit falschem Inhaltstyp senden. Erwartet: HTTP 403; eine korrekt gekennzeichnete Anfrage funktioniert. Das ist eine Protokollprüfung, kein vollständiges Sicherheitsaudit.
10. **Verschobenes PDF:** PDF umbenennen und die Fundstelle mit dem aktuellen Dateipfad auflösen; zusätzlich Seite 999 anfragen. Erwartet: Markierungsrechtecke am neuen Pfad, ungültige Seite abgewiesen. Prüft Positionsauflösung und Pfadwechsel.
11. **KI-Planung und Ablehnung:** Kontrollierte KI formuliert eine englische Anfrage, bewertet echte PDF-Treffer und wählt eine Quelle. Danach lehnt sie alle Treffer ab. Erwartet: erste Quelle empfohlen und markierbar; nach Ablehnung keine Zitate oder weiteren Ergebnisseiten. Die KI-Entscheidung ist vorgegeben, keine gemessene Modellleistung.
12. **Parallele Suchen:** Acht HTTP-Anfragen mit vier gleichzeitigen Arbeitern auf zwei gefüllte und eine leere Bibliothek verteilen. Erwartet: jeweils drei bzw. null Treffer, keinerlei fremde Bibliotheks-IDs. Das ist ein Nebenläufigkeitstest; kein Lastnachweis für Millionen Chunks.
13. **Relevanzdiagramm:** Eine identische PDF-Kopie und ein themenfremdes Kontroll-PDF importieren. Erwartet: drei Anhänge, zwei eindeutige Dokumente, Cosinuswerte 1 und 0, passende höchste/niedrigste Kategorie, korrekte Summen. Prüft Diagrammdaten und Gruppierung, keine sichtbare Zeichenanimation.
14. **Asynchrone Pro-/Kontra-Suche:** Einen echten Hintergrundjob starten, dessen Status bis zum Abschluss abfragen, echte PDF-Treffer kontrolliert als zweimal Pro und einmal Kontra bewerten. Erwartet: drei originale Fundstellen, 66,7 % Pro und 33,3 % Kontra mit PDF-Positionen. Diese Prozentwerte beschreiben Fundstellen; sie sind keine Wahrheitswahrscheinlichkeit.

## 3. Katalog jeder automatischen Python-Testmethode

Die technischen Namen stehen zusätzlich hier, damit jeder Eintrag des Ergebnisberichts einer konkreten Prüfung zugeordnet werden kann. Ein Test kann mehrere Eingabevarianten als Untertests prüfen; diese werden nicht als zusätzliche Methoden gezählt.

### PDF, Chunks und Suche

| Methode | Was wird geprüft? |
|---|---|
| `test_ai_candidates_keep_secondary_numeric_passage_without_changing_direct_search` | Eine numerische Nebenfundstelle bleibt für die KI-Auswertung verfügbar, während die direkte Suche ihre strengere Auswahl behält. |
| `test_collection_scope_filters_before_ranking_keeps_pagination_and_empty_scope` | Der Sammlungsfilter wirkt vor der Bewertung, bleibt beim Blättern erhalten und liefert für eine leere Auswahl keine Treffer. |
| `test_average_word_search_keeps_every_pdf_despite_low_cosine_and_bert` | Exakte Average-Treffer werden unabhängig von schwachen Modellwerten gefunden, Schreibweisen gleich behandelt und Wortfragmente ausgeschlossen. |
| `test_direct_phrase_and_ligature_matches_are_not_removed_by_semantic_gate` | Wörtliche Phrasen und PDF-Ligaturen wie in overﬁtting überstehen die semantische Filterung. |
| `test_qwen_direct_semantics_accepts_relevant_range_and_rejects_unrelated_range` | Kontrollierte Qwen-Bewertungsbereiche werden an den vorgesehenen Annahme- und Ablehnungsgrenzen geprüft. |
| `test_evidence_candidates_survive_moderate_cosine_but_weak_bert_does_not` | Die Belegsuche behält mäßig ähnliche Kandidaten, verwirft jedoch zu schwache BERT-Bewertungen. |
| `test_evidence_qualifies_each_language_query_against_its_own_score_range` | Sprachvarianten der Belegsuche werden anhand der jeweiligen Bewertungsbereiche geprüft. |
| `test_quote_highlights_the_entire_multiline_passage_and_normalizes_hyphenation` | Die Positionsauflösung erfasst mehrzeilige Zitate einschließlich normalisierter PDF-Silbentrennung. |
| `test_cosine_gate_sends_every_qualifying_chunk_to_bertscore` | Jeder Chunk über der Cosinusgrenze gelangt in die zweite Stufe; keine unbeabsichtigte kleine Top-k-Auswahl. |
| `test_paginated_search_migrates_vectors_and_caps_bertscore_batch` | Alte Vektorformate werden migriert, Ergebnisse über Seiten vollständig geladen und BERT-Batches begrenzt. |
| `test_exact_pdf_position_and_saved_quote_library_scope` | PDF-Rechtecke und Seitenindizes stimmen; gespeicherte Zitate bleiben bibliotheksgebunden. |
| `test_locator_uses_current_zotero_path_without_waiting_for_search_lock` | Der aktuelle Dateipfad wird verwendet und die Positionsauflösung wartet nicht auf die große Suchsperre. |
| `test_library_scope_and_citation_page` | Die Suche bleibt in einer Bibliothek und liefert die korrekte Seitenangabe für das Zitat. |
| `test_chunks_preserve_short_source_text` | Kurzer Originaltext wird bei der Chunk-Erzeugung nicht verworfen. |
| `test_chunk_overlap` | Aufeinanderfolgende Chunks enthalten die vorgesehene Überlappung. |
| `test_language_metadata_and_text_fallback` | Sprachmetadaten werden normalisiert; fehlt die Sprache, greift die Texterkennung. |
| `test_search_uses_document_language_query` | Dokumente werden mit der für ihre Sprache bestimmten Suchvariante verglichen. |
| `test_search_deduplicates_repeated_quotes_in_one_pdf` | Wiederholte identische Zitate derselben PDF erzeugen keine mehrfachen Fundstellen. |
| `test_topic_flags_are_saved_but_do_not_exclude_documents` | Themenflags und Themenvektoren werden gespeichert, ohne relevante Dokumente allein deshalb auszuschließen. |
| `test_quote_selection_matches_inflected_pdf_word` | Die Zitatwahl erkennt auch passende gebeugte Wortformen im PDF. |
| `test_quote_selection_prefers_distinctive_search_term` | Die Zitatwahl bevorzugt den aussagekräftigen Suchbegriff gegenüber generischen Textstellen. |
| `test_later_windows_do_not_restore_generic_quotes` | Nachgeladene Suchfenster bringen zuvor ausgeschlossene generische Zitate nicht zurück. |
| `test_mae_case_insensitive_search_returns_each_matching_sentence` | MAE und mae liefern dieselben passenden Sätze statt eines Ausfalls durch Groß-/Kleinschreibung. |
| `test_flag_prefilter_keeps_documents_when_flags_miss_query` | Unvollständige Themenflags entfernen Dokumente nicht allein wegen fehlender Query-Begriffe. |

### Embedding-Modelle und Neuberechnung

| Methode | Was wird geprüft? |
|---|---|
| `test_confirmation_and_atomic_switch_all_libraries_and_restart` | Ein Modellwechsel braucht Bestätigung, aktualisiert alle Bibliotheken atomar und bleibt nach erneutem Laden erhalten. |
| `test_failed_later_batch_preserves_every_old_vector_and_model` | Scheitert eine spätere Neuberechnungscharge, bleiben das alte Modell und sämtliche alten Vektoren erhalten. |
| `test_e5_prefixes_are_model_specific` | E5-Frage-/Dokumentpräfixe werden ausschließlich für das passende Modellprofil verwendet. |
| `test_every_catalog_model_uses_the_publishers_retrieval_format` | Die konfigurierten Eingabeprofile der Katalogmodelle entsprechen den im Code hinterlegten Vorgaben. |
| `test_new_encoders_normalize_vectors_and_reduce_large_model_batches` | Encoder bekommen Normalisierung und begrenzte Batchgrößen für große Modelle. |
| `test_loader_prefers_cache_and_never_enables_repository_code` | Der Modelllader bevorzugt vorhandenen Cache und aktiviert keinen fremden Repository-Python-Code. |
| `test_rebuild_new_german_model_uses_passage_prefix_and_eight_item_batches` | Die Neuberechnung für das deutsche Modell verwendet Dokumentpräfix und begrenzte Achterchargen. |
| `test_custom_hub_ids_profiles_and_invalid_paths` | Eigene Hugging-Face-IDs und Eingabeprofile werden akzeptiert; ungültige Pfade werden zurückgewiesen. |
| `test_automatic_profile_uses_repository_query_and_document_routes` | Das automatische Profil übernimmt getrennte Frage-/Dokumentrouten aus den kontrollierten Modellmetadaten. |
| `test_custom_configuration_persists_and_same_repository_profile_rebuilds` | Eigene Profile werden gespeichert; auch ein Profilwechsel beim gleichen Repository löst eine Neuberechnung aus. |
| `test_custom_invalid_routes_preserve_active_index_and_empty_database` | Ungültige Modellrouten zerstören weder einen vorhandenen Index noch eine leere Datenbank. |
| `test_zero_vectors_cannot_replace_custom_index` | Ein Modell mit Nullvektoren darf den gültigen Index nicht ersetzen. |
| `test_custom_revision_passed_to_cache_and_download_without_repository_code` | Eine angegebene Modellrevision wird an Cache-/Downloadzugriffe weitergegeben; Repository-Code bleibt deaktiviert. |
| `test_task_classifier_is_not_an_embedding_even_if_pooling_can_make_vectors` | Ein Klassifikator wird trotz technisch möglicher Vektorausgabe als ungeeignet erkannt. |
| `test_classifier_rejected_before_loading_weights_and_index_preserved` | Der Klassifikator wird vor dem Gewichts-Laden abgewiesen; der Index bleibt erhalten. |
| `test_cached_metadata_checks_pinned_revision_without_network` | Metadaten einer festgelegten Revision werden aus dem Cache ohne Netzabruf geprüft. |

### Dokumentrelevanz und Diagrammdaten

| Methode | Was wird geprüft? |
|---|---|
| `test_maximum_not_average_all_chunks_and_true_cosine` | Pro Dokument zählt die höchste normalisierte Chunk-Cosinusähnlichkeit; kein Durchschnitt und kein unnormalisiertes Skalarprodukt. |
| `test_library_whitelist_empty_collection_and_unindexed_pdf` | Relevanzwerte respektieren Bibliothek und erlaubte Anhänge; nicht indizierte PDFs bleiben als unbewertet sichtbar. |
| `test_relative_bands_and_uniform_scores_keep_ties_together` | Relative Gruppen, Gleichstände und identische Werte werden konsistent behandelt; Anteile ergeben insgesamt 100 Prozent. |
| `test_zero_similarity_is_lowest_not_highest` | Ein Dummy-Dokument mit Ähnlichkeit null landet unter einem Dokument mit hoher Ähnlichkeit. |
| `test_query_compared_only_in_each_documents_language` | Eine fremdsprachige Query-Variante darf den Wert eines Dokuments anderer Sprache nicht künstlich erhöhen. |
| `test_invalid_language_queries_rejected_before_embedding` | Falsche Sprachcodes, leere Texte und ungültige Datentypen werden vor der Vektorberechnung abgewiesen. |
| `test_encoder_must_return_one_vector_per_query_variant` | Die Zahl der Query-Vektoren muss genau zur Zahl der Query-Varianten passen. |
| `test_incompatible_active_model_does_not_display_false_relevance` | Bei einem ungeeigneten Modell werden keine scheinbar verlässlichen Relevanzkategorien berechnet. |
| `test_invalid_vectors_remain_unscored` | Nullvektoren, falsche Dimensionen und NaN-Werte bleiben unbewertet. |
| `test_identical_text_copies_count_once_and_use_the_strongest_attachment` | Inhaltlich identische Kopien zählen einmal; der stärkste Anhang repräsentiert die Gruppe, gleicher Titel allein genügt nicht. |
| `test_copy_groups_obey_library_collection_scope_and_keep_unknown_documents_separate` | Kopien werden nur innerhalb des Suchbereichs gruppiert; unbekannte Dokumente bleiben getrennt. |
| `test_fingerprints_cached_across_queries_and_reindexing_resets_identity` | Inhaltsfingerprints werden wiederverwendet und nach einer PDF-Änderung neu bestimmt. |

### KI-Suche, Anbieter und Modelllisten

| Methode | Was wird geprüft? |
|---|---|
| `test_failed_ai_review_never_displays_unreviewed_broad_candidates` | Scheitert die KI-Bewertung, erscheinen keine ungeprüften breiten Kandidaten als bestätigte Zitate. |
| `test_agent_toggle_and_unsupported_model_fallback` | Der Agentenschalter wirkt; ohne Tool-Unterstützung wird die normale Suche mit Hinweis verwendet. |
| `test_chat_translates_german_request_for_english_documents` | Ein kontrollierter Plan übersetzt die Frage; Suchvariante, Auswertung und Quellenreferenzen werden korrekt weitergegeben. |
| `test_review_can_reject_all_weak_results` | Die KI-Auswertung darf sämtliche schwachen Fundstellen ablehnen und muss dann keine Quelle auswählen. |
| `test_chat_hides_quotes_when_review_finds_no_evidence` | Keine ausreichenden Belege bedeutet leere Zitatanzeige und keine verbleibenden Ergebnisseiten. |
| `test_short_keyword_search_keeps_exact_hits_without_llm_filter` | Kurze exakte Suchwörter werden nicht unnötig durch eine KI-Umformulierung oder -Bewertung entfernt. |
| `test_review_rejects_unlinked_claims` | Eine Antwort mit behaupteten Belegen ohne passende sichtbare Quellenverweise wird verworfen. |
| `test_chat_without_provider_keeps_multilingual_query` | Ohne verbundenen Anbieter bleibt die Originalanfrage erhalten und wird nicht als KI-Antwort ausgegeben. |
| `test_anthropic_uses_messages_endpoint_and_key_header` | Die kontrollierte Anthropic-Anfrage verwendet den Messages-Endpunkt und den richtigen Schlüsselheader. |
| `test_deepseek_uses_own_endpoint` | DeepSeek-Anfragen verwenden den DeepSeek-Endpunkt. |
| `test_deepseek_errors_distinguish_key_balance_and_model` | Fehler zu Schlüssel, Guthaben und Modell werden unterschiedlich erklärt. |
| `test_ollama_model_picker_lists_installed_models` | Die kontrollierte Ollama-Antwort wird in eine Auswahl installierter Modelle umgesetzt. |
| `test_deepseek_model_picker_uses_saved_key_without_exposing_it` | Die Modellabfrage nutzt den gespeicherten Schlüssel, gibt ihn aber nicht in der Liste zurück. |
| `test_model_picker_rejects_remote_ollama_address` | Nicht lokale Ollama-Adressen werden abgewiesen. |
| `test_cloud_model_choices_exist_without_a_key_and_do_not_make_network_requests` | Ohne Schlüssel gibt es gekennzeichnete Vorschläge für OpenAI und Anthropic ohne Netzaufruf. |
| `test_openai_connection_and_nonagent_requests_use_current_token_parameter` | Die kontrollierten OpenAI-Anfragen verwenden den vorgesehenen Tokenparameter. |
| `test_openai_list_filters_modalities_keeps_text_finetunes_and_uses_entered_key` | Textmodelle bleiben auswählbar, Bild-/Audiomodelle werden entfernt, der eingegebene Schlüssel bleibt vertraulich. |
| `test_anthropic_model_list_follows_all_pages_and_preserves_labels` | Mehrseitige Anthropic-Modelllisten werden vollständig geladen und lesbare Modellnamen erhalten. |
| `test_cloud_discovery_errors_and_empty_results_leave_labelled_suggestions` | Fehlgeschlagene oder leere Modellabfragen zeigen weiterhin ausdrücklich als Vorschläge markierte Einträge. |
| `test_ollama_retries_transient_server_error` | Ein vorübergehender Ollama-Serverfehler löst den begrenzten Wiederholungsversuch aus. |

### Agentische Suche

| Methode | Was wird geprüft? |
|---|---|
| `test_grouped_citations_finish_without_rejecting_valid_sources` | Gruppierte Quellenverweise in einer Antwort werden als gültige Referenzen erkannt. |
| `test_numeric_source_after_eighth_hit_is_exposed_and_can_be_selected` | Eine numerische Belegstelle hinter dem achten Treffer bleibt für die KI sichtbar und auswählbar. |
| `test_results_drive_next_query_and_refs_survive_merge_and_pagination` | Tool-Ergebnisse gelangen in die nächste Modellrunde; Referenzen bleiben nach Zusammenführen und Blättern stabil. |
| `test_limit_and_duplicate_queries_do_not_run_extra_searches` | Das Schrittlimit und bereits ausgeführte Suchanfragen verhindern zusätzliche identische Suchläufe. |
| `test_model_cannot_switch_library_or_execute_arbitrary_functions` | Modellaufrufe dürfen weder die Bibliothek wechseln noch beliebige Funktionen ausführen. |
| `test_unknown_references_are_rejected_and_no_evidence_returns_no_quotes` | Erfundenen Quellenreferenzen wird nicht vertraut; ohne Belege werden keine Zitate ausgegeben. |
| `test_unsupported_model_produces_no_fabricated_search` | Fehlende Tool-Unterstützung wird als Fehler gemeldet statt Suchaktionen vorzutäuschen. |
| `test_native_protocols_return_matching_tool_results_and_preserve_reasoning` | Die Anbieterprotokolle ordnen Tool-Ergebnisse den richtigen Aufruf-IDs zu und erhalten erforderliche Protokollfelder. |
| `test_deepseek_thinking_finish_replays_reasoning_without_forced_tool_choice` | Der kontrollierte DeepSeek-Thinking-Verlauf übernimmt die erforderlichen Reasoning-Felder ohne erzwungene Tool-Auswahl beim Abschluss. |
| `test_deepseek_http_400_is_not_reported_as_missing_tool_support` | Ein DeepSeek-HTTP-400 wird nicht pauschal als fehlende Tool-Unterstützung ausgegeben. |
| `test_truncated_tool_response_reports_token_limit_without_fabricating_results` | Eine abgeschnittene Tool-Antwort meldet die Tokenbegrenzung und erzeugt keine erfundenen Ergebnisse. |

### Pro-/Kontra-Auswertung

| Methode | Was wird geprüft? |
|---|---|
| `test_all_pages_all_batches_dedup_and_sixty_forty` | Alle Ergebnisseiten und Bewertungsbatches fließen ein; Duplikate zählen einmal und sechs Pro/vier Kontra ergeben 60/40. |
| `test_neutral_only_has_no_percentage_and_no_selected_quotes` | Nur neutrale Fundstellen erzeugen weder Pro-/Kontra-Prozentwerte noch ausgewählte Belegzitate. |
| `test_invalid_refs_or_incomplete_review_fail_instead_of_false_balance` | Unvollständige Bewertungen oder fremde Referenzen ergeben einen Fehler statt einer falschen Bilanz. |
| `test_foreign_library_hits_rejected` | Belegstellen aus einer fremden Bibliothek werden verworfen. |
| `test_agent_collects_all_pages_even_when_finish_selects_no_quotes` | Die Belegprüfung lädt sämtliche Agenten-Fundstellen auch dann, wenn der erste Abschluss keine Zitate auswählt. |
| `test_jobs_are_library_scoped_and_can_cancel_before_next_batch` | Hintergrundjobs sind bibliotheksgebunden und können vor dem nächsten Bewertungsschritt abgebrochen werden. |
| `test_separate_aspect_queries_collect_all_pages_before_next_search` | Für getrennte Aspektfragen werden jeweils alle Ergebnisseiten vor dem nächsten Suchlauf eingesammelt. |

### Ablaufanzeige, Abbruch und Suchmodi

| Methode | Was wird geprüft? |
|---|---|
| `test_http_chat_jobs_deliver_live_activity_before_answer` | Ein echter lokaler Chatjob liefert bereits während des Laufs Ereignisse und schützt seinen Sammlungsbereich. |
| `test_live_events_are_bounded_sanitized_and_scoped` | Ereignislisten sind begrenzt, lassen Schlüssel und interne Reasoning-Inhalte weg und bleiben im Suchbereich. |
| `test_each_native_search_and_next_model_call_report_real_events_and_keep_scope` | Suchläufe und Folgerunden melden tatsächliche Aktionen und behalten Bibliothek/Sammlung bei. |
| `test_reset_cancels_before_any_fallback_or_model_call` | Ein Reset stoppt vor weiteren Fallback- oder Modellaufrufen. |
| `test_empty_scope_is_explicit_and_incomplete_collection_scope_is_rejected` | Eine leere Auswahl wird explizit übergeben; eine unvollständige Sammlungsangabe wird abgewiesen. |
| `test_fast_never_loads_or_calls_bert_in_any_retrieval_mode` | Direkte, KI- und Belegsuche dürfen im schnellen Modus BERT weder laden noch aufrufen. |
| `test_thorough_default_and_explicit_mode_still_score_candidates` | Der normale Standardmodus und seine ausdrückliche Auswahl bewerten Kandidaten weiterhin mit BERT. |
| `test_fast_literal_pagination_preserves_mode_scope_and_pdf_positions` | Wörtliche schnelle Treffer behalten beim Blättern Modus, Suchbereich und PDF-Positionen. |
| `test_invalid_mode_and_very_weak_fast_candidates` | Ungültige Suchmodi werden abgewiesen; sehr schwache Cosinus-Kandidaten werden im schnellen Modus entfernt. |

### Einstellungen und Dienststeuerung

| Methode | Was wird geprüft? |
|---|---|
| `test_speed_mode_default_persistence_provider_preservation_and_validation` | Der Suchmodus wird validiert und gespeichert, ohne Anbieter oder Agentenschalter zu überschreiben. |
| `test_activity_display_persists_across_provider_changes` | Der Schalter für die KI-Ablaufanzeige bleibt beim Anbieterwechsel erhalten. |
| `test_agent_options_persist_without_overwriting_provider_and_validate_limits` | Agentenoptionen bleiben gespeichert, erhalten Anbieterdaten und akzeptieren nur gültige Schrittlimits. |
| `test_key_is_kept_out_of_settings_file_and_response` | API-Schlüssel landen im kontrollierten Schlüsselspeicher statt in Einstellungsdatei oder Rückgabe. |
| `test_ollama_rejects_remote_endpoint` | Die Einstellungen akzeptieren nur lokale Ollama-Endpunkte. |
| `test_health_accepts_only_this_service` | Der Starter erkennt ausschließlich die passende Zitatlotse-Health-Antwort. |
| `test_os_lock_releases_and_stale_file_does_not_block` | Die Betriebssystemsperre wird freigegeben; eine alte Sperrdatei allein blockiert den Start nicht. |
| `test_duplicate_supervisor_never_spawns_worker` | Ein zweiter Supervisor erzeugt keinen zusätzlichen Worker. |
| `test_existing_service_is_reused` | Ein bereits laufender passender Dienst wird wiederverwendet. |
| `test_worker_crash_retries_and_records_new_worker` | Nach einem simulierten Worker-Absturz wird erneut gestartet und die neue Prozess-ID erfasst. |

### Paket und Installation

| Methode | Was wird geprüft? |
|---|---|
| `test_current_manifest_and_update_feed` | Das aktuelle Manifest und die Struktur des Updatefeeds erfüllen die Paketanforderungen. |
| `test_missing_installation_fields_are_rejected` | Fehlende von Zotero benötigte Installationsfelder verhindern den Paketbau. |
| `test_placeholder_and_insecure_update_urls_are_rejected` | Platzhalteradressen und unverschlüsselte Update-URLs werden nicht ausgeliefert. |
| `test_invalid_minimum_version_is_rejected` | Eine ungültige minimale Zotero-Version, etwa mit Wildcard, wird abgewiesen. |

### Neue HTTP-Systemtests

| Methode | Was wird geprüft? |
|---|---|
| `test_http_pdf_index_metadata_flags_and_unchanged_rescan` | Echter PDF-Import speichert drei Chunks, Sprache und Flags; ein unveränderter erneuter Scan erzeugt keine Duplikate. |
| `test_http_keyword_case_pagination_and_pdf_rectangles` | MAE-Schreibweisen finden drei Seiten über die HTTP-Paginierung mit echten PDF-Markierungsrechtecken. |
| `test_http_collection_library_and_session_isolation` | Bibliotheken, Sammlungsauswahl und Suchsession-Zugriffe bleiben getrennt; leere Bereiche liefern keine Treffer. |
| `test_http_saved_quote_note_search_delete_and_foreign_access` | Zitat speichern, doppelt speichern, Notiz setzen, suchen und löschen funktionieren; fremde Änderungen werden verhindert. |
| `test_http_modified_pdf_replaces_old_chunks_preserves_saved_quote` | Geänderte PDF-Inhalte ersetzen den Indexinhalt, erhalten aber gespeicherte Zitate. |
| `test_http_restart_engine_preserves_index_notes_and_mode` | Eine neu erzeugte Engine liest Index und Notizen wieder; der Modus bleibt auf der Festplatte erhalten. |
| `test_http_speed_modes_and_existing_page_snapshot` | Schnelle HTTP-Suchen überspringen BERT; alte Seiten behalten ihren Modus, neue normale Suchen verwenden BERT. |
| `test_http_no_match_and_invalid_requests_recover` | Eine unpassende Query bleibt leer; kaputte Anfragen beeinträchtigen die nachfolgende gültige Suche nicht. |
| `test_http_rejects_missing_client_headers_and_wrong_content_type` | Fehlender Add-on-Header oder falscher Inhaltstyp ergibt 403; gültige Anfragen funktionieren. |
| `test_http_pdf_locator_current_path_and_wrong_page` | Fundstellen werden auch nach einem PDF-Pfadwechsel aufgelöst; ungültige Seiten werden abgewiesen. |
| `test_http_chat_plan_review_and_rejection_use_real_retrieval` | Kontrollierte KI-Planung und Bewertung nutzen echte PDF-Treffer; vollständige Ablehnung leert die Anzeige. |
| `test_http_parallel_searches_keep_results_in_their_library` | Acht parallele Suchanfragen mischen weder Bibliotheksergebnisse noch Sessions. |
| `test_http_relevance_chart_deduplicates_pdf_copies_and_sorts_scores` | Echte indizierte Kopien zählen einmal; der höchste Chunkwert und die Reihenfolge der Diagrammkategorien stimmen. |
| `test_http_evidence_job_assesses_original_passages_and_counts_balance` | Ein asynchroner Belegjob verarbeitet echte Treffer mit kontrollierter KI-Bewertung zu einer korrekten 2:1-Bilanz. |

## 4. Die drei JavaScript-Prüfblöcke

### `test_plugin.js` — Zotero-Anbindung

Prüft Einzel-PDF-Verarbeitung, Verarbeitung eines Eintrags mit Anhang, Bibliotheksscan ohne doppelt erfasste Anhänge, Sprachübergabe, Fortschrittsmeldungen, Seitenbeleg und den Seitenleistenknopf. Außerdem werden Sprachumschaltung, Anbietermodell-Voreinstellungen und Erkennung eines nicht erreichbaren Dienstes geprüft. Zotero wird nachgebildet; ein echter Reader öffnet sich dabei nicht.

### `test_search_session.js` — Fenster, Verlauf und Ergebnisse

Prüft Fenster schließen/erneut öffnen, erhaltene Nachrichten und Suchentwürfe, Bibliothekswechsel, Reset und einen neu erzeugten Plugin-Kontext. Weitere Fälle prüfen KI-Auswahl/alle Treffer, Ergebnisseiten, Sammlungen samt Unterauswahl, Abbruch bei Filterwechsel, sichtbare Ablaufereignisse, Einstellungen, Modellwechsel-Bestätigung, gespeicherte Zitate, PDF-Aufrufe, Diagrammgruppen und verspätete Antworten. Ein nachgebildeter DOM kann Ausrichtungen oder abgeschnittene Elemente nicht zuverlässig beurteilen.

### `test_runtime.js` — Startsteuerung

Prüft Ressourcenlesen aus der XPI, Einrichtung aus dem Paket, Wiederverwendung des entpackten Runtimes, Versionswechsel, verlorene Prozesse, parallele Startversuche, Wiederholung nach Fehlern und Portkonflikte. Prüft außerdem die versteckten Windows-Startflags und den Fall, dass der Dienst bereit ist, aber die Rückmeldung des Setup-Prozesses ausbleibt. Prozesse und Zotero-APIs sind kontrollierte Nachbildungen.

## 5. Startsimulation aus einer fertigen XPI

1. **Einrichtung aus der tatsächlich gebauten Datei:** Das mitgelieferte Setup wird aus der angegebenen XPI entpackt und gestartet. Erwartet: eigener Dienst antwortet mit exakt passender Version.
2. **Kein extern installiertes Python erforderlich:** PATH enthält nur Windows-Komponenten. Erwartet: Interpreter liegt im isolierten Testverzeichnis und nicht in einer Entwicklungs-venv.
3. **Fortschritt erreicht bereit:** Erwartet: `phase=ready` und 100 Prozent statt eines endlosen Startbalkens.
4. **Vollständiger Prozessverlust:** Beide eigenen Testprozesse werden beendet, danach wird das Paketsetup erneut ausgeführt. Erwartet: Dienst erreichbar, richtige Version. Das ist eine Neustart-Annäherung, kein Windows-Boot mit Autostart, Benutzeranmeldung, Antivirus oder Zeitproblemen.
5. **Daten bleiben erhalten:** Prüfsumme der angelegten Testdatenbank und eine Testnotiz werden vor/nach dem erneuten Start verglichen. Erwartet: unveränderte Daten. Die Testdatenbank ist leer; gefüllte Daten werden zusätzlich im Engine-Neustarttest geprüft.

## 6. Noch manuell in Zotero zu prüfen

Diese Prüfungen stehen ausdrücklich nicht auf „bestanden“, nur weil die automatisierten Tests grün sind. Für jeden Punkt Ergebnis, Zotero-Version, Fenstergröße und gegebenenfalls Screenshot notieren.

| Fall | Schritte | Erwartung |
|---|---|---|
| V1 Darstellung | Alle fünf Reiter bei großem und kleinem Fenster öffnen; Windows-Skalierung 100/150/200 Prozent prüfen. | Lesbarer Text, kein Überlappen, keine verdeckten Aktionen. |
| V2 Schließen | Bei jeder Größe schließen, wieder öffnen und den Seitenleistenknopf nochmals drücken. | Ein Klick schließt; Animation und Schließen-Knopf bewegen sich gemeinsam. |
| V3 Fokus | Mit Tab, Umschalt+Tab und Escape navigieren. | Sichtbarer Fokus, erreichbare Aktionen, Escape schließt. |
| V4 Menü/Sprache | Zotero-Sprache Deutsch/Englisch umstellen und neu öffnen. | Passende Labels; AI Search statt anbieterspezifischer Fehlbezeichnung. |
| V5 Verlauf | Chat und direkte Suche nutzen; Fenster schließen/öffnen; Reset; Zotero neu starten. | Verlauf bleibt bis Reset erhalten und ist nach Zotero-Neustart zurückgesetzt. |
| V6 PDF-Stelle | Mehrere Treffer verschiedener Seiten doppelklicken. | Richtige PDF, richtige Seite, vollständige Markierung der Passage. |
| V7 Farben | Pro-/Kontra-Ansicht und Diagramm mit bekannten Testdaten ansehen. | Bedeutungen konsistent, Texte lesbar, Dokumente nicht mehrfach gelistet. |
| V8 Dienststart | Nach echtem Windows-Neustart Add-on-Menü öffnen, dabei keine Entwicklungsumgebung manuell starten. | Dienst startet selbst, Fortschritt endet, kein sichtbares PowerShell-Fenster. |
| V9 Modellwechsel | Modell auswählen, Bestätigung ablehnen; dann einen Wechsel bestätigen. | Ablehnen erhält Index, Bestätigen berechnet neu und erhält gespeicherte Zitate. |
| V10 Animation | Suche starten und reduzierte Bewegung in Windows aktivieren. | Ladeanzeige erscheint am vorgesehenen Ort; reduzierte Bewegung wird berücksichtigt. |

## 7. Suchqualität und große Datenmengen: separater Versuchsplan

### Bewerteter Referenzsatz

- Mindestens 40 Fragen vorbereiten: 10 exakte Begriffe/Abkürzungen, 10 umformulierte Fragen, 10 deutsch-englische Fragen und 10 Fragen ohne passende Quelle. Für Pro/Kontra zusätzlich Aussagen mit Pro-, Kontra- und neutralen Fundstellen vorbereiten.
- Zu jeder Frage zuerst von Hand relevante Dokumente, Seiten und Textstellen festhalten. Bei Negativfragen die Abwesenheit im abgegrenzten Testbestand prüfen. Externe KI-Ausgabe allein ist kein Referenzurteil.
- Die Fragen im schnellen und normalen Modus mit demselben Index/Modell ausführen. Suchbereich, Modellrevision, Schwellen und Softwareversion protokollieren. Kaltstart und warme Folgeanfragen getrennt erfassen.
- Messen: Anteil relevanter Stellen in den ersten zehn Treffern (Precision@10), Anteil gefundener bekannter Stellen (Recall@k), Fehlzitate bei Negativfragen, korrekte Quellenverweise und PDF-Positionen. Pro/Kontra/neutral anhand einer manuell geprüften Klassifikation getrennt bewerten.
- Median und 95. Perzentil der Laufzeiten über mehrere Wiederholungen ausweisen. Nicht aus einem einzelnen warmen Lauf auf die generelle Geschwindigkeit schließen.
- Qualitätsgrenzen vor dem Versuch festlegen. Als erste Abnahme: kein fremder Bibliothekstreffer, keine erfundene Quelle und keine bestätigten Zitate bei den festgelegten Negativfragen. Weitere Precision-/Recall-Ziele erst mit einem sinnvollen Referenzsatz bestimmen.

### Skalierungsversuch

Mit separaten künstlichen Beständen von etwa 1.000, 10.000 und 100.000 Chunks prüfen: Indexierdauer, Datenbankgröße, RAM-Spitze, Query-Einbettung, Cosinus-Stufe, BERT-Stufe und KI-Runden getrennt. Dieselbe Frage jeweils mehrfach ausführen, Suchsessions schließen und prüfen, ob der Speicher wieder freigegeben wird. Eine rein synthetische Wiederholung gleicher Texte liefert keine belastbare Qualitätsaussage; für die Qualität diverse Inhalte verwenden.

Echte Modelle nur aus einem vorhandenen Cache laden oder einen Download separat zulassen. Echte Anbieterprüfungen sind getrennte kostenpflichtige Tests und benötigen einen passenden Testbestand und Freigabe. Dieser automatisierte Aufbau sendet keine privaten PDFs an Anbieter und behauptet keine aktuelle API-Kompatibilität aus simulierten Antworten.
