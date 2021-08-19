release: python manage.py migrate
web: gunicorn server.wsgi:application --access-logfile - --error-logfile -
worker: celery -A server worker -l info -Q consumer -P gevent -Ofair -c $HEROKU_CELERY_CONCURRENCY --without-mingle --without-gossip --without-heartbeat
beat: celery -A server worker -B -l info -Q celery