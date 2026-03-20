# Admin What's New Maintenance

Use this file whenever an admin-panel task changes navigation, workflows, tools, labels, dashboards, permissions, or other staff-facing behavior.

## Rule

Every meaningful admin-facing change must add a new release entry at the top of `core/services/admin_releases.py`.

## What Counts

Add an entry when you change:

- admin navigation or sidebar structure
- workspace hubs or dashboards
- top-bar tools, badges, filters, or notifications
- staff workflows or the recommended entry points for work
- admin forms, labels, summaries, or other visible UX

Do not add an entry for:

- invisible refactors with no staff-facing effect
- internal cleanup that does not change how the admin behaves
- non-admin-only changes

## Entry Format

Each release entry should include:

- `key`: unique slug, usually date plus short feature name
- `published_at`: ISO datetime with timezone
- `title`: short staff-readable headline
- `summary`: 1 sentence on what changed
- `highlights`: 2-4 concise bullets focused on user impact
- `areas`: short labels like `Navigation`, `Orders`, `Email`, `Reporting`

## Writing Standard

- Write for staff, not developers.
- Describe what changed and how to work with it now.
- Keep bullets concrete and action-oriented.
- Prefer “Start here”, “Use this page for…”, “This now lives in…” language.

## Ordering

- Newest release goes first.
- Keep the list sorted descending by `published_at`.

## After Editing

1. Verify `python3 manage.py check` passes.
2. Open or reverse the `admin-whats-new` route.
3. Confirm the newest entry appears in the top-nav What's New dropdown.
4. If the change affects navigation, verify the related workspace hub or sidebar path still resolves.
