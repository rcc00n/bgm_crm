web: gunicorn booking.wsgi:application --workers 4 --bind 0.0.0.0:5000 --timeout 60
release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
telegrambot: python manage.py run_telegram_bot
