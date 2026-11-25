# Focused CI checks

`ci/checks.py` loads application models and existing code under an explicit synthetic
settings module. It forces an in-memory SQLite database, local file storage, memory
queues/caches and an in-memory email backend. It clears external-provider credentials
and blocks socket connections before Django initializes. No payment, email, bot,
OCR-model download, live database or deployment operation is performed.

The existing tests selected here are:

- `core.tests.test_utils_discount`
- `core.tests.test_utils_format_currency`
- `core.tests.test_utils_durations`
- `core.tests.test_validators`
- `core.tests.test_template_filters`

These are focused source checks, not full PostgreSQL, external-provider, OCR-model,
browser or production acceptance. PostgreSQL-specific constraints and concurrency
need their own isolated integration environment. Existing test assertions are not
modified or skipped by this setup.

The GitHub workflow also checks Python syntax. It does not deploy or use repository secrets. A failing check remains a failing
job; no passing badge or coverage percentage is asserted by this document.

Python 3.12 is the focused CI interpreter. This job does not certify the separate
`.python-version` deployment pin against all native dependencies.
