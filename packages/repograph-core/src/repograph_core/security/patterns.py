"""Insecure-pattern rules.

Deterministic regex rules with a CWE, a severity and a fix for each. This is a
linting-grade check, not a taint analysis: every finding names the file and line
so a human (or an agent) can confirm it in seconds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Sequence

from ..evidence_quality import (
    declares_non_security_use,
    is_pattern_definition,
    is_xml_namespace,
)
from ..model import Finding
from ..util import slug


@dataclass
class Rule:
    id: str
    title: str
    pattern: str
    severity: str = "medium"
    cwe: str = ""
    languages: Sequence[str] = ()
    files: str = ""              # regex on the path
    not_files: str = ""
    confidence: str = "medium"
    remediation: str = ""
    category: str = "code"
    once_per_file: bool = False
    references: List[str] = field(default_factory=list)
    _compiled: Optional[re.Pattern] = None

    def compiled(self) -> re.Pattern:
        if self._compiled is None:
            self._compiled = re.compile(self.pattern, re.M)
        return self._compiled

    def applies(self, rel: str, language: str) -> bool:
        if self.languages and language not in self.languages:
            return False
        if self.files and not re.search(self.files, rel, re.I):
            return False
        if self.not_files and re.search(self.not_files, rel, re.I):
            return False
        return True


PY = ("Python",)
JS = ("JavaScript", "TypeScript", "Vue", "Svelte")
JVM = ("Java", "Kotlin", "Scala", "Groovy")
GO = ("Go",)
NET = ("C#",)
PHP = ("PHP",)
RUBY = ("Ruby",)

RULES: List[Rule] = [
    # ---------------------------------------------------------- injection
    Rule("py-sql-format", "SQL built with string formatting",
         r"""(?is)(?:execute|executemany|raw|text)\s*\(\s*f?["'].{0,300}?(?:SELECT|INSERT|UPDATE|DELETE)"""
         r""".{0,300}?["']\s*(?:%|\+|\.format\()|f["'][^"'\n]{0,200}?(?:SELECT|INSERT|UPDATE|DELETE)[^"'\n]{0,200}?\{""",
         "high", "CWE-89", PY, confidence="medium",
         remediation="Use parameterised queries (``cursor.execute(sql, params)``) or the ORM's binding API."),
    Rule("js-sql-concat", "SQL built with template literals or concatenation",
         r"""(?is)(?:query|execute|raw)\s*\(\s*[`"'].{0,300}?(?:SELECT|INSERT|UPDATE|DELETE).{0,300}?(?:\$\{|["']\s*\+)""",
         "high", "CWE-89", JS, confidence="medium",
         remediation="Use parameterised queries ($1 placeholders / prepared statements) instead of interpolation."),
    Rule("jvm-sql-concat", "SQL built with string concatenation",
         r"""(?is)(?:createQuery|executeQuery|createNativeQuery|prepareStatement)\s*\(\s*".{0,300}?(?:SELECT|INSERT|UPDATE|DELETE).{0,300}?"\s*\+""",
         "high", "CWE-89", JVM, remediation="Use bind parameters (``setString``) or JPA criteria queries."),
    Rule("go-sql-fmt", "SQL built with fmt.Sprintf",
         r"(?i)(?:Query|Exec|QueryRow)\w*\(\s*fmt\.Sprintf\(",
         "high", "CWE-89", GO, remediation="Pass query arguments as parameters: ``db.Query(sql, args...)``."),
    Rule("net-sql-concat", "SQL built with string concatenation",
         r"(?i)new Sql(?:Command|DataAdapter)\s*\(\s*\"[^\"]*(?:SELECT|INSERT|UPDATE|DELETE)[^\"]*\"\s*\+",
         "high", "CWE-89", NET, remediation="Use ``SqlParameter`` bindings or an ORM."),
    Rule("py-command-injection", "Shell command built from variables",
         r"(?:subprocess\.(?:run|call|check_output|Popen)\([^)]*shell\s*=\s*True|os\.(?:system|popen)\s*\()",
         "high", "CWE-78", PY, confidence="medium",
         remediation="Pass an argument list without ``shell=True`` so user input cannot be interpreted by a shell."),
    Rule("js-command-injection", "Shell execution with interpolated input",
         r"(?:child_process\.)?exec(?:Sync)?\s*\(\s*[`\"'][^`\"']*\$\{",
         "high", "CWE-78", JS,
         remediation="Use ``execFile``/``spawn`` with an argument array instead of building a shell string."),
    Rule("py-eval", "Dynamic code execution (eval/exec)",
         r"\b(?:eval|exec)\s*\(", "high", "CWE-95", PY, confidence="low",
         remediation="Avoid evaluating dynamic code; parse the input explicitly "
                     "(``ast.literal_eval`` if you need literals)."),
    Rule("js-eval", "Dynamic code execution (eval / new Function)",
         r"\beval\s*\(|new\s+Function\s*\(", "high", "CWE-95", JS, confidence="low",
         remediation="Replace ``eval`` with an explicit parser or a lookup table."),
    Rule("php-eval", "Dynamic code execution", r"\b(?:eval|assert|create_function)\s*\(",
         "high", "CWE-95", PHP, remediation="Remove dynamic evaluation of input."),
    Rule("py-pickle", "Untrusted deserialisation (pickle / marshal)",
         r"\b(?:pickle|cPickle|marshal|dill)\.(?:load|loads)\s*\(", "high", "CWE-502", PY,
         remediation="Use a data format that cannot execute code (JSON, msgpack) for untrusted input."),
    Rule("py-yaml-load", "Unsafe YAML load", r"yaml\.load\s*\((?![^)]*SafeLoader)",
         "high", "CWE-502", PY,
         remediation="Use ``yaml.safe_load`` (or pass ``Loader=yaml.SafeLoader``)."),
    Rule("jvm-deserialize", "Java native deserialisation of untrusted data",
         r"new\s+ObjectInputStream\s*\(", "high", "CWE-502", JVM,
         remediation="Avoid Java serialisation for untrusted input; use JSON with a strict schema."),
    Rule("net-binaryformatter", "BinaryFormatter deserialisation",
         r"BinaryFormatter|NetDataContractSerializer|LosFormatter", "high", "CWE-502", NET,
         remediation="BinaryFormatter is unsafe and removed in .NET 9 — switch to System.Text.Json."),
    # ------------------------------------------------------------- xss/web
    Rule("js-innerhtml", "Raw HTML assignment (possible XSS)",
         r"\.innerHTML\s*=|dangerouslySetInnerHTML|v-html\s*=|\.outerHTML\s*=",
         "medium", "CWE-79", JS, confidence="low",
         remediation="Render text nodes, or sanitise with DOMPurify before injecting HTML."),
    Rule("py-mark-safe", "Template auto-escaping bypassed",
         r"mark_safe\s*\(|\|\s*safe\b|Markup\s*\(", "medium", "CWE-79", PY, confidence="low",
         remediation="Escape user content; only mark trusted, already-sanitised HTML as safe."),
    Rule("cors-wildcard", "CORS allows any origin",
         r"(?i)(?:Access-Control-Allow-Origin[\"']?\s*[:,]\s*[\"']\*|allow_origins\s*=\s*\[\s*[\"']\*|"
         r"origin\s*:\s*[\"']\*|cors\(\s*\)|AllowAnyOrigin\(\))",
         "medium", "CWE-942", confidence="medium",
         remediation="List the exact origins allowed; a wildcard with credentials defeats same-origin protection."),
    Rule("csrf-disabled", "CSRF protection disabled",
         r"(?i)(csrf_exempt|csrf\s*[:=]\s*(?:false|False)|IgnoreAntiforgeryToken|"
         r"WTF_CSRF_ENABLED\s*=\s*False)",
         "medium", "CWE-352", remediation="Keep CSRF protection on for cookie-authenticated state changes."),
    # -------------------------------------------------------------- crypto
    Rule("weak-hash", "Weak hash algorithm (MD5 / SHA-1)",
         r"(?i)\b(?:md5|sha1)\s*\(|hashlib\.(?:md5|sha1)\s*\(|MessageDigest\.getInstance\(\s*\"(?:MD5|SHA-?1)\"|"
         r"MD5\.Create\(\)|crypto\.createHash\(\s*['\"](?:md5|sha1)['\"]",
         "medium", "CWE-327", confidence="medium",
         remediation="Use SHA-256+ for integrity and bcrypt/scrypt/argon2 for passwords."),
    Rule("weak-cipher", "Weak or ECB-mode cipher",
         r"(?i)\b(?:DES|RC4|Blowfish)\b|AES/ECB|MODE_ECB|CipherMode\.ECB",
         "high", "CWE-327", confidence="medium",
         remediation="Use AES-GCM (or ChaCha20-Poly1305) with a random nonce."),
    Rule("insecure-random", "Non-cryptographic randomness used for security value",
         r"(?i)(?:random\.(?:random|randint|choice)|Math\.random\(\)|rand\(\))"
         r"[^\n]{0,60}(?:token|secret|password|key|nonce|salt|otp|session)",
         "medium", "CWE-338", confidence="medium",
         remediation="Use ``secrets``/``crypto.randomBytes``/``SecureRandom`` for security-relevant values."),
    Rule("tls-verify-off", "TLS certificate verification disabled",
         r"(?i)(verify\s*=\s*False|rejectUnauthorized\s*:\s*false|InsecureSkipVerify\s*:\s*true|"
         r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0|ServerCertificateValidationCallback\s*\+?=|"
         r"CURLOPT_SSL_VERIFYPEER\s*,\s*(?:false|0))",
         "high", "CWE-295",
         remediation="Verify certificates; pin a CA bundle instead of disabling verification."),
    Rule("http-url", "Plaintext HTTP endpoint",
         r"[\"']http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|schemas?\.|www\.w3\.org|"
         r"[\w.\-]*\.local)[\w.\-]+", "low", "CWE-319", confidence="low",
         remediation="Use HTTPS for anything leaving the host."),
    Rule("jwt-none", "JWT signature verification weakened",
         r"(?i)(algorithms?\s*[:=]\s*\[?\s*['\"]none['\"]|verify\s*[:=]\s*False[^\n]{0,40}jwt|"
         r"jwt\.decode\([^)]*verify\s*=\s*False)",
         "critical", "CWE-347",
         remediation="Always verify the signature and pin the expected algorithm."),
    # ------------------------------------------------------- config / auth
    Rule("debug-on", "Debug mode enabled",
         r"(?i)\bDEBUG\s*[:=]\s*(?:True|true|1)\b|app\.run\([^)]*debug\s*=\s*True|"
         r"ASPNETCORE_ENVIRONMENT\s*[:=]\s*Development",
         "medium", "CWE-489", not_files=r"(test|spec|local|dev)",
         remediation="Never ship debug mode: it exposes stack traces and, in some frameworks, a remote console."),
    Rule("permissive-chmod", "World-writable permissions",
         r"chmod\s+(?:-R\s+)?0?7[0-7][7]|os\.chmod\([^)]*0o?7[0-7]7", "medium", "CWE-732",
         remediation="Grant the narrowest permissions that work (0640/0750)."),
    Rule("path-traversal", "Filesystem path built from request input",
         r"(?i)(?:open|readFile|readFileSync|File\()\s*\(\s*[^)]*(?:req\.(?:params|query|body)|request\."
         r"(?:args|form|GET|POST)|params\[)", "high", "CWE-22", confidence="medium",
         remediation="Resolve the path and assert it stays inside the intended directory."),
    Rule("ssrf", "Outbound request to a caller-supplied URL",
         r"(?i)(?:requests\.(?:get|post)|axios\.(?:get|post)|fetch|http\.Get|HttpClient\.GetAsync)\s*\(\s*"
         r"(?:req\.(?:params|query|body)|request\.(?:args|form)|params\[|url\s*\))",
         "high", "CWE-918", confidence="low",
         remediation="Allow-list the hosts you may call and reject redirects to internal ranges."),
    Rule("open-redirect", "Redirect target taken from request",
         r"(?i)redirect\s*\(\s*(?:req\.(?:query|params|body)|request\.(?:args|GET))",
         "medium", "CWE-601", confidence="medium",
         remediation="Redirect only to a fixed allow-list of paths."),
    Rule("mass-assignment", "Model populated directly from request body",
         r"(?i)(?:\.create|\.update|new\s+\w+)\s*\(\s*(?:req\.body|request\.(?:data|json)|params)\s*\)",
         "medium", "CWE-915", confidence="low",
         remediation="Bind an explicit DTO / allow-list of fields."),
    Rule("no-auth-check", "Authentication explicitly disabled",
         r"(?i)(AllowAnonymous|permission_classes\s*=\s*\[\s*AllowAny|authentication\s*[:=]\s*(?:false|False)|"
         r"@PermitAll|auth\s*[:=]\s*false)", "medium", "CWE-306", confidence="low",
         remediation="Confirm the endpoint is meant to be public and rate-limited."),
    Rule("logging-secrets", "Secret value written to logs",
         r"(?i)(?:log|logger|console)\.\w+\([^)]*(?:password|secret|token|api[_-]?key|authorization)",
         "medium", "CWE-532", confidence="low",
         remediation="Redact credentials before logging."),
    Rule("wildcard-bind", "Service binds to all interfaces",
         r"""(?:["'](?:0\.0\.0\.0|\[::\])["']|\b0\.0\.0\.0:\d{2,5}|--host[= ]0\.0\.0\.0)""",
         "low", "CWE-1327", confidence="low", files=r"\.(py|js|ts|go|java|cs|yml|yaml)$",
         remediation="Bind to localhost unless the process is meant to be reachable from the network."),
    # -------------------------------------------------------- dockerfile/k8s
    Rule("docker-root", "Container runs as root (no USER)",
         r"\A(?:(?!^\s*USER\s).)*\Z", "medium", "CWE-250", files=r"(^|/)Dockerfile[\w.\-]*$",
         confidence="medium", category="infra",
         remediation="Add a non-root ``USER`` before the entrypoint."),
    Rule("docker-latest", "Base image pinned to a moving tag",
         r"^\s*FROM\s+\S+:latest|^\s*FROM\s+[^\s:@]+\s*$", "low", "CWE-1104",
         files=r"(^|/)Dockerfile[\w.\-]*$", category="infra",
         remediation="Pin an explicit version or digest so builds are reproducible."),
    Rule("docker-secret-arg", "Secret passed as build argument or env",
         r"(?i)^\s*(?:ARG|ENV)\s+\w*(?:PASSWORD|SECRET|TOKEN|KEY)\w*\s*=?\s*\S+",
         "high", "CWE-798", files=r"(^|/)Dockerfile[\w.\-]*$", category="infra",
         remediation="Use build secrets (``--mount=type=secret``) or inject at runtime."),
    Rule("docker-curl-bash", "Remote script piped into a shell",
         r"(?:curl|wget)[^\n|]*\|\s*(?:sudo\s+)?(?:ba)?sh", "medium", "CWE-494",
         files=r"(Dockerfile|\.sh$|\.ya?ml$)", category="infra",
         remediation="Download, verify a checksum, then execute."),
    Rule("k8s-privileged", "Privileged container / host namespace",
         r"(?i)privileged\s*:\s*true|hostNetwork\s*:\s*true|hostPID\s*:\s*true|allowPrivilegeEscalation\s*:\s*true",
         "high", "CWE-250", files=r"\.ya?ml$", category="infra",
         remediation="Drop privileges; set ``allowPrivilegeEscalation: false`` and a read-only root filesystem."),
    Rule("k8s-no-limits", "Kubernetes workload without resource limits",
         r"kind:\s*(?:Deployment|StatefulSet|DaemonSet)(?:(?!limits:).)*\Z",
         "low", "CWE-770", files=r"\.ya?ml$", category="infra", confidence="low",
         remediation="Set CPU/memory requests and limits so one workload cannot starve the node."),
    Rule("tf-public-ingress", "Security group open to the internet",
         r"cidr_blocks\s*=\s*\[\s*\"0\.0\.0\.0/0\"", "high", "CWE-284",
         files=r"\.tf$", category="infra",
         remediation="Restrict ingress to known CIDRs or put the service behind a load balancer."),
    Rule("tf-public-bucket", "Object storage exposed publicly",
         r"(?i)acl\s*=\s*\"public-read(?:-write)?\"|block_public_acls\s*=\s*false",
         "high", "CWE-732", files=r"\.tf$", category="infra",
         remediation="Keep buckets private and serve through signed URLs or a CDN."),
    Rule("tf-unencrypted", "Storage created without encryption",
         r"(?i)(encrypted\s*=\s*false|storage_encrypted\s*=\s*false)", "medium", "CWE-311",
         files=r"\.tf$", category="infra", remediation="Enable encryption at rest."),
    Rule("ci-pull-request-target", "Workflow runs untrusted code with write access",
         r"pull_request_target", "high", "CWE-829", files=r"\.github/workflows/",
         category="infra",
         remediation="Avoid ``pull_request_target`` with a checkout of the PR head, or drop permissions to read-only."),
    Rule("ci-script-injection", "Untrusted GitHub context interpolated into a shell step",
         r"\$\{\{\s*github\.event\.(?:issue|pull_request|comment|head_commit)\.[\w.]*(?:title|body|message|ref|login)",
         "high", "CWE-94", files=r"\.github/workflows/", category="infra",
         remediation="Pass the value through an ``env:`` variable and quote it instead of "
                     "interpolating into ``run:``."),
    Rule("ci-unpinned-action", "Third-party action pinned only by tag",
         r"uses:\s*(?!actions/|github/)[\w.\-]+/[\w.\-]+@v?\d", "low", "CWE-1104",
         files=r"\.github/workflows/", category="infra", confidence="low",
         remediation="Pin third-party actions to a commit SHA."),
    Rule("env-committed", "Environment file with real values committed",
         r"(?i)^\s*[A-Z][A-Z0-9_]*\s*=\s*\S+", "high", "CWE-540",
         files=r"(^|/)\.env(\.\w+)?$", not_files=r"(example|sample|template|dist)",
         category="config", once_per_file=True,
         remediation="Remove the file from version control, rotate the values and add it to .gitignore."),
]

_INFRA_WHOLE_FILE = {"docker-root", "k8s-no-limits"}


_PY_DOCSTRING = re.compile(r'("""|\'\'\')(?:.|\n)*?\1')


def _docstring_spans(rel: str, text: str) -> List[tuple]:
    """Documentation is full of illustrative bad code; it is not the code."""
    if not rel.endswith((".py", ".pyi")):
        return []
    return [(m.start(), m.end()) for m in _PY_DOCSTRING.finditer(text)]


def _inside(spans: Sequence[tuple], index: int) -> bool:
    return any(start <= index < end for start, end in spans)


_FIXTURE_PATH = re.compile(
    r"(?i)(^|/)(tests?|spec|specs|fixtures?|mocks?|examples?|samples?|testdata|__tests__)(/|$)"
)


def scan_patterns(rel: str, text: str, language: str, max_per_rule: int = 5) -> Iterator[Finding]:
    if not text:
        return
    lines = text.splitlines()
    fixture = bool(_FIXTURE_PATH.search(rel))
    doc_spans = _docstring_spans(rel, text)
    for rule in RULES:
        if not rule.applies(rel, language):
            continue
        try:
            pattern = rule.compiled()
        except re.error:
            continue
        if rule.id in _INFRA_WHOLE_FILE:
            if _whole_file_hit(rule, text):
                yield _finding(rule, rel, 1, lines[0].strip()[:200] if lines else "", fixture)
            continue
        count = 0
        limit = 1 if rule.once_per_file else max_per_rule
        for match in pattern.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            line = lines[line_no - 1].strip() if line_no - 1 < len(lines) else ""
            if _is_comment(line, language) or _inside(doc_spans, match.start()):
                continue
            # A rule table matching its own rules is the single loudest source
            # of noise when this is pointed at a scanner, a linter or anything
            # else that catalogues insecure code rather than containing it.
            if is_pattern_definition(line):
                continue
            if rule.id in _URI_RULES and is_xml_namespace(line, match.group(0)):
                continue
            if rule.id in _HASH_RULES and declares_non_security_use(line):
                continue
            yield _finding(rule, rel, line_no, line[:200], fixture)
            count += 1
            if count >= limit:
                break


# Rules about network addresses. An XML namespace URI is spelled like an
# address but is only ever a name, so these must not fire on one.
_URI_RULES = frozenset({"http-url"})

# Digest rules, which a caller can opt out of by declaring intent.
_HASH_RULES = frozenset({"weak-hash"})


def _whole_file_hit(rule: Rule, text: str) -> bool:
    if rule.id == "docker-root":
        return not re.search(r"^\s*USER\s+\w", text, re.M)
    if rule.id == "k8s-no-limits":
        return bool(re.search(r"kind:\s*(Deployment|StatefulSet|DaemonSet)", text)) and "limits:" not in text
    return False


_COMMENT_PREFIXES = {
    "Python": ("#",), "Ruby": ("#",), "Shell": ("#",), "YAML": ("#",),
    "JavaScript": ("//", "*"), "TypeScript": ("//", "*"), "Go": ("//",), "Java": ("//", "*"),
    "Kotlin": ("//", "*"), "C#": ("//", "*"), "Rust": ("//",), "PHP": ("//", "#", "*"),
}


def _is_comment(line: str, language: str) -> bool:
    prefixes = _COMMENT_PREFIXES.get(language)
    if not prefixes:
        return False
    return line.startswith(prefixes)


_SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


def _downgrade(severity: str) -> str:
    index = _SEVERITY_ORDER.index(severity) if severity in _SEVERITY_ORDER else 2
    return _SEVERITY_ORDER[min(index + 1, len(_SEVERITY_ORDER) - 1)]


def _finding(rule: Rule, rel: str, line: int, snippet: str, fixture: bool = False) -> Finding:
    # A committed .env under tests/ is a fixture, not a production leak — worth
    # reporting, not worth waking anyone up for.
    severity = _downgrade(rule.severity) if fixture and rule.category in ("config", "secret") \
        else rule.severity
    return Finding(
        id=slug("rule", rule.id, rel, str(line)),
        title=rule.title,
        severity=severity,
        category=rule.category,
        file=rel,
        line=line,
        snippet=snippet,
        cwe=rule.cwe,
        identifier=f"RG-{rule.id.upper()}",
        confidence="low" if fixture and rule.confidence != "high" else rule.confidence,
        remediation=rule.remediation,
        references=list(rule.references),
    )
