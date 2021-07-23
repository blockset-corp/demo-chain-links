release: python manage.py migrate
web: gunicorn server.wsgi:application --access-logfile - --error-logfile -
worker: celery -A server worker -l info -Q celery,consumer
beat: celery -A server beat -l info