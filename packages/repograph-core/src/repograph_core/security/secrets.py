"""Hardcoded secret detection.

Pattern matches first, entropy second, and a deliberately aggressive
false-positive filter: a scanner nobody trusts gets ignored.
"""

from __future__ import annotations

import re
from typing import Iterator, List, Tuple

from ..model import Finding
from ..util import shannon_entropy, slug

# (rule id, title, regex, severity, confidence)
RULES: List[Tuple[str, str, str, str, str]] = [
    ("aws-access-key", "AWS access key id", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "critical", "high"),
    ("aws-secret", "AWS secret access key",
     r"(?i)aws(.{0,20})?(secret|private)[^\n]{0,20}['\"][0-9a-zA-Z/+]{40}['\"]", "critical", "high"),
    ("github-token", "GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", "critical", "high"),
    ("gitlab-token", "GitLab token", r"\bglpat-[A-Za-z0-9_\-]{20,}\b", "critical", "high"),
    ("slack-token", "Slack token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "critical", "high"),
    ("slack-webhook", "Slack webhook URL", r"https://hooks\.slack\.com/services/[A-Za-z0-9/+]{20,}", "high", "high"),
    ("stripe-key", "Stripe secret key", r"\b(?:sk|rk)_(?:live|test)_[0-9a-zA-Z]{16,}\b", "critical", "high"),
    ("google-api-key", "Google API key", r"\bAIza[0-9A-Za-z_\-]{35}\b", "high", "high"),
    ("openai-key", "OpenAI API key", r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b", "critical", "high"),
    ("anthropic-key", "Anthropic API key", r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b", "critical", "high"),
    ("private-key", "Private key material",
     r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY", "critical", "high"),
    ("jwt", "Hardcoded JWT",
     r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b", "medium", "medium"),
    ("npm-token", "npm token", r"\bnpm_[A-Za-z0-9]{36}\b", "high", "high"),
    ("twilio", "Twilio account SID", r"\bAC[0-9a-fA-F]{32}\b", "high", "medium"),
    ("sendgrid", "SendGrid API key", r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}\b", "critical", "high"),
    ("azure-secret", "Azure storage key",
     r"(?i)(?:AccountKey|SharedAccessSignature)=[A-Za-z0-9+/=]{40,}", "critical", "high"),
    ("conn-string", "Database connection string with password",
     r"(?i)(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|mssql)://"
     r"[^\s:/@'\"]+:[^\s:/@'\"]{3,}@[\w.\-]+", "high", "high"),
    # The name may carry a prefix or suffix (DB_PASSWORD, stripeApiKey), so this
    # deliberately does not anchor on a word boundary before the keyword.
    ("password-assign", "Hardcoded password / secret assignment",
     r"(?i)[\w.\-]{0,32}(?:password|passwd|pwd|secret|api[_\-]?key|apikey|access[_\-]?token|"
     r"auth[_\-]?token|client[_\-]?secret)[\w.\-]{0,16}\s*[:=]\s*['\"][^'\"\n]{6,}['\"]",
     "high", "medium"),
    ("basic-auth", "Hardcoded HTTP basic auth header",
     r"(?i)authorization\s*[:=]\s*['\"]?basic\s+[A-Za-z0-9+/=]{12,}", "high", "high"),
    ("bearer", "Hardcoded bearer token",
     r"(?i)authorization\s*[:=]\s*['\"]?bearer\s+[A-Za-z0-9_\-.]{20,}", "high", "medium"),
]

_COMPILED = [(rid, title, re.compile(pattern), sev, conf) for rid, title, pattern, sev, conf in RULES]

# Values that look like secrets but are not.
_PLACEHOLDER = re.compile(
    r"(?i)(example|sample|placeholder|dummy|test|fake|changeme|change_me|your[_\-]?|my[_\-]?|"
    r"xxx+|yyy+|zzz+|aaa+|1234|abcd|foo|bar|baz|todo|redacted|removed|none|null|empty|"
    r"\$\{|\{\{|<[a-z_]+>|%s|%\(|\.\.\.|process\.env|os\.environ|getenv|secrets\.|vault:)"
)
# For structurally unmistakable tokens (an AKIA key, a ghp_ token) only an
# explicit "this is not real" marker should suppress the finding.
_STRICT_PLACEHOLDER = re.compile(
    r"(?i)(example|sample|placeholder|dummy|fake|changeme|change_me|redacted|removed|"
    r"your[_\-]?|xxx+|\$\{|\{\{|<[a-z_]+>)"
)

_HIGH_ENTROPY_ASSIGN = re.compile(
    r"""(?i)\b([\w.\-]{0,40}(?:key|token|secret|password|pwd|credential|salt|hash|signature)[\w.\-]{0,20})"""
    r"""\s*[:=]\s*["']([A-Za-z0-9+/=_\-]{24,})["']"""
)
_SKIP_FILES = re.compile(
    r"(?i)(^|/)(test|tests|spec|fixtures?|mocks?|examples?|samples?|docs?|vendor|__snapshots__)(/|$)"
    r"|\.(md|rst|txt|lock|snap|svg|map|csv)$|(^|/)(package-lock\.json|yarn\.lock|poetry\.lock)$"
)
_ENV_EXAMPLE = re.compile(r"(?i)\.env\.(example|sample|template|dist)$|(^|/)env\.example$")


_QUOTED = re.compile(r"""['"]([^'"\n]{4,})['"]""")


def _secret_value(matched: str) -> str:
    """The credential itself, not the assignment around it."""
    quoted = _QUOTED.findall(matched)
    return quoted[-1] if quoted else matched


def _looks_placeholder(text: str, strict: bool = False, is_value: bool = False) -> bool:
    """``strict`` narrows the vocabulary for structurally unmistakable tokens;
    ``is_value`` enables checks that only make sense on the secret itself."""
    pattern = _STRICT_PLACEHOLDER if strict else _PLACEHOLDER
    if pattern.search(text):
        return True
    if is_value and not strict:
        # "SECRET_KEY = 'development key'" is prose, not a credential.
        if " " in text.strip().strip("\"'"):
            return True
    return len(set(text)) <= 4


_PY_DOCSTRING = re.compile(r'("""|\'\'\')(?:.|\n)*?\1')


def _docstring_spans(rel: str, text: str) -> List[tuple]:
    if not rel.endswith((".py", ".pyi")):
        return []
    return [(m.start(), m.end()) for m in _PY_DOCSTRING.finditer(text)]


def scan_secrets(rel: str, text: str, app: str = "") -> Iterator[Finding]:
    if not text or _ENV_EXAMPLE.search(rel):
        return
    is_low_signal = bool(_SKIP_FILES.search(rel))
    lines = text.splitlines()
    doc_spans = _docstring_spans(rel, text)
    seen: set = set()

    for rid, title, pattern, severity, confidence in _COMPILED:
        for match in pattern.finditer(text):
            value = _secret_value(match.group(0))
            line_no = text.count("\n", 0, match.start()) + 1
            if line_no - 1 >= len(lines):
                continue
            line = lines[line_no - 1]
            # High-confidence rules judge the matched value; the loose
            # "password = ..." rule also weighs the surrounding line.
            if _looks_placeholder(value, strict=confidence == "high", is_value=True) \
                    and rid != "private-key":
                continue
            if confidence != "high" and _looks_placeholder(line):
                continue
            key = (rid, line_no)
            if key in seen or any(start <= match.start() < end for start, end in doc_spans):
                continue
            seen.add(key)
            sev = severity
            conf = confidence
            if is_low_signal:
                sev = _downgrade(severity)
                conf = "low"
            yield Finding(
                id=slug("secret", rid, rel, str(line_no)),
                title=title,
                severity=sev,
                category="secret",
                file=rel,
                line=line_no,
                snippet=_redact(line.strip()[:200]),
                cwe="CWE-798",
                identifier=f"RG-SECRET-{rid.upper()}",
                confidence=conf,
                remediation="Move the value to a secret manager or environment variable, then rotate it — "
                            "anything committed to git must be treated as compromised.",
            )

    for match in _HIGH_ENTROPY_ASSIGN.finditer(text):
        name, value = match.group(1), match.group(2)
        if _looks_placeholder(value, is_value=True) or shannon_entropy(value) < 4.0:
            continue
        line_no = text.count("\n", 0, match.start()) + 1
        if ("entropy", line_no) in seen or any(k[1] == line_no for k in seen):
            continue
        seen.add(("entropy", line_no))
        yield Finding(
            id=slug("secret", "entropy", rel, str(line_no)),
            title=f"High-entropy value assigned to '{name}'",
            severity="medium" if not is_low_signal else "low",
            category="secret",
            file=rel,
            line=line_no,
            snippet=_redact(lines[line_no - 1].strip()[:200] if line_no - 1 < len(lines) else ""),
            cwe="CWE-798",
            identifier="RG-SECRET-ENTROPY",
            confidence="low",
            remediation="Confirm whether this is a live credential; if so rotate it and load it from configuration.",
        )


def _downgrade(severity: str) -> str:
    order = ["critical", "high", "medium", "low", "info"]
    idx = order.index(severity) if severity in order else 2
    return order[min(idx + 1, len(order) - 1)]


def _redact(line: str) -> str:
    """Never print a full credential into a report that gets shared."""
    def repl(match: re.Match) -> str:
        value = match.group(0)
        return value[:4] + "…" + "*" * 6 if len(value) > 10 else "***"

    return re.sub(r"[A-Za-z0-9+/=_\-]{16,}", repl, line)
