#!/bin/sh
set -eu

python manage.py check --deploy --fail-level ERROR
python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
