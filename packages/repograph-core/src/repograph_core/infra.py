"""Infrastructure discovery: containers, orchestration, IaC and CI pipelines."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .model import Evidence, ExternalSystem
from .parsers import load_yaml, load_yaml_all
from .util import slug

# Container images that clearly mean "this is a backing service".
IMAGE_SYSTEMS: List[Tuple[str, str, str, str]] = [
    (r"postgres|timescale|pgvector", "PostgreSQL", "database", "PostgreSQL"),
    (r"mysql|mariadb", "MySQL / MariaDB", "database", "MySQL"),
    (r"mongo", "MongoDB", "database", "MongoDB"),
    (r"redis|valkey", "Redis", "cache", "Redis"),
    (r"memcached", "Memcached", "cache", "Memcached"),
    (r"kafka|redpanda|cp-kafka", "Apache Kafka", "queue", "Kafka"),
    (r"zookeeper", "ZooKeeper", "queue", "ZooKeeper"),
    (r"rabbitmq", "RabbitMQ", "queue", "RabbitMQ"),
    (r"nats", "NATS", "queue", "NATS"),
    (r"elasticsearch|opensearch", "Elasticsearch / OpenSearch", "search", "Elasticsearch"),
    (r"minio", "MinIO", "storage", "MinIO"),
    (r"localstack", "LocalStack (AWS emulation)", "api", "LocalStack"),
    (r"clickhouse", "ClickHouse", "database", "ClickHouse"),
    (r"cassandra|scylla", "Cassandra", "database", "Cassandra"),
    (r"neo4j", "Neo4j", "database", "Neo4j"),
    (r"prometheus", "Prometheus", "observability", "Prometheus"),
    (r"grafana", "Grafana", "observability", "Grafana"),
    (r"jaeger|zipkin|tempo", "Tracing backend", "observability", "Jaeger/Zipkin"),
    (r"keycloak", "Keycloak", "auth", "Keycloak"),
    (r"vault", "HashiCorp Vault", "auth", "Vault"),
    (r"nginx|traefik|caddy|haproxy|envoy", "Reverse proxy / ingress", "api", "Nginx/Traefik"),
    (r"mailhog|mailpit|maildev", "Mail catcher (dev)", "mail", "MailHog"),
    (r"sqlserver|mssql", "SQL Server", "database", "SQL Server"),
    (r"influxdb", "InfluxDB", "database", "InfluxDB"),
    (r"temporalio", "Temporal", "queue", "Temporal"),
]


def _match_image(image: str) -> Optional[Tuple[str, str, str]]:
    for pattern, name, kind, tech in IMAGE_SYSTEMS:
        if re.search(pattern, image, re.I):
            return name, kind, tech
    return None


class InfraScanner:
    def __init__(self) -> None:
        self.containers: List[Dict[str, Any]] = []
        self.dockerfiles: List[Dict[str, Any]] = []
        self.kubernetes: List[Dict[str, Any]] = []
        self.terraform: List[Dict[str, Any]] = []
        self.ci: List[Dict[str, Any]] = []
        self.serverless: List[Dict[str, Any]] = []
        self.helm: List[Dict[str, Any]] = []
        self.systems: Dict[str, ExternalSystem] = {}
        self.env_files: Dict[str, Dict[str, str]] = {}
        self.notes: List[str] = []

    # ------------------------------------------------------------- dispatch
    def scan(self, rel: str, text: str) -> None:
        name = rel.rsplit("/", 1)[-1].lower()
        try:
            if name.startswith("dockerfile") or name.endswith(".dockerfile"):
                self._dockerfile(rel, text)
            elif re.match(r"(docker-)?compose[.\w-]*\.ya?ml$", name):
                self._compose(rel, text)
            elif name == "serverless.yml" or name == "serverless.yaml":
                self._serverless(rel, text)
            elif rel.endswith(".tf"):
                self._terraform(rel, text)
            elif "/.github/workflows/" in "/" + rel and name.endswith((".yml", ".yaml")):
                self._github_actions(rel, text)
            elif name in (".gitlab-ci.yml", "azure-pipelines.yml", "bitbucket-pipelines.yml", "cloudbuild.yaml"):
                self._generic_ci(rel, text)
            elif name == "jenkinsfile":
                self.ci.append({"file": rel, "system": "Jenkins", "jobs": re.findall(r"stage\(['\"]([^'\"]+)", text)})
            elif name == "chart.yaml":
                self._helm(rel, text)
            elif name.endswith((".yml", ".yaml")):
                self._maybe_kubernetes(rel, text)
        except Exception as exc:  # never let odd YAML break a scan
            self.notes.append(f"{rel}: {type(exc).__name__}")

    # ------------------------------------------------------------ dockerfile
    def _dockerfile(self, rel: str, text: str) -> None:
        stages = re.findall(r"^\s*FROM\s+(\S+)(?:\s+AS\s+(\S+))?", text, re.M | re.I)
        ports = [int(p) for p in re.findall(r"^\s*EXPOSE\s+(\d+)", text, re.M | re.I)]
        user = re.findall(r"^\s*USER\s+(\S+)", text, re.M | re.I)
        entry = re.findall(r"^\s*(?:ENTRYPOINT|CMD)\s+(.+)$", text, re.M | re.I)
        env = dict(re.findall(r"^\s*ENV\s+([A-Z_][A-Z0-9_]*)[\s=]+(\S+)", text, re.M | re.I))
        self.dockerfiles.append({
            "file": rel,
            "base_images": [s[0] for s in stages],
            "stages": [s[1] for s in stages if s[1]],
            "ports": ports,
            "user": user[-1] if user else "root (implicit)",
            "entrypoint": entry[-1].strip()[:200] if entry else "",
            "env": env,
            "multistage": len(stages) > 1,
        })

    # --------------------------------------------------------------- compose
    def _compose(self, rel: str, text: str) -> None:
        data = load_yaml(text)
        if not isinstance(data, dict):
            return
        services = data.get("services")
        if not isinstance(services, dict):
            return
        for name, spec in services.items():
            if not isinstance(spec, dict):
                continue
            image = str(spec.get("image", "") or "")
            build = spec.get("build")
            build_ctx = ""
            if isinstance(build, str):
                build_ctx = build
            elif isinstance(build, dict):
                build_ctx = str(build.get("context", "") or "")
            ports = _as_list(spec.get("ports"))
            env = spec.get("environment")
            env_keys: List[str] = []
            if isinstance(env, dict):
                env_keys = [str(k) for k in env]
            elif isinstance(env, list):
                env_keys = [str(e).split("=")[0] for e in env]
            raw_depends = spec.get("depends_on")
            depends = list(raw_depends) if isinstance(raw_depends, dict) else _as_list(raw_depends)
            entry = {
                "name": str(name),
                "image": image,
                "build": build_ctx,
                "ports": [str(p) for p in ports],
                "env_keys": env_keys,
                "depends_on": [str(d) for d in depends],
                "file": rel,
                "volumes": [str(v) for v in _as_list(spec.get("volumes"))],
            }
            self.containers.append(entry)
            hit = _match_image(image) if image else None
            if hit:
                sys_name, kind, tech = hit
                sid = f"ext-{slug(sys_name)}"
                system = self.systems.setdefault(
                    sid, ExternalSystem(id=sid, name=sys_name, kind=kind, technology=tech,
                                        description=f"Runs as container '{name}' ({image})")
                )
                system.evidence.append(Evidence(file=rel, note=f"service {name}: {image}"))

    # ------------------------------------------------------------ kubernetes
    def _maybe_kubernetes(self, rel: str, text: str) -> None:
        if "apiVersion" not in text or "kind:" not in text:
            return
        for doc in load_yaml_all(text):
            if not isinstance(doc, dict) or "kind" not in doc:
                continue
            meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
            spec = doc.get("spec") if isinstance(doc.get("spec"), dict) else {}
            images = _collect(spec, "image")
            ports = [str(p) for p in _collect(spec, "containerPort") + _collect(spec, "port")]
            entry = {
                "kind": str(doc.get("kind")),
                "name": str(meta.get("name", "")) if isinstance(meta, dict) else "",
                "namespace": str(meta.get("namespace", "")) if isinstance(meta, dict) else "",
                "images": [str(i) for i in images],
                "ports": ports,
                "replicas": spec.get("replicas"),
                "file": rel,
            }
            self.kubernetes.append(entry)
            for image in entry["images"]:
                hit = _match_image(image)
                if hit:
                    sys_name, kind, tech = hit
                    sid = f"ext-{slug(sys_name)}"
                    system = self.systems.setdefault(
                        sid, ExternalSystem(id=sid, name=sys_name, kind=kind, technology=tech,
                                            description=f"Deployed in Kubernetes ({image})")
                    )
                    system.evidence.append(Evidence(file=rel, note=f"{entry['kind']} {entry['name']}"))

    # ------------------------------------------------------------- terraform
    _TF_BLOCK = re.compile(r"^(resource|data|module|provider)\s+\"([^\"]+)\"(?:\s+\"([^\"]+)\")?", re.M)

    def _terraform(self, rel: str, text: str) -> None:
        for match in self._TF_BLOCK.finditer(text):
            block, first, second = match.group(1), match.group(2), match.group(3)
            entry = {
                "block": block,
                "type": first,
                "name": second or "",
                "provider": first.split("_")[0] if block in ("resource", "data") else first,
                "file": rel,
                "line": text.count("\n", 0, match.start()) + 1,
            }
            self.terraform.append(entry)
            hit = _match_image(first.replace("_", " "))
            if hit and block == "resource":
                sys_name, kind, tech = hit
                sid = f"ext-{slug(sys_name)}"
                system = self.systems.setdefault(
                    sid, ExternalSystem(id=sid, name=sys_name, kind=kind, technology=tech,
                                        description="Provisioned by Terraform")
                )
                system.evidence.append(Evidence(file=rel, line=entry["line"], note=first))

    # --------------------------------------------------------------- ci / cd
    def _github_actions(self, rel: str, text: str) -> None:
        data = load_yaml(text)
        if not isinstance(data, dict):
            return
        jobs = data.get("jobs") if isinstance(data.get("jobs"), dict) else {}
        triggers = data.get("on") if data.get("on") is not None else data.get(True)
        job_entries = []
        for name, spec in (jobs or {}).items():
            if not isinstance(spec, dict):
                continue
            steps = spec.get("steps") if isinstance(spec.get("steps"), list) else []
            uses = [str(s.get("uses")) for s in steps if isinstance(s, dict) and s.get("uses")]
            runs = [str(s.get("run", ""))[:120] for s in steps if isinstance(s, dict) and s.get("run")]
            job_entries.append({
                "name": str(name),
                "runs_on": str(spec.get("runs-on", "")),
                "uses": uses[:12],
                "commands": runs[:12],
                "needs": [str(n) for n in _as_list(spec.get("needs"))],
            })
        self.ci.append({
            "file": rel,
            "system": "GitHub Actions",
            "name": str(data.get("name", rel.rsplit("/", 1)[-1])),
            "triggers": _trigger_names(triggers),
            "jobs": job_entries,
        })

    def _generic_ci(self, rel: str, text: str) -> None:
        data = load_yaml(text)
        jobs: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ("stages", "variables", "image", "default", "include", "workflow", "trigger", "pool"):
                    continue
                if isinstance(value, dict) and ("script" in value or "steps" in value or "stage" in value):
                    jobs.append({"name": str(key), "stage": str(value.get("stage", ""))})
        name = rel.rsplit("/", 1)[-1]
        self.ci.append({"file": rel, "system": {"gitlab-ci.yml": "GitLab CI"}.get(name, name),
                        "name": name, "triggers": [], "jobs": jobs})

    def _serverless(self, rel: str, text: str) -> None:
        data = load_yaml(text)
        if not isinstance(data, dict):
            return
        functions = data.get("functions") if isinstance(data.get("functions"), dict) else {}
        entries = []
        for name, spec in functions.items():
            if not isinstance(spec, dict):
                continue
            entries.append({
                "name": str(name),
                "handler": str(spec.get("handler", "")),
                "events": [list(e.keys())[0] if isinstance(e, dict) and e else str(e)
                           for e in _as_list(spec.get("events"))],
            })
        self.serverless.append({
            "file": rel,
            "service": str(data.get("service", "")),
            "provider": (data.get("provider") or {}).get("name", "") if isinstance(data.get("provider"), dict) else "",
            "runtime": (data.get("provider") or {}).get("runtime", "")
                       if isinstance(data.get("provider"), dict) else "",
            "functions": entries,
        })

    def _helm(self, rel: str, text: str) -> None:
        data = load_yaml(text)
        if isinstance(data, dict):
            self.helm.append({"file": rel, "name": str(data.get("name", "")),
                              "version": str(data.get("version", "")),
                              "description": str(data.get("description", ""))})

    # --------------------------------------------------------------- output
    def to_dict(self) -> Dict[str, Any]:
        return {
            "containers": self.containers,
            "dockerfiles": self.dockerfiles,
            "kubernetes": self.kubernetes,
            "terraform": self.terraform,
            "ci": self.ci,
            "serverless": self.serverless,
            "helm": self.helm,
            "notes": self.notes,
        }


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return [value]


def _collect(node: Any, key: str) -> List[Any]:
    found: List[Any] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for k, v in current.items():
                if k == key and isinstance(v, (str, int)):
                    found.append(v)
                else:
                    stack.append(v)
        elif isinstance(current, list):
            stack.extend(current)
    return found


def _trigger_names(triggers: Any) -> List[str]:
    if isinstance(triggers, dict):
        return [str(k) for k in triggers]
    if isinstance(triggers, list):
        return [str(t) for t in triggers]
    if triggers:
        return [str(triggers)]
    return []
