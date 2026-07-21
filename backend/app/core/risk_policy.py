"""
Deterministic risk and permission policy for Mama AI.

Every command should be assessed before it reaches a tool executor.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

from app.core.task import RiskLevel, utc_now


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class RiskRule:
    category: str
    pattern: str
    risk_level: RiskLevel
    decision: PermissionDecision
    reason: str

    def matches(self, command: str) -> bool:
        return re.search(
            self.pattern,
            command,
            flags=re.IGNORECASE,
        ) is not None


@dataclass(slots=True)
class RiskAssessment:
    command: str
    risk_level: RiskLevel
    decision: PermissionDecision
    category: str
    reasons: list[str] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)
    assessment_id: str = field(
        default_factory=lambda: uuid4().hex
    )
    created_at: str = field(default_factory=utc_now)

    @property
    def requires_approval(self) -> bool:
        return self.decision == PermissionDecision.REQUIRE_APPROVAL

    @property
    def allowed(self) -> bool:
        return self.decision != PermissionDecision.DENY

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["risk_level"] = self.risk_level.value
        data["decision"] = self.decision.value
        data["requires_approval"] = self.requires_approval
        data["allowed"] = self.allowed
        return data


class RiskPolicy:
    """
    Classify Mama AI commands using ordered safety rules.

    Rules are ordered from strongest to weakest:

    denied → critical → high → medium → low
    """

    def __init__(self) -> None:
        self._rules = self._build_rules()

    @staticmethod
    def _build_rules() -> tuple[RiskRule, ...]:
        return (
            # Completely denied operations
            RiskRule(
                category="credential_theft",
                pattern=(
                    r"\b(?:steal|extract|dump|collect)\b"
                    r".*\b(?:passwords?|credentials?|tokens?|cookies?)\b"
                ),
                risk_level=RiskLevel.CRITICAL,
                decision=PermissionDecision.DENY,
                reason=(
                    "Requests to steal or extract private credentials "
                    "are prohibited."
                ),
            ),
            RiskRule(
                category="security_bypass",
                pattern=(
                    r"\b(?:disable|bypass|evade|remove)\b"
                    r".*\b(?:security|antivirus|authentication|"
                    r"approval|permission)\b"
                ),
                risk_level=RiskLevel.CRITICAL,
                decision=PermissionDecision.DENY,
                reason=(
                    "Mama AI cannot bypass authentication, approval, "
                    "or device-security controls."
                ),
            ),
            RiskRule(
                category="malicious_software",
                pattern=(
                    r"\b(?:keylogger|ransomware|credential\s*theft|"
                    r"password\s*stealer)\b"
                ),
                risk_level=RiskLevel.CRITICAL,
                decision=PermissionDecision.DENY,
                reason="Malicious software operations are prohibited.",
            ),

            # Critical operations requiring explicit approval
            RiskRule(
                category="financial_transaction",
                pattern=(
                    r"\b(?:pay|send|transfer)\b"
                    r".*\b(?:money|payment|funds?|rupees?|inr|"
                    r"dollars?|usd)\b"
                ),
                risk_level=RiskLevel.CRITICAL,
                decision=PermissionDecision.REQUIRE_APPROVAL,
                reason=(
                    "Financial transactions require explicit user "
                    "approval before execution."
                ),
            ),
            RiskRule(
                category="upi_transaction",
                pattern=(
                    r"(?:\bupi\b.*\b(?:pay|send|transfer)\b|"
                    r"\b(?:pay|send|transfer)\b.*\bupi\b)"
                ),
                risk_level=RiskLevel.CRITICAL,
                decision=PermissionDecision.REQUIRE_APPROVAL,
                reason=(
                    "UPI transactions require explicit user approval."
                ),
            ),
            RiskRule(
                category="purchase",
                pattern=(
                    r"\b(?:buy|purchase|place\s+(?:the\s+)?order|"
                    r"confirm\s+(?:the\s+)?order)\b"
                ),
                risk_level=RiskLevel.CRITICAL,
                decision=PermissionDecision.REQUIRE_APPROVAL,
                reason=(
                    "Purchases and orders require explicit approval."
                ),
            ),
            RiskRule(
                category="system_power",
                pattern=(
                    r"\b(?:shutdown|shut\s+down|restart|reboot|"
                    r"factory\s+reset)\b"
                ),
                risk_level=RiskLevel.CRITICAL,
                decision=PermissionDecision.REQUIRE_APPROVAL,
                reason=(
                    "Power and factory-reset operations require "
                    "explicit approval."
                ),
            ),
            RiskRule(
                category="disk_destruction",
                pattern=(
                    r"\b(?:format|wipe|erase)\b"
                    r".*\b(?:drive|disk|partition)\b"
                ),
                risk_level=RiskLevel.CRITICAL,
                decision=PermissionDecision.REQUIRE_APPROVAL,
                reason=(
                    "Disk modification can cause permanent data loss."
                ),
            ),
            RiskRule(
                category="external_communication",
                pattern=(
                    r"\b(?:send|post|publish)\b"
                    r".*\b(?:email|message|sms|whatsapp|telegram|"
                    r"tweet|social\s+media|public\s+post)\b"
                ),
                risk_level=RiskLevel.CRITICAL,
                decision=PermissionDecision.REQUIRE_APPROVAL,
                reason=(
                    "External communications require approval before "
                    "they are sent."
                ),
            ),

            # High-risk operations requiring approval
            RiskRule(
                category="file_deletion",
                pattern=(
                    r"\b(?:delete|remove|erase)\b"
                    r".*\b(?:file|folder|directory|document|photo|"
                    r"video)\b"
                ),
                risk_level=RiskLevel.HIGH,
                decision=PermissionDecision.REQUIRE_APPROVAL,
                reason=(
                    "Deleting files or folders requires approval."
                ),
            ),
            RiskRule(
                category="terminal_execution",
                pattern=(
                    r"\b(?:run|execute|open|launch)\b"
                    r".*\b(?:cmd|command\s+prompt|powershell|"
                    r"terminal|shell)\b"
                ),
                risk_level=RiskLevel.HIGH,
                decision=PermissionDecision.REQUIRE_APPROVAL,
                reason=(
                    "Terminal and shell access requires approval."
                ),
            ),
            RiskRule(
                category="software_change",
                pattern=(
                    r"\b(?:install|uninstall|remove)\b"
                    r".*\b(?:application|app|program|software|"
                    r"package|driver)\b"
                ),
                risk_level=RiskLevel.HIGH,
                decision=PermissionDecision.REQUIRE_APPROVAL,
                reason=(
                    "Installing or removing software requires approval."
                ),
            ),
            RiskRule(
                category="system_configuration",
                pattern=(
                    r"\b(?:change|modify|edit|disable|enable)\b"
                    r".*\b(?:registry|firewall|system\s+settings|"
                    r"network\s+settings)\b"
                ),
                risk_level=RiskLevel.HIGH,
                decision=PermissionDecision.REQUIRE_APPROVAL,
                reason=(
                    "System configuration changes require approval."
                ),
            ),
            RiskRule(
                category="recording",
                pattern=(
                    r"\b(?:record|capture|activate|turn\s+on)\b"
                    r".*\b(?:camera|microphone|webcam|audio)\b"
                ),
                risk_level=RiskLevel.HIGH,
                decision=PermissionDecision.REQUIRE_APPROVAL,
                reason=(
                    "Camera or microphone recording requires approval."
                ),
            ),

            # Medium-risk operations
            RiskRule(
                category="file_modification",
                pattern=(
                    r"\b(?:create|write|edit|modify|rename|move|copy)\b"
                    r".*\b(?:file|folder|directory|document)\b"
                ),
                risk_level=RiskLevel.MEDIUM,
                decision=PermissionDecision.ALLOW,
                reason=(
                    "The command modifies local files and must be logged."
                ),
            ),
            RiskRule(
                category="file_transfer",
                pattern=(
                    r"\b(?:upload|download)\b"
                    r".*\b(?:file|document|photo|video|archive)\b"
                ),
                risk_level=RiskLevel.MEDIUM,
                decision=PermissionDecision.ALLOW,
                reason=(
                    "The command transfers data and must be logged."
                ),
            ),
        )

    def assess(self, command: str) -> RiskAssessment:
        if not isinstance(command, str):
            raise TypeError("Risk assessment command must be text.")

        normalized_command = " ".join(command.strip().split())

        if not normalized_command:
            raise ValueError(
                "Risk assessment command cannot be empty."
            )

        for rule in self._rules:
            if rule.matches(normalized_command):
                return RiskAssessment(
                    command=normalized_command,
                    risk_level=rule.risk_level,
                    decision=rule.decision,
                    category=rule.category,
                    reasons=[rule.reason],
                    matched_rules=[rule.pattern],
                )

        return RiskAssessment(
            command=normalized_command,
            risk_level=RiskLevel.LOW,
            decision=PermissionDecision.ALLOW,
            category="normal_operation",
            reasons=[
                "No sensitive or destructive operation was detected."
            ],
            matched_rules=[],
        )


risk_policy = RiskPolicy()


__all__ = [
    "PermissionDecision",
    "RiskAssessment",
    "RiskPolicy",
    "RiskRule",
    "risk_policy",
]