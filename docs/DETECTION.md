# What repograph detects

Everything below is derived by static analysis. Each detection records the file and line it came
from, so anything in a report can be verified in seconds.

## Languages

| Language | Imports | Symbols | Endpoints | Notes |
|---|---|---|---|---|
| Python | ✅ (`ast`) | classes, functions, methods, docstrings | Flask, FastAPI, Django, Starlette, aiohttp, Sanic, Celery tasks, Click/Typer | exact module resolution incl. relative imports |
| JavaScript / TypeScript | ✅ | exports, classes, functions, types | Express, Fastify, Koa, NestJS, Next.js (pages + app router), SvelteKit, tRPC, Lambda handlers | resolves `tsconfig` path aliases and workspace packages |
| Vue / Svelte | ✅ | components | via the JS analyzer | |
| Go | ✅ | funcs, methods, structs, interfaces | net/http, Gin, Echo, Chi, Fiber, gorilla/mux | module-aware internal resolution |
| Java / Kotlin / Scala / Groovy | ✅ | classes, interfaces, enums, records | Spring (`@GetMapping`…), JAX-RS | package→file resolution |
| C# | ✅ | classes, interfaces, records | ASP.NET Core attributes and minimal APIs | |
| Ruby | ✅ | classes, modules, methods | Rails `routes.rb`, Sinatra | |
| PHP | ✅ | classes, traits, functions | Laravel `Route::`, Symfony attributes | |
| Rust | ✅ | fns, structs, traits, impls | Actix attributes, Axum `.route()` | |
| Elixir | ✅ | modules, functions | Phoenix router | |
| Swift, Dart, C, C++, Objective-C, Shell | ✅ | types and functions | — | |
| SQL | — | tables, views, procedures | — | feeds the data model |
| Protobuf | ✅ | services, messages | gRPC methods | |
| GraphQL | — | types | Query/Mutation/Subscription fields | |

## Applications and components

An application is a unit that is built, published or deployed on its own. repograph finds them from:

- npm / pnpm / Yarn workspaces, `lerna.json`
- Cargo workspaces, Go modules and `go.work`
- Maven modules, Gradle `settings.gradle` includes, .NET solutions
- Python distributions (`pyproject.toml`, `setup.py`)
- directory conventions: `apps/*`, `services/*`, `packages/*`, `libs/*`, `cmd/*`, `functions/*`

Each application is then split into components by descending its directory tree until every part is
small enough to read in a diagram.

### Application kind

`service`, `frontend`, `job`, `library`, `cli`, `infra`, `docs` or `application` — inferred from
frameworks in use, detected endpoints, manifest hints and directory naming, in that order.

### Architecture style

Detected from directory vocabulary and frameworks: layered (controller/service/repository),
hexagonal / ports & adapters, clean architecture, MVC, CQRS, feature-sliced, event-driven,
serverless, framework MVC, GraphQL API — or "unclassified" when the layout says nothing.

## External systems

Signature matching over source and configuration files across these categories:

- **databases** PostgreSQL, MySQL/MariaDB, SQLite, SQL Server, Oracle, CockroachDB, MongoDB,
  DynamoDB, Cassandra, Neo4j, ClickHouse, Snowflake, BigQuery, Couchbase, InfluxDB, Supabase,
  Firebase
- **caches** Redis, Memcached
- **queues & streams** Kafka, RabbitMQ, SQS, SNS, EventBridge, Google Pub/Sub, Azure Service Bus,
  NATS, MQTT, Celery, Sidekiq, BullMQ, Temporal
- **storage** S3, GCS, Azure Blob, MinIO, Cloudinary
- **search** Elasticsearch/OpenSearch, Algolia, Meilisearch
- **identity** Auth0, Okta, Keycloak, Cognito, Entra ID, generic OAuth/OIDC, JWT, LDAP, Vault
- **payments** Stripe, PayPal, Adyen, Braintree, Klarna, Vipps
- **mail & messaging** SendGrid, SES, Mailgun, SMTP, Twilio, Slack, Teams
- **observability** Sentry, Datadog, Prometheus, Grafana, OpenTelemetry, New Relic, ELK,
  Application Insights
- **AI** OpenAI, Anthropic, Bedrock, Vertex AI, Hugging Face, Ollama
- **clouds and platforms** AWS, GCP, Azure, Kubernetes API, Docker, GitHub, GitLab, Jira,
  Salesforce, Shopify, maps providers
- **any other host** referenced by an `https://` URL in code or configuration

Container images in Compose and Kubernetes manifests are matched too, so a `postgres:15` service
becomes a PostgreSQL dependency even if no code string mentions it.

## Infrastructure

Dockerfiles (base images, stages, exposed ports, user, entrypoint, env), Docker Compose services,
Kubernetes objects, Terraform resources/data/modules/providers, Helm charts, `serverless.yml`
functions, GitHub Actions, GitLab CI, Azure Pipelines, Bitbucket Pipelines, Cloud Build and
Jenkinsfiles — plus every environment variable the code reads.

## Security rules

### Secrets

AWS keys, GitHub/GitLab/Slack/npm/SendGrid/Stripe/Google/OpenAI/Anthropic tokens, private keys,
JWTs, Azure storage keys, database URLs containing a password, hardcoded password/secret
assignments, basic-auth and bearer headers, and high-entropy values assigned to
key/token/secret-shaped names. Findings are redacted in the output, downgraded in test, fixture, example and
documentation files, skipped inside Python docstrings, and suppressed when the value is an obvious
placeholder or reads as prose ("development key") rather than a credential.

### Code patterns (with CWE)

SQL injection via string building (CWE-89), command injection (CWE-78), dynamic code execution
(CWE-95), unsafe deserialisation — pickle, `yaml.load`, Java `ObjectInputStream`, BinaryFormatter
(CWE-502), XSS sinks (CWE-79), wildcard CORS (CWE-942), disabled CSRF (CWE-352), weak hashes and
ciphers (CWE-327), insecure randomness (CWE-338), disabled TLS verification (CWE-295), plaintext
HTTP (CWE-319), JWT verification weakened (CWE-347), debug mode enabled (CWE-489), world-writable
permissions (CWE-732), path traversal (CWE-22), SSRF (CWE-918), open redirect (CWE-601), mass
assignment (CWE-915), authentication disabled (CWE-306), secrets in logs (CWE-532).

Rules that describe a property of a whole file (a committed `.env`, a container with no `USER`)
report once per file rather than once per line.

### Infrastructure rules

Containers running as root, unpinned base images, secrets in build args, `curl | sh`, privileged
Kubernetes workloads, missing resource limits, security groups open to `0.0.0.0/0`, public object
storage, unencrypted storage, `pull_request_target`, script injection through GitHub contexts,
unpinned third-party actions, and committed `.env` files.

### Dependencies

- **advisories** — OSV.dev lookup with `--online`, covering npm, PyPI, Go, Maven, NuGet,
  crates.io, RubyGems, Packagist, Pub and Hex, with CVSS v3 scoring done locally.
- **hygiene, always offline** — missing lockfiles, unpinned versions, deprecated packages,
  declared-but-never-imported packages, and imported-but-never-declared packages.
