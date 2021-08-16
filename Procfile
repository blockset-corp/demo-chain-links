release: python manage.py migrate
web: gunicorn server.wsgi:application --access-logfile - --error-logfile -
worker: celery -A server worker -l info -Q consumer -P gevent -c 175
beat: celery -A server worker -B -l info -Q celery