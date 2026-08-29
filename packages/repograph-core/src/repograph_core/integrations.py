"""External system detection.

Signature matching over source and config files: which databases, queues,
caches, cloud services and third party APIs this code actually talks to, with
file/line evidence for every claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .evidence_quality import (
    PROSE_KINDS,
    is_comment_line,
    is_pattern_catalogue,
    is_pattern_definition,
    is_xml_namespace,
    spans_whole_raw_string,
)
from .model import Evidence, ExternalSystem
from .util import slug

# (id, display name, kind, technology, regex)
SIGNATURES: List[Tuple[str, str, str, str, str]] = [
    # --- relational databases
    ("postgres", "PostgreSQL", "database", "PostgreSQL",
     r"postgres(?:ql)?://|\bpsycopg2?\b|\basyncpg\b|\bpg\.Pool\b|require\(['\"]pg['\"]\)|from\s+['\"]pg['\"]|Npgsql|jdbc:postgresql|POSTGRES_(?:HOST|USER|DB|PASSWORD)|gorm\.io/driver/postgres|lib/pq"),
    ("mysql", "MySQL / MariaDB", "database", "MySQL",
     r"mysql(?:2)?://|jdbc:mysql|\bmysql2?\b|MySqlConnection|go-sql-driver/mysql|MYSQL_(?:HOST|USER|DATABASE|ROOT_PASSWORD)|mariadb"),
    ("sqlite", "SQLite", "database", "SQLite",
     r"sqlite3?://|\bsqlite3\b|\.sqlite3?\b|Microsoft\.Data\.Sqlite|mattn/go-sqlite3"),
    ("mssql", "SQL Server", "database", "Microsoft SQL Server",
     r"jdbc:sqlserver|SqlConnection|mssql://|Server=.*Database=|System\.Data\.SqlClient|denisenkom/go-mssqldb"),
    ("oracle", "Oracle Database", "database", "Oracle",
     r"jdbc:oracle|cx_Oracle|oracledb|OracleConnection"),
    ("cockroach", "CockroachDB", "database", "CockroachDB", r"cockroach(?:db|labs)"),
    # --- document / kv / graph
    ("mongodb", "MongoDB", "database", "MongoDB",
     r"mongodb(?:\+srv)?://|\bpymongo\b|\bmongoose\b|MongoClient|MONGO_(?:URI|URL|HOST)|go\.mongodb\.org"),
    ("redis", "Redis", "cache", "Redis",
     r"redis://|rediss://|\bioredis\b|\bredis\.createClient|StrictRedis|Redis\(|go-redis|StackExchange\.Redis|REDIS_(?:URL|HOST)"),
    ("memcached", "Memcached", "cache", "Memcached", r"memcached?|pylibmc|gomemcache"),
    ("dynamodb", "DynamoDB", "database", "AWS DynamoDB",
     r"DynamoDB|dynamodb|boto3\.resource\(['\"]dynamodb"),
    ("cassandra", "Cassandra", "database", "Apache Cassandra", r"cassandra|datastax|cqlsh|gocql"),
    ("neo4j", "Neo4j", "database", "Neo4j", r"neo4j://|bolt://|neo4j-driver"),
    ("clickhouse", "ClickHouse", "database", "ClickHouse", r"clickhouse"),
    ("snowflake", "Snowflake", "database", "Snowflake", r"snowflake(?:-connector|\.com|_conn)"),
    ("bigquery", "BigQuery", "database", "Google BigQuery", r"bigquery|BigQueryClient"),
    ("couchbase", "Couchbase", "database", "Couchbase", r"couchbase"),
    ("influx", "InfluxDB", "database", "InfluxDB", r"influxdb"),
    ("supabase", "Supabase", "database", "Supabase", r"supabase"),
    ("firebase", "Firebase", "database", "Google Firebase",
     r"firebase|firestore|FIREBASE_(?:API_KEY|PROJECT)"),
    # --- search
    ("elasticsearch", "Elasticsearch / OpenSearch", "search", "Elasticsearch",
     r"elasticsearch|opensearch|ELASTIC_(?:URL|HOST)"),
    ("algolia", "Algolia", "search", "Algolia", r"algolia"),
    ("meilisearch", "Meilisearch", "search", "Meilisearch", r"meilisearch"),
    # --- messaging
    ("kafka", "Apache Kafka", "queue", "Kafka",
     r"\bkafka\b|KafkaProducer|KafkaConsumer|confluent[_-]kafka|segmentio/kafka-go|KAFKA_(?:BROKERS|BOOTSTRAP)"),
    ("rabbitmq", "RabbitMQ", "queue", "RabbitMQ",
     r"amqps?://|\bpika\b|\bamqplib\b|RabbitMQ|streadway/amqp"),
    ("sqs", "AWS SQS", "queue", "Amazon SQS", r"\bSQS\b|sqs\.amazonaws\.com|boto3\.client\(['\"]sqs"),
    ("sns", "AWS SNS", "queue", "Amazon SNS", r"\bSNS\b|sns\.amazonaws\.com|boto3\.client\(['\"]sns"),
    ("eventbridge", "AWS EventBridge", "queue", "EventBridge", r"EventBridge|events\.amazonaws\.com"),
    ("pubsub", "Google Pub/Sub", "queue", "Google Pub/Sub", r"pubsub|PubSubClient|google-cloud-pubsub"),
    ("servicebus", "Azure Service Bus", "queue", "Azure Service Bus", r"ServiceBus|servicebus\.windows\.net"),
    ("nats", "NATS", "queue", "NATS", r"nats://|nats\.go|\bnats-py\b|jetstream"),
    ("mqtt", "MQTT broker", "queue", "MQTT", r"mqtt://|paho|mosquitto"),
    ("celery", "Celery workers", "queue", "Celery", r"\bcelery\b|CELERY_BROKER"),
    ("sidekiq", "Sidekiq", "queue", "Sidekiq", r"sidekiq"),
    ("bullmq", "BullMQ", "queue", "BullMQ", r"bullmq|new Queue\("),
    ("temporal", "Temporal", "queue", "Temporal", r"temporal\.io|temporalio"),
    # --- storage
    ("s3", "AWS S3", "storage", "Amazon S3",
     r"\bS3\b|s3://|s3\.amazonaws\.com|boto3\.client\(['\"]s3|@aws-sdk/client-s3|AWS_S3_BUCKET"),
    ("gcs", "Google Cloud Storage", "storage", "GCS", r"storage\.googleapis\.com|google-cloud-storage|gs://"),
    ("azureblob", "Azure Blob Storage", "storage", "Azure Blob",
     r"blob\.core\.windows\.net|BlobServiceClient|azure-storage-blob"),
    ("minio", "MinIO", "storage", "MinIO", r"\bminio\b"),
    ("cloudinary", "Cloudinary", "storage", "Cloudinary", r"cloudinary"),
    # --- auth
    ("auth0", "Auth0", "auth", "Auth0", r"auth0"),
    ("okta", "Okta", "auth", "Okta", r"\bokta\b"),
    ("keycloak", "Keycloak", "auth", "Keycloak", r"keycloak"),
    ("cognito", "AWS Cognito", "auth", "Cognito", r"cognito"),
    ("entra", "Microsoft Entra ID", "auth", "Entra ID / Azure AD",
     r"login\.microsoftonline\.com|AzureAD|MicrosoftIdentity|msal"),
    ("oauth", "OAuth / OIDC provider", "auth", "OAuth2 / OIDC",
     r"oauth2?|openid[-_]?connect|\.well-known/openid-configuration"),
    ("jwt", "JWT tokens", "auth", "JWT", r"\bjsonwebtoken\b|\bPyJWT\b|jwt\.sign|jwt\.decode|Bearer "),
    ("ldap", "LDAP / Active Directory", "auth", "LDAP", r"ldaps?://|ldap3|System\.DirectoryServices"),
    # --- payments & commerce
    ("stripe", "Stripe", "payment", "Stripe", r"\bstripe\b|STRIPE_(?:SECRET|API)_KEY"),
    ("paypal", "PayPal", "payment", "PayPal", r"paypal"),
    ("adyen", "Adyen", "payment", "Adyen", r"adyen"),
    ("braintree", "Braintree", "payment", "Braintree", r"braintree"),
    ("vipps", "Vipps", "payment", "Vipps", r"\bvipps\b"),
    ("klarna", "Klarna", "payment", "Klarna", r"klarna"),
    # --- comms
    ("sendgrid", "SendGrid", "mail", "SendGrid", r"sendgrid"),
    ("ses", "AWS SES", "mail", "Amazon SES", r"\bSES\b|email\.amazonaws\.com|boto3\.client\(['\"]ses"),
    ("mailgun", "Mailgun", "mail", "Mailgun", r"mailgun"),
    ("smtp", "SMTP server", "mail", "SMTP", r"smtp://|smtplib|SMTP_(?:HOST|PORT|USER)|nodemailer"),
    ("twilio", "Twilio", "mail", "Twilio", r"twilio"),
    ("slack", "Slack", "api", "Slack API", r"hooks\.slack\.com|slack_sdk|@slack/"),
    ("teams", "Microsoft Teams", "api", "Teams webhook", r"outlook\.office\.com/webhook|teams\.microsoft\.com"),
    # --- observability
    ("sentry", "Sentry", "observability", "Sentry", r"sentry"),
    ("datadog", "Datadog", "observability", "Datadog", r"datadog|dd-trace|DD_API_KEY"),
    ("prometheus", "Prometheus", "observability", "Prometheus", r"prometheus|/metrics\b|prom_client"),
    ("grafana", "Grafana", "observability", "Grafana", r"grafana"),
    ("otel", "OpenTelemetry collector", "observability", "OpenTelemetry",
     r"opentelemetry|otel[-_]|OTEL_EXPORTER"),
    ("newrelic", "New Relic", "observability", "New Relic", r"newrelic|new_relic"),
    ("elk", "Logstash / ELK", "observability", "Logstash", r"logstash|filebeat"),
    ("appinsights", "Azure Application Insights", "observability", "App Insights",
     r"ApplicationInsights|APPINSIGHTS_"),
    # --- AI
    ("openai", "OpenAI API", "ai", "OpenAI", r"api\.openai\.com|\bopenai\b|OPENAI_API_KEY"),
    ("anthropic", "Anthropic API", "ai", "Anthropic", r"api\.anthropic\.com|anthropic|ANTHROPIC_API_KEY"),
    ("bedrock", "AWS Bedrock", "ai", "Bedrock", r"bedrock"),
    ("vertex", "Google Vertex AI", "ai", "Vertex AI", r"vertexai|aiplatform"),
    ("huggingface", "Hugging Face", "ai", "Hugging Face", r"huggingface|transformers\b"),
    ("ollama", "Ollama", "ai", "Ollama", r"ollama"),
    # --- cloud platforms & infra services
    ("aws", "AWS", "api", "Amazon Web Services",
     r"\bboto3\b|aws-sdk|amazonaws\.com|AWS_ACCESS_KEY_ID|@aws-sdk/"),
    ("gcp", "Google Cloud", "api", "Google Cloud",
     r"google-cloud|googleapis\.com|GOOGLE_APPLICATION_CREDENTIALS"),
    ("azure", "Microsoft Azure", "api", "Azure",
     r"azure-|Azure\.Identity|AZURE_(?:CLIENT_ID|TENANT_ID)|\.azure\.com"),
    ("k8sapi", "Kubernetes API", "api", "Kubernetes", r"kubernetes\.client|client-go|KUBERNETES_SERVICE_HOST"),
    ("docker", "Docker daemon", "api", "Docker", r"/var/run/docker\.sock|docker\.from_env"),
    ("vault", "HashiCorp Vault", "auth", "Vault", r"hashicorp/vault|VAULT_ADDR|hvac"),
    ("github", "GitHub API", "api", "GitHub", r"api\.github\.com|@octokit|PyGithub|GITHUB_TOKEN"),
    ("gitlab", "GitLab API", "api", "GitLab", r"gitlab\.com/api|python-gitlab"),
    ("jira", "Jira", "api", "Atlassian Jira", r"atlassian\.net|jira"),
    ("salesforce", "Salesforce", "api", "Salesforce", r"salesforce|force\.com"),
    ("shopify", "Shopify", "api", "Shopify", r"shopify"),
    ("maps", "Maps provider", "api", "Maps API", r"maps\.googleapis\.com|mapbox"),
    ("graphql_client", "GraphQL upstream", "api", "GraphQL", r"ApolloClient|graphql-request"),
    ("grpc_client", "gRPC upstream", "api", "gRPC", r"grpc\.Dial|grpc\.insecure_channel|createChannel"),
]

_COMPILED: List[Tuple[str, str, str, str, re.Pattern]] = [
    (sid, name, kind, tech, re.compile(pattern, re.I))
    for sid, name, kind, tech, pattern in SIGNATURES
]

# Generic outbound HTTP endpoints: http(s)://host used from code.
_URL_RE = re.compile(r"https?://([a-zA-Z0-9._\-]+\.[a-zA-Z]{2,})(?::\d+)?(/[\w./\-{}$:]*)?")
_LOCAL_HOSTS = re.compile(
    r"^(localhost|127\.0\.0\.1|0\.0\.0\.0|host\.docker\.internal|example\.(com|org)|"
    r"schemas?\..*|www\.w3\.org|.*\.local)$", re.I
)
_DOC_HOSTS = re.compile(
    r"(github\.com|gitlab\.com|npmjs\.com|pypi\.org|golang\.org|apache\.org|mit-license\.org|"
    r"stackoverflow\.com|wikipedia\.org|readthedocs\.io|medium\.com|youtube\.com|docs\.|"
    r"opensource\.org|creativecommons\.org|json-schema\.org|maven\.apache\.org|shields\.io|"
    r"badge\.|img\.|fonts\.googleapis\.com|cdn\.jsdelivr\.net|unpkg\.com|cdnjs\.cloudflare\.com)",
    re.I,
)

_ENV_RE = re.compile(
    r"""(?:os\.(?:getenv|environ(?:\.get)?)\s*\(?\s*["']([A-Z][A-Z0-9_]{2,})["']"""
    r"""|process\.env\.([A-Z][A-Z0-9_]{2,})"""
    r"""|process\.env\[["']([A-Z][A-Z0-9_]{2,})["']\]"""
    r"""|System\.getenv\(\s*["']([A-Z][A-Z0-9_]{2,})["']"""
    r"""|os\.Getenv\(\s*["']([A-Z][A-Z0-9_]{2,})["']"""
    r"""|ENV\[["']([A-Z][A-Z0-9_]{2,})["']\]"""
    r"""|Environment\.GetEnvironmentVariable\(\s*["']([A-Z][A-Z0-9_]{2,})["']"""
    r"""|\$\{?([A-Z][A-Z0-9_]{2,})\}?)"""
)


_PY_DOCSTRING = re.compile(r'("""|\'\'\')(?:.|\n)*?\1')


def _docstring_spans(rel: str, text: str) -> List[Tuple[int, int]]:
    """Byte ranges of Python docstrings — prose that happens to live in a .py."""
    if not rel.endswith(".py"):
        return []
    return [(m.start(), m.end()) for m in _PY_DOCSTRING.finditer(text)]


def _inside(spans: List[Tuple[int, int]], position: int) -> bool:
    return any(start <= position < end for start, end in spans)


@dataclass
class IntegrationHit:
    system_id: str
    file: str
    line: int
    snippet: str
    app: str = ""


class IntegrationScanner:
    """Collects external system evidence file by file."""

    def __init__(self) -> None:
        self.systems: Dict[str, ExternalSystem] = {}
        self.env_vars: Dict[str, List[str]] = {}
        self.hosts: Dict[str, List[Evidence]] = {}
        # A system is only real once something that runs has referenced it.
        # Prose and pattern tables can corroborate, never establish.
        self.established: set = set()
        self._prose_lines: set = set()
        self._defining_lines: set = set()

    def scan_file(self, rel: str, text: str, app: str, kind: str) -> None:
        if not text:
            return
        lines = text.splitlines()
        head = text if len(text) < 400_000 else text[:400_000]

        prose = kind in PROSE_KINDS
        doc_spans = _docstring_spans(rel, head)

        # Collect first, judge second: whether a line defines a pattern or uses
        # a service is partly a property of the file it sits in.
        hits: List[Tuple[str, str, str, str, int, str]] = []
        for sid, name, system_kind, tech, pattern in _COMPILED:
            match = pattern.search(head)
            if match is None:
                continue
            line_no = head.count("\n", 0, match.start()) + 1
            snippet = lines[line_no - 1].strip()[:160] if line_no - 1 < len(lines) else ""
            if _inside(doc_spans, match.start()) or is_comment_line(snippet):
                self._prose_lines.add((rel, line_no))
            if spans_whole_raw_string(snippet, match.group(0)):
                self._defining_lines.add((rel, line_no))
            hits.append((sid, name, system_kind, tech, line_no, snippet))

        catalogue = is_pattern_catalogue([h[5] for h in hits])
        for sid, name, system_kind, tech, line_no, snippet in hits:
            documented = prose or (rel, line_no) in self._prose_lines
            defining = (catalogue or is_pattern_definition(snippet)
                        or (rel, line_no) in self._defining_lines)
            system = self.systems.get(sid)
            if system is None:
                system = ExternalSystem(id=f"ext-{sid}", name=name, kind=system_kind, technology=tech)
                self.systems[sid] = system
            note = "mentioned in prose" if documented else (
                "matches a pattern definition" if defining else "")
            if len(system.evidence) < 12:
                system.evidence.append(
                    Evidence(file=rel, line=line_no, snippet=snippet, note=note))
            if not documented and not defining:
                self.established.add(sid)
                if app and app not in system.apps:
                    system.apps.append(app)

        if kind in ("source", "config", "infra"):
            self._scan_urls(rel, head, lines, app)
            self._scan_env(rel, head)

    def _scan_urls(self, rel: str, text: str, lines: List[str], app: str) -> None:
        for match in _URL_RE.finditer(text):
            host = match.group(1).lower()
            if _LOCAL_HOSTS.match(host) or _DOC_HOSTS.search(host):
                continue
            line_no = text.count("\n", 0, match.start()) + 1
            snippet = lines[line_no - 1].strip()[:160] if line_no - 1 < len(lines) else ""
            # www.w3.org in an xmlns is the vocabulary's name; nothing calls it.
            if is_xml_namespace(snippet, match.group(0)):
                continue
            bucket = self.hosts.setdefault(host, [])
            if len(bucket) < 6:
                bucket.append(Evidence(file=rel, line=line_no, snippet=snippet, note=app))

    def _scan_env(self, rel: str, text: str) -> None:
        for match in _ENV_RE.finditer(text):
            name = next((g for g in match.groups() if g), "")
            if not name or name in ("PATH", "HOME", "USER", "PWD", "SHELL", "LANG", "TERM"):
                continue
            files = self.env_vars.setdefault(name, [])
            if rel not in files and len(files) < 10:
                files.append(rel)

    def finish(self, min_host_hits: int = 1) -> List[ExternalSystem]:
        # Drop anything only ever named by prose or by a signature table, and
        # with it the evidence that merely restated the name.
        for sid in [s for s in self.systems if s not in self.established]:
            del self.systems[sid]
        for system in self.systems.values():
            system.evidence = [e for e in system.evidence if not e.note] or system.evidence
        systems = list(self.systems.values())
        # A host that merely restates an already-detected system (api.stripe.com
        # next to "Stripe") would double count it.
        covered = {sid for sid in self.systems}
        for host, evidence in sorted(self.hosts.items()):
            if len(evidence) < min_host_hits:
                continue
            if any(sid in host.replace(".", "") or sid in host for sid in covered if len(sid) > 3):
                continue
            sid = f"ext-host-{slug(host)}"
            systems.append(
                ExternalSystem(
                    id=sid,
                    name=host,
                    kind="api",
                    technology="HTTPS",
                    direction="outbound",
                    evidence=evidence,
                    apps=sorted({e.note for e in evidence if e.note}),
                    description="Outbound HTTP endpoint referenced in code or configuration",
                )
            )
        for system in systems:
            if not system.description:
                system.description = f"{system.technology} — detected from {len(system.evidence)} reference(s)"
        systems.sort(key=lambda s: (s.kind, s.name.lower()))
        return systems


ENV_HINTS = {
    "DATABASE": "database", "DB_": "database", "POSTGRES": "database", "MYSQL": "database",
    "MONGO": "database", "REDIS": "cache", "KAFKA": "queue", "RABBIT": "queue", "AMQP": "queue",
    "S3": "storage", "BUCKET": "storage", "SMTP": "mail", "MAIL": "mail", "STRIPE": "payment",
    "AUTH": "auth", "OAUTH": "auth", "JWT": "auth", "API_KEY": "api", "TOKEN": "auth",
    "SENTRY": "observability", "OTEL": "observability", "AWS": "api", "AZURE": "api", "GCP": "api",
}


def classify_env_var(name: str) -> str:
    for needle, kind in ENV_HINTS.items():
        if needle in name:
            return kind
    return "config"
