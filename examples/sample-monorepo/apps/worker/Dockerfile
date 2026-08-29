FROM python:3.11-slim
WORKDIR /srv
COPY . .
RUN pip install -e .
USER 1001
CMD ["celery", "-A", "worker.tasks", "worker", "--loglevel=info"]
