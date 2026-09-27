from agent.evidence import quote_supports


def test_quote_supports_ignores_case_and_spacing():
    assert quote_supports(
        "the retry service needs a circuit breaker",
        "The retry service needs a  circuit breaker before launch.",
    ) is True


def test_quote_supports_rejects_prefix_matches():
    assert quote_supports("Dan", "Danielle owns the migration.") is False


def test_quote_supports_rejects_blank_or_missing_quotes():
    assert quote_supports(None, "anything") is False
    assert quote_supports("  ", "anything") is False
    assert quote_supports("not present", "the notes say something else") is False
