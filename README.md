BGM CRM & Store

BGM CRM is a full‑featured customer relationship management (CRM) and e‑commerce platform built with the Django framework. It powers the digital presence for a service‑oriented business by combining appointment scheduling, client dashboards, dealer programs and an online store into a single cohesive project. The repository contains several Django apps (accounts, core, store and booking) that cooperate to deliver a rich experience for staff, service providers (masters) and clients.

Key features
Multi‑role authentication and dashboards

The accounts app extends Django’s authentication to support role‑based redirects and access control. After login the application inspects the user’s roles (Admin, Master or Client) and redirects accordingly
GitHub
. A RoleRequiredMixin checks for the presence of specific roles and raises a PermissionDenied error when unauthorized
GitHub
. Dedicated dashboard views provide tailored experiences:

Client dashboard: shows the user’s profile, recent appointments, upcoming appointments and monthly statistics
GitHub
. Users can update their profile via a POST request
GitHub
.

Master dashboard: a placeholder for service providers (masters) who need a management interface
GitHub
.

Main menu: a protected landing page for clients, serving as an entry point into the service catalog
GitHub
.

Order history: clients can browse past orders and view details; queries fall back to email matching when no user relation exists
GitHub
.

Service catalog and appointment scheduling

The core app exposes both UI views and JSON APIs to manage services and appointments. A helper builds catalog context by filtering services by text query or category and prefetches categories for efficient templates
GitHub
. The public main menu uses this context and injects the authenticated user’s profile and appointments
GitHub
.

Authenticated endpoints allow clients to:

Query availability: Given a service, date and optional master, the api_availability endpoint returns available time slots and a list of masters capable of performing the service
GitHub
.

Book an appointment: The api_book view validates input, ensures the selected master can perform the service, normalizes start time with timezone awareness and creates an appointment with an initial status
GitHub
.

Cancel or reschedule appointments: Additional endpoints enforce owner or staff permissions and update appointment status atomically using transaction safeguards
GitHub
.

An API for searching services supports full‑text queries and optional category filtering; it limits results and includes discounted prices and image URLs for rendering card components
GitHub
.

Dealer program

Users can apply to become dealers through a dedicated form. The DealerApplyView injects the current user into the form, prevents multiple in‑progress applications and saves a DealerApplication record
GitHub
. A status page summarizes the user’s application and whether they are an approved dealer
GitHub
.

Online store

The store app implements a complete product catalogue and checkout flow:

Filtering and catalog navigation: Products can be filtered by category, make, model and year. _apply_filters processes the form and filters querysets accordingly
GitHub
. The store_home view displays products, new arrivals and sectional listings when no filters are active
GitHub
. Clients can browse specific categories or view a product’s detail page with related products
GitHub
.

Cart management: Session‑based carts hold quantities keyed by product id. Users can add products (with optional “buy now” redirect), view the cart with calculated totals, and remove items
GitHub
GitHub
. Server‑side messages provide feedback.

Checkout: When placing an order, the system collects customer information, validates required fields, and handles both shipping and pickup options. It dynamically maps the collected data onto Order model fields, creates the order and associated OrderItem records inside a transaction, and finally empties the cart
GitHub
. Authenticated users are linked to the order when possible
GitHub
.

Utility functions and validation

Role assignment & discounts: Helpers assign roles and automatically grant is_staff access for Admin/Master users. Dealer discounts are retrieved from the user profile and applied to base prices via a simple calculation
GitHub
.

Phone number validation: A regular expression checks international phone numbers (optional + followed by 10–15 digits) and raises a ValidationError on invalid input
GitHub
.

Hero images: A context processor maps route names to hero images and provides fallbacks so pages can display appropriate hero banners
GitHub
.

Project structure
booking/           – Django project settings and WSGI entry point.
accounts/          – authentication, role management and user dashboards.
core/              – service catalogue, appointment APIs, dealer program, utilities.
store/             – product catalogue, shopping cart and checkout.
templates/         – HTML templates for client and admin interfaces.
static/            – static assets (images, CSS, JS).
manage.py          – entry point for Django management commands:contentReference[oaicite:25]{index=25}.
README.md          – original quick‑start instructions (superseded by this file).

Getting started
Prerequisites

Python 3.8 or later and pip installed on your system.

A virtual environment is recommended to isolate dependencies.

PostgreSQL, SQLite or another database supported by Django; configure it in booking/settings.py (not included here for security reasons).

Installation

Clone the repository and change into the project directory.

Create a virtual environment and activate it:

python -m venv venv
source venv/bin/activate


Install dependencies using the provided requirements.txt:

pip install -r requirements.txt


Configure environment variables: set DJANGO_SECRET_KEY, database credentials and other settings in an .env file or through your environment. The project uses booking.settings as the settings module
GitHub
.

Apply migrations and create a superuser:

python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser


Run the development server:

python manage.py runserver


Visit http://127.0.0.1:8000/admin/ for the admin panel and http://127.0.0.1:8000/accounts/login/ for the user login page. Sample credentials are provided in the original README for local testing.

Populating data

Services & categories: Add service categories and services through the admin panel. Each service can include duration, price and an optional image.

Products & categories: Create product categories, car makes, models and products. Specify compatibility and active status. Products appear on the store home page and category pages once added.

Telegram operations bot

The notifications app ships an operations-grade Telegram bot that lives alongside the Django project.

- Configuration lives at “Telegram bot settings” in the admin panel. Add the BotFather token, at least one chat ID (comma or space separated), and optional whitelisted user IDs for interactive commands.
- Once configured, run `python manage.py run_telegram_bot` on the Dokku host to start the long-polling worker. It understands `/today` (returns an inline digest) and `/digest` (pushes the summary to all recipients).
- Real-time alerts fire automatically whenever an appointment or order is created as long as the corresponding toggles are enabled in the settings entry.
- The same admin section exposes “Telegram reminders”. Staff can queue ad-hoc reminders from the admin UI, trigger them manually via the bulk action, or automate delivery with `python manage.py process_telegram_reminders`.
- Optional daily digests can be sent via cron with `python manage.py send_telegram_digest` (includes a `--force` switch). Use the hour selector inside the settings model to control when the digest is allowed to send.

Users & roles: Create users and assign roles via the admin interface or programmatically using assign_role
GitHub
. Granting the Admin or Master role will automatically set is_staff.

Customization

Hero banners: To customize hero images per route, update the HERO_MAP dictionary in core/context_processors_core.py or add new keys for additional routes
GitHub
. Place your images in static/img/.

Dealer discount logic: The dealer discount functions are located in core/utils.py
GitHub
. Adjust them to fit your pricing rules, or expose the discount percent on the user profile model.

Phone validation: Modify the regular expression in core/validators.py if you need different phone formats
GitHub
.

Templates & styling: The project uses Django templates located under templates/. Feel free to extend or override them to suit your brand. Static assets reside in static/ and can be replaced.

API endpoints: The service and booking APIs return JSON responses designed for use with AJAX. Extend them to integrate with front‑end frameworks or mobile clients.

Contributing

Contributions and suggestions are welcome. Please follow these guidelines when contributing:

Fork the repository and create a new branch for your feature or bug fix.

Write clear commit messages and include tests when adding new functionality.

Submit a pull request describing your changes.

Avoid including sensitive information (such as secret keys) in your code or documentation.

License

This project is provided for internal use and educational purposes. Licensing for third‑party assets in the staticfiles/admin/ directory remains under their respective licenses.



### Commands:


Kill the port:
```
fuser -k 8000/tcp
```

Command to activate the enviroment and install dependencies:
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Command to start the server:
```bash
python manage.py runserver
```

Command to make migration:
```bash
python manage.py makemigrations
```

Command to migrate:
```bash
python manage.py migrate
```

Command to add superuser to the Admin panel:
```bash
python manage.py createsuperuser
```

Pages:

http://127.0.0.1:8000/admin/ - admin panel login

http://127.0.0.1:8000/accounts/login/ - general login


Test accounts:

  Admin:
  
    UN: Vadim
    
    P: 7238523qwQW!
    
  User:
  
    UN: user
    
    P: useruser!!!
