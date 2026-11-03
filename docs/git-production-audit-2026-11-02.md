# Git and production audit — 2026-11-02

GitHub `origin/master` was `043e1d1`. The deployed Dokku commit was `5435357`,
12 commits ahead. Those commits include the bumper configurator, add-on/paint-code
checkout and removal of generated static assets from source control. The local
master was fast-forwarded to that production history before this fix.

The running web container also differed from its deployed commit in seven files:

- `store/urls_store.py`
- `store/views.py`
- `templates/client/bgm_home.html`
- `templates/includes/topbar_client_v3.html`
- `templates/store/_base_store.html`
- `templates/store/_bumper_configurator.html`
- `templates/store/product_detail.html`

All seven runtime versions were copied and preserved in commit `fd31508` before
notification changes. This retains the integrated bumper cart endpoint, current
configurator and existing storefront/widget behavior during redeployment.

The initial local working tree contained no uncommitted tracked changes. These
older local branches contain commits not reachable from the inspected remote
references; they were not merged as part of this production fix:

| Local branch | Unpublished commits |
| --- | ---: |
| `backup/local-master-pre-align-20260326` | 4 |
| `deploy/for-main` | 1 |
| `deploy/pin-29e4452` | 1 |
| `deploy/printful-live` | 1 |
| `deploy/prod-storefront-20260323-191124` | 2 |
| `deploy/prod-storefront-20260323-193222` | 1 |
| `deploy/prod-storefront-20260323-194831` | 1 |
| `deploy/reference-photo-clarify` | 2 |
| `deploy/reference-photo-clarify-main` | 1 |
| `dev/from-6ddf389` | 1 |
| `hotfix/meta-text-restore` | 1 |
| `react` | 1 |
| `rollback/bgm-prod-20260323-193222` | 2 |
| `rollback/bgm-prod-20260323-194831` | 1 |

Distinct commit identities do not necessarily mean missing features: several
branches are old deployment, backup or rollback histories with cherry-picks.
Ignored local price spreadsheets, media, dependencies and the development database
are intentionally outside Git; they were not added to the repository.
