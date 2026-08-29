# Sample monorepo

A deliberately small but realistic monorepo used to demonstrate and test repograph.

It contains three deployable applications and one shared library:

- `apps/api` — a Python FastAPI order service backed by PostgreSQL and Redis.
- `apps/web` — a React front end that calls the API.
- `apps/worker` — a Celery worker that consumes order events from Kafka.
- `packages/shared` — domain models and event contracts shared by the API and the worker.

It also ships a few intentional problems (a hardcoded secret, string-built SQL, a permissive
security group) so the security output has something to find.
