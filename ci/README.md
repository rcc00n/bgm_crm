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


## PostgreSQL business regressions

`python ci/business_checks.py` runs the explicitly listed existing business tests
against PostgreSQL 17.5. It loads the real URL configuration and migrations, uses
a temporary media directory, clears provider credentials, keeps queues/cache/email
local, and blocks Python socket connections except the loopback database service.
Payment, mapping and bot clients in the selected tests are mocked. This is a scoped
business suite, not a claim that every repository test or live integration ran.

Start a **disposable** database; never reuse a production database or volume:

```sh
docker run --rm -d --name reviewer-postgres \
  -e POSTGRES_USER=ci_review -e POSTGRES_PASSWORD=synthetic-local-only \
  -e POSTGRES_DB=review -p 127.0.0.1:55432:5432 postgres:17.5
# Wait until: docker exec reviewer-postgres pg_isready -U ci_review -d review
REVIEW_POSTGRES=1 REVIEW_POSTGRES_PORT=55432 python ci/business_checks.py
docker stop reviewer-postgres
```

Use a fresh checkout without private `.env` files. The test settings ignore
`DATABASE_URL` and arbitrary remote hosts; Django creates and destroys a separate
`test_review_*` database. The example password belongs only to this ephemeral CI
service. The GitHub `business-postgres` job runs the same command on its isolated
service container; it does not deploy and requires no repository secrets.

The expanded suite also refreshes existing test fixtures: a rollback action needs
a persisted import batch, HTML messages are escaped, and merch checkout requires
a delivery address plus a mocked live shipping rate. Inventory/order/file
persistence assertions remain in place.
