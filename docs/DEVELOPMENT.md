# BGM development guide

## Local prerequisites

Use an isolated Python environment, the dependencies in
[`requirements.txt`](../requirements.txt), and an empty PostgreSQL database with a
dedicated local role. The repository also has a deployment interpreter pin in
[`.python-version`](../.python-version); check compatibility of that interpreter
with the pinned native dependencies before reproducing the deployment environment.

The settings module is [`booking.settings`](../booking/settings.py), and the
secret-key variable is `SECRET_KEY`. Export the required values into the process
environment; `DATABASE_URL` is read directly from `os.environ`, so a `.env` file
alone does not export it for a host `manage.py` process.

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')"
export DATABASE_URL='postgresql://LOCAL_USER:LOCAL_PASSWORD@127.0.0.1:5432/bgm_local'
export DEBUG=True
export ALLOWED_HOSTS=127.0.0.1,localhost
```

Replace the database placeholders with your dedicated local role and password.
The key command generates a new local value. Keep local configuration untracked;
never reuse a source fallback, customer export or provider credential.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

Use `makemigrations` when intentionally developing model changes, then review and
commit the resulting migration; it is not required for an unchanged fresh checkout.
The commands above were checked against the source entry points, not executed
against a new application database during this documentation refresh.

## Add your own local data

- In Django admin, add service categories, services, durations, prices and images.
- Configure staff profiles, service assignments and availability before testing slots.
- Add product categories, vehicle makes/models, products, options and fitment data
  before testing catalogue filters and checkout.
- Create local users and assign the appropriate roles. The existing role utilities
  in [`core/utils.py`](../core/utils.py) control staff access and dealer pricing.

No customer, order, appointment or shared login fixture is provided by this guide.

## Optional integrations

Provider configuration is independent of starting the development server. Use
appropriate sandbox credentials and intentionally selected recipients when testing.

| Integration | Source configuration |
| --- | --- |
| Square | `SQUARE_ENVIRONMENT`, `SQUARE_APPLICATION_ID`, `SQUARE_ACCESS_TOKEN`, `SQUARE_LOCATION_ID` |
| Printful | `PRINTFUL_TOKEN`, optional `PRINTFUL_STORE_ID`, catalogue/product links and bounded fetch/cache settings |
| Email | Configurable email backend, sender and SMTP or SendGrid settings |
| S3 uploads | `USE_S3_MEDIA` and the corresponding bucket, region and credential variables |
| Telegram | Admin bot settings, recipient slots and allowed user IDs |

Printful supports `PRINTFUL_MERCH_CATALOG_URL`,
`PRINTFUL_MERCH_PRODUCT_URL_TEMPLATE`, `PRINTFUL_MERCH_LIMIT`,
`PRINTFUL_MERCH_CACHE_SECONDS`, `PRINTFUL_TIMEOUT_SECONDS` and
`PRINTFUL_MERCH_SHOW_PRICE`. Detailed shipping/webhook behavior is documented in
[the merchandise guide](merch_shipping_and_printful.md).

The Telegram worker is a separate process:

```bash
python manage.py run_telegram_bot
```

Only start it for an intentionally configured local bot and recipients. Do not run
multiple consumers for an existing deployed bot. The existing
[Telegram guide](telegram-notifications.md) covers recipients, commands and delivery.
Reminders and digests also have explicit commands:

```bash
python manage.py process_telegram_reminders
python manage.py send_telegram_digest --force
```

These commands can send real messages; they are operational tools, not setup steps.

## Customization and contribution

- Templates live in [`templates/`](../templates/); source assets live in
  [`static/`](../static/).
- Existing hero/context behavior is in
  [`core/context_processors_core.py`](../core/context_processors_core.py).
- Dealer pricing utilities and phone validation live in
  [`core/utils.py`](../core/utils.py) and [`core/validators.py`](../core/validators.py).
- The application uses JSON endpoints alongside server-rendered Django views;
  inspect [`booking/urls.py`](../booking/urls.py) and
  [`accounts/urls.py`](../accounts/urls.py) before extending a client flow.

Keep changes focused, add coverage for affected business rules, and explain the
behavior and validation in a pull request. Preserve existing licences and attribution.

## Deployment boundary

[`Procfile`](../Procfile) defines web, release and Telegram processes. Release runs
migrations and static collection. Configure private environment values, persistent
uploads, TLS and backups for the intended host before deployment. A documentation
checkout is not a deployment instruction or an instruction to restart a shared host.
