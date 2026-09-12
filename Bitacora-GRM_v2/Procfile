web:     gunicorn -c gunicorn.conf.py app.main:app
worker:  celery -A app.core.celery_app:celery_app worker --loglevel=info --concurrency=2
beat:    celery -A app.core.celery_app:celery_app beat --loglevel=info
