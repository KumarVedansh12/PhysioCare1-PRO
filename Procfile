web: gunicorn config.wsgi:application --config gunicorn.conf.py
worker: python manage.py send_appointment_reminders --watch
release: python manage.py migrate --noinput
