"""Evidence-only seller-intent proposal rules.

The algorithm is not a source and never confirms a status. It proposes a
review state from current evidence; an authenticated user must accept it.
"""
from __future__ import annotations

from dataclasses import dataclass

POSITIVE = {"SIGNAL_IDENTIFIED", "DIRECTLY_EXPRESSED", "ENGAGED_IN_DISCUSSION", "FORMAL_PROCESS"}
PERMITTED_SOURCES = {"OWNER_COMMUNICATION", "AUTHORIZED_REPRESENTATIVE", "OUTREACH_RESPONSE", "CALL", "MEETING", "AUTHORIZED_INTERMEDIARY", "NAMED_REFERRAL", "PUBLIC_FORMAL_PROCESS"}
RANK = {"SIGNAL_IDENTIFIED": 1, "DIRECTLY_EXPRESSED": 2, "ENGAGED_IN_DISCUSSION": 3, "FORMAL_PROCESS": 4}


@dataclass(frozen=True)
class IntentEvidence:
    source_type: str
    proposed_status: str
    claim_polarity: str
    evidence_excerpt: str
    current: bool = True


@dataclass(frozen=True)
class IntentProposal:
    status: str
    reason: str
    evidence_count: int


def propose_status(evidence: list[IntentEvidence]) -> IntentProposal:
    usable = [item for item in evidence if item.current and item.source_type in PERMITTED_SOURCES and len(item.evidence_excerpt.strip()) >= 10]
    positive = [item for item in usable if item.proposed_status in POSITIVE and item.claim_polarity != "REFUTES"]
    negative = [item for item in usable if item.proposed_status == "NOT_INTERESTED" and item.claim_polarity != "REFUTES"]
    if positive and negative:
        return IntentProposal("CONFLICTING", "Current permitted evidence supports both interest and non-interest.", len(usable))
    if negative:
        return IntentProposal("NOT_INTERESTED", "Current direct or authorized evidence states the firm is not interested.", len(negative))
    if positive:
        status = max((item.proposed_status for item in positive), key=RANK.__getitem__)
        return IntentProposal(status, "Highest supported stage in current permitted evidence; user confirmation is still required.", len(positive))
    return IntentProposal("UNKNOWN", "No current permitted evidence establishes seller intent.", 0)
