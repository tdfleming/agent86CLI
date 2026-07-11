"""Deterministic detectors for the guardrail tier (Pillar 4).

Regex-based scanners for the book's "big three" input risks (prompt injection) plus
secret and PII leakage. These are intentionally simple and fast — a first line of defense,
not a replacement for a dedicated DLP system. Findings drive warn / block / redact behavior
in :mod:`agent86.guardrails.ingress` and :mod:`agent86.guardrails.egress`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Patterns
# --------------------------------------------------------------------------- #

_INJECTION = [
    (re.compile(r"\bignore\s+(all\s+|the\s+|any\s+)?(previous|prior|above)\s+"
                r"(instructions|prompts?|messages?)", re.I), "override-instructions"),
    (re.compile(r"\bdisregard\s+(the\s+|all\s+)?(above|previous|prior)", re.I),
     "override-instructions"),
    (re.compile(r"\byou\s+are\s+now\b", re.I), "role-reassignment"),
    (re.compile(r"\b(developer|dan|jailbreak)\s+mode\b", re.I), "jailbreak"),
    (re.compile(r"\b(reveal|print|show|repeat)\s+(your|the)\s+(system\s+)?"
                r"(prompt|instructions)", re.I), "prompt-extraction"),
    (re.compile(r"\bnew\s+(system\s+)?(instructions?|rules?)\s*:", re.I), "instruction-injection"),
    (re.compile(r"\bexfiltrat", re.I), "exfiltration"),
]

_SECRETS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "anthropic-key"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "openai-key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "aws-access-key"),
    (re.compile(r"\bghp_[A-Za-z0-9]{36}\b"), "github-token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"), "private-key"),
    (re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*"
                r"['\"]?[A-Za-z0-9_\-]{12,}"), "credential-assignment"),
]

_PII = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "email"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "ssn"),
    (re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), "phone"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "card-number"),
]


@dataclass
class Finding:
    category: str  # "injection" | "secret" | "pii"
    label: str
    snippet: str


@dataclass
class ScanReport:
    findings: list[Finding] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return bool(self.findings)

    def summary(self) -> str:
        return ", ".join(f"{f.category}:{f.label}" for f in self.findings)


def _snippet(text: str, start: int, end: int, pad: int = 12) -> str:
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    return text[s:e].replace("\n", " ").strip()


def _scan(text: str, patterns, category: str) -> list[Finding]:
    out: list[Finding] = []
    for rx, label in patterns:
        for m in rx.finditer(text):
            out.append(Finding(category=category, label=label, snippet=_snippet(text, *m.span())))
    return out


def scan_injection(text: str) -> list[Finding]:
    return _scan(text, _INJECTION, "injection")


def scan_secrets(text: str) -> list[Finding]:
    return _scan(text, _SECRETS, "secret")


def scan_pii(text: str) -> list[Finding]:
    return _scan(text, _PII, "pii")


def redact(text: str, *, secrets: bool = True, pii: bool = True) -> tuple[str, list[Finding]]:
    """Replace secret/PII matches with ``[REDACTED:label]`` markers."""
    findings: list[Finding] = []
    groups = []
    if secrets:
        groups.extend(_SECRETS_WITH_CAT)
    if pii:
        groups.extend(_PII_WITH_CAT)
    result = text
    for rx, label, category in groups:
        def _repl(m: re.Match, _label=label, _cat=category) -> str:
            findings.append(Finding(category=_cat, label=_label, snippet="[redacted]"))
            return f"[REDACTED:{_label}]"

        result = rx.sub(_repl, result)
    return result, findings


_SECRETS_WITH_CAT = [(rx, label, "secret") for rx, label in _SECRETS]
_PII_WITH_CAT = [(rx, label, "pii") for rx, label in _PII]


__all__ = [
    "Finding",
    "ScanReport",
    "scan_injection",
    "scan_secrets",
    "scan_pii",
    "redact",
]
