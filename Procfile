web: python -c "import app; app.init_runtime()" && gunicorn app:app --bind 0.0.0.0:$PORT --log-file - --access-logfile - --error-logfile -
