# Zitatlotse development rules

- Before changing search, AI evaluation, agentic calls, scope boundaries or the search window, run several known example queries against the existing version. Repeat the same cases after the change.
- For AI search changes, check the real flow, including selection and display of quotations. Direct search or provider responses simulated only in tests are not sufficient evidence of retrieval quality.
- Check positive DINO and knowledge-distillation cases, an unrelated negative case with no quotations, library boundaries and empty collections. Use only documents the user running the test has authorized for use and, where applicable, cloud transfer.
- Save reproducible reports locally under `outputs/`. Anonymize before publication. Never log keys, raw provider responses or private model reasoning.
- Cloud tests are not automatically authorized. Check the specific request, document selection and possible costs; without authorization, continue only independent local work.
- Private data, models, virtual environments and test output do not belong in the repository. Original project code is MIT licensed; comply with third-party licenses.
