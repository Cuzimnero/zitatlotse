# Contributing

Thank you for reproducible bug reports and well-documented improvements. This project is an experimental prototype.

## Get started locally

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m unittest discover -s backend -p "test_*.py"
node test_plugin.js
node test_search_session.js
python package.py
```

For actual model inference, use `backend/requirements.txt`. For Zotero, run the Windows installer. See the [testing guide](docs/TESTING.md).

## Verify search changes

Use the same query set before and after a change. Include positive cases, a clearly unrelated negative case, another library and an empty collection. For AI changes, also test an authorized real provider flow, including result selection and display. Mock-only tests do not prove retrieval quality.

Record the query, mode, search scope, models, hit count, selected sources, runtime, warnings and outcome. Store private results under `outputs/` and sanitize them before public summaries. Do not publish keys, raw responses or private model reasoning.

Cloud runs require an informed decision by the user running them for the specific documents and potential costs. Existing tests or another user's authorization are not general consent to transfer data.

## Submit changes

- Keep changes small and explain the reason and test evidence.
- Database/model changes must preserve existing quotations and notes or provide an explicit migration.
- Preserve library and collection boundaries in every search path.
- Add new UI labels in both German and English.
- Include the Zotero/Windows/add-on versions, reproducible steps and sanitized error messages in bug reports.
- Do not commit private PDFs, index files, credentials or model weights.

## Security

For possible credential leaks or unauthorized data transfer, see [SECURITY.md](SECURITY.md). Ordinary bugs can be reported as issues. This project currently offers no guaranteed response time.
