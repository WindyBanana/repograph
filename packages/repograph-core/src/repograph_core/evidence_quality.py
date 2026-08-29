"""Telling a mention apart from a use.

Signature and rule matching is substring matching, so it cannot by itself
distinguish three very different things that all contain the word "Stripe":

    payment = stripe.Charge.create(...)          # the code uses Stripe
    ("stripe", "Stripe", r"stripe|sk_live_")     # the code *detects* Stripe
    - **Payments** Stripe, Adyen, Braintree      # the docs *mention* Stripe

Only the first is evidence of a dependency. The other two are why a scanner
pointed at another scanner, a linter, a service catalogue or a vendor
comparison page reports dozens of systems nobody talks to.

Nothing here is repograph-specific: any repository that catalogues names it
does not call hits the same problem, and repograph is simply the first one
this was noticed on.
"""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple

# File kinds whose content is written to be read by a person, not executed.
# A name here can corroborate a system found in code, never establish one.
PROSE_KINDS = frozenset({"docs", "data"})

# Constructs that appear in regular expressions and essentially never in the
# ordinary string literals of application code. Two or more on one line means
# the line is describing a pattern rather than doing something.
_REGEX_SIGNALS: Tuple[re.Pattern, ...] = (
    re.compile(r"""\br['"]"""),              # r"..." raw-string prefix
    re.compile(r"\(\?[:imsxaLu#=!<]"),       # (?: (?i) (?= (?<  ...
    # A class escape is followed by a quantifier or a boundary, never by more
    # letters: \s* and \b| are regex, the \dev in a Windows path is not.
    re.compile(r"\\[bBdDsSwWAZ](?![A-Za-z])"),
    re.compile(r"\[\^"),                     # [^...] negated class
    re.compile(r"\.[*+]\??[)|\"']"),         # .* .+ .*? at a boundary
    re.compile(r"\\\."),                     # \. an escaped dot
    re.compile(r"\{\d+,\d*\}"),              # {2,} {1,3} repetition
    # Alternation is written tight — mongodb://|pymongo — while a bitwise or in
    # ordinary code is nearly always spaced: a | b.
    re.compile(r"\S\|\S"),
)

_MIN_SIGNALS = 2

# A file whose matches mostly land on pattern definitions is a catalogue, and
# then even its plainest entries (r"klarna") are definitions too. Needs a few
# matches before the proportion means anything.
_CATALOGUE_MIN_LINES = 4
_CATALOGUE_RATIO = 1 / 3


_RAW_STRING = re.compile(r"""\br(['"])(.*?)(?<!\\)\1""")


def spans_whole_raw_string(line: str, matched: str) -> bool:
    """True when the match *is* an entire raw-string literal on this line.

    A table of signatures holds entries as bare as r"clickhouse", which carries
    no regex syntax to recognise it by. What gives it away is that the whole
    literal is the name: real code that happens to hold a name inside a raw
    string — r"C:\\redis\\dump" — matches only part of it.
    """
    if not line or not matched:
        return False
    return any(body == matched for _quote, body in
               (m.groups() for m in _RAW_STRING.finditer(line)))


# Leading markers for a line that is a comment rather than code. A name in a
# comment is prose that happens to live in a source file.
_COMMENT_LINE = re.compile(r"^\s*(#|//|/\*|\*|<!--|--\s|;)")


def is_comment_line(line: str) -> bool:
    return bool(_COMMENT_LINE.match(line or ""))


def is_pattern_catalogue(matched_lines: Sequence[str]) -> bool:
    """True when a file defines detection patterns rather than using services.

    Judged per file rather than per line: a signature table holds entries as
    plain as r"klarna", which carries no regex syntax of its own and is only
    recognisable from the company it keeps.
    """
    lines = [line for line in matched_lines if line]
    if len(lines) < _CATALOGUE_MIN_LINES:
        return False
    defined = sum(1 for line in lines if is_pattern_definition(line))
    return defined / len(lines) >= _CATALOGUE_RATIO


def is_pattern_definition(line: str) -> bool:
    """True when this line defines a regular expression rather than using one.

    Deliberately needs two independent signals: a lone raw-string prefix is
    common in ordinary code (Windows paths, LaTeX, f-string siblings), so on
    its own it must not silence a real finding.
    """
    if not line:
        return False
    hits = 0
    for signal in _REGEX_SIGNALS:
        if signal.search(line):
            hits += 1
            if hits >= _MIN_SIGNALS:
                return True
    return False


# A URI used to name an XML vocabulary is an identifier, not an address. No
# request is ever made to it — http://www.w3.org/2000/svg is a name, and
# rewriting it to https breaks every document that declares it.
_XML_NAMESPACE_CONTEXT = re.compile(
    r"""xmlns(?::[\w.-]+)?\s*=|targetNamespace\s*=|schemaLocation\s*=|"""
    r"""xsi:\w+\s*=|namespace\s*[:=]|nsmap|register_namespace""",
    re.I,
)

# The vocabularies themselves, for the case where the URI sits alone in a
# lookup table with the binding on another line ({"bpmn": "http://..."}).
_XML_NAMESPACE_HOSTS = re.compile(
    r"https?://(?:www\.)?(?:"
    r"w3\.org|omg\.org|purl\.org|opengroup\.org|oasis-open\.org|xmlsoap\.org|"
    r"schemas\.(?:microsoft|openxmlformats|android)\.com|openxmlformats\.org|"
    r"docbook\.org|dublincore\.org|iptc\.org|ns\.adobe\.com|apache\.org"
    # The caller often hands over a match clipped at the host, so the path
    # that usually follows cannot be required.
    r")(?:/|\b)",
    re.I,
)


def is_xml_namespace(line: str, matched: str = "") -> bool:
    """True when the URI here names an XML vocabulary rather than an endpoint.

    Both the match and its whole line are considered: a match is typically
    clipped at the host, while the binding that gives it away — xmlns=,
    schemaLocation=, a namespace map — sits further along the line.
    """
    for text in (matched, line):
        if text and _XML_NAMESPACE_HOSTS.search(text):
            return True
    return bool(line and _XML_NAMESPACE_CONTEXT.search(line))


# An import inside `try: ... except ImportError:` is optional by construction.
# Reporting it as an undeclared dependency asks the author to declare the very
# thing they wrote a fallback for.
_IMPORT_LINE = re.compile(r"^\s*(?:from|import)\s+([\w.]+)")
_TRY_LINE = re.compile(r"^(\s*)try\s*:")
_EXCEPT_IMPORT = re.compile(r"^\s*except\s+\(?[\w. ,]*(?:ImportError|ModuleNotFoundError)")


def optional_import_names(text: str) -> List[str]:
    """Modules imported inside a try/except ImportError block.

    Scanned line by line rather than with one regex over the whole file: a
    pattern spanning an arbitrary block body backtracks catastrophically on a
    large source file, which is a scanner that never finishes.
    """
    names: List[str] = []
    if "try" not in text or "Error" not in text:
        return names
    lines = text.splitlines()
    index = 0
    total = len(lines)
    while index < total:
        opened = _TRY_LINE.match(lines[index])
        if not opened:
            index += 1
            continue
        indent = len(opened.group(1))
        body: List[str] = []
        cursor = index + 1
        while cursor < total:
            line = lines[cursor]
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                break
            body.append(line)
            cursor += 1
        if cursor < total and _EXCEPT_IMPORT.match(lines[cursor]):
            for line in body:
                found = _IMPORT_LINE.match(line)
                if found:
                    names.append(found.group(1).split(".")[0])
        index = cursor if cursor > index else index + 1
    return names


# hashlib grew usedforsecurity= precisely so a digest used as an identifier can
# say so. Honouring it also keeps the finding meaningful: a codebase that marks
# its non-security digests is left with only the ones that matter.
_NON_SECURITY_HASH = re.compile(r"usedforsecurity\s*=\s*False")


def declares_non_security_use(line: str) -> bool:
    return bool(line and _NON_SECURITY_HASH.search(line))
