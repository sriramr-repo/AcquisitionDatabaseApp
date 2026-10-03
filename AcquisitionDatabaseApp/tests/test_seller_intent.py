from src.seller_intent import IntentEvidence, propose_status


def evidence(source: str, status: str, excerpt: str = "Owner explicitly discussed a possible transaction.", polarity: str = "SUPPORTS") -> IntentEvidence:
    return IntentEvidence(source, status, polarity, excerpt)


def test_sec_context_and_no_response_cannot_create_intent():
    proposal = propose_status([
        evidence("SEC_IA_BULK", "SIGNAL_IDENTIFIED", "The firm reports only one advisory employee."),
        evidence("NO_RESPONSE", "NOT_INTERESTED", "No response was received after an email."),
    ])
    assert proposal.status == "UNKNOWN"


def test_highest_supported_stage_is_proposed_not_accepted():
    proposal = propose_status([
        evidence("NAMED_REFERRAL", "SIGNAL_IDENTIFIED", "A named referral said transition planning may be timely."),
        evidence("MEETING", "ENGAGED_IN_DISCUSSION", "The owner discussed a transaction and agreed to a next meeting."),
    ])
    assert proposal.status == "ENGAGED_IN_DISCUSSION"
    assert "user confirmation" in proposal.reason


def test_current_positive_and_negative_evidence_conflicts():
    proposal = propose_status([
        evidence("OWNER_COMMUNICATION", "DIRECTLY_EXPRESSED"),
        evidence("AUTHORIZED_REPRESENTATIVE", "NOT_INTERESTED", "The authorized representative said the owner is not interested."),
    ])
    assert proposal.status == "CONFLICTING"


def test_stale_is_never_algorithmically_created():
    proposal = propose_status([IntentEvidence("OWNER_COMMUNICATION", "DIRECTLY_EXPRESSED", "SUPPORTS", "Old owner conversation that is no longer current.", current=False)])
    assert proposal.status == "UNKNOWN"
