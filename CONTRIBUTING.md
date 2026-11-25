# Contributing

Start with the [README](README.md) and [development guide](docs/DEVELOPMENT.md). Use a fresh local checkout and
private local configuration; never reuse deployed databases or provider accounts.

Keep a change focused on one useful behavior. Preserve existing APIs, migrations,
licences and attribution. Financial, pricing and payment changes need regression
coverage of the affected rules. Do not weaken existing assertions to obtain a green
workflow, edit applied migrations silently, or add simulated results as real data.

Run the focused checks with:

```bash
python3 ci/checks.py
```

Install the workflow's Python dependencies first. [CI scope](ci/README.md) explains
what these checks cover and what they do not.

In a pull request, describe the trigger, resulting behavior and actual validation.
State any database, provider or deployment impact. Do not commit environment files,
credentials, customer uploads, database copies, generated caches or nested Git
backups. Report vulnerabilities through [SECURITY.md](SECURITY.md).

A contribution does not choose a new project licence. Existing project and
third-party terms remain applicable; discuss any proposed licensing change first.
