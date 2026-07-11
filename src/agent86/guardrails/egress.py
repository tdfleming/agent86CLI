"""Egress guardrail (Tier 5, Pillar 4).

Scans model output for leaked secrets and PII before it leaves the harness. Modes: ``off``
(skip), ``warn`` (flag but pass through), ``redact`` (replace matches with markers).
"""

from __future__ import annotations

from dataclasses import dataclass

from agent86.guardrails.scanners import ScanReport, redact, scan_pii, scan_secrets


@dataclass
class EgressResult:
    report: ScanReport
    text: str  # possibly redacted


@dataclass
class EgressGuardrail:
    mode: str = "warn"  # off | warn | redact

    def inspect(self, text: str) -> EgressResult:
        if self.mode == "off" or not text:
            return EgressResult(ScanReport(), text)
        if self.mode == "redact":
            redacted, findings = redact(text)
            return EgressResult(ScanReport(findings=findings), redacted)
        findings = scan_secrets(text) + scan_pii(text)
        return EgressResult(ScanReport(findings=findings), text)


__all__ = ["EgressGuardrail", "EgressResult"]
