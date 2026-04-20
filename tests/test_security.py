import agent


def test_is_safe_url_accepts_expected_https_domains():
    assert agent.is_safe_url("https://www.maniaplanet.com/login") is True
    assert agent.is_safe_url("https://support.maniaplanet.com/path") is True


def test_is_safe_url_rejects_http_and_lookalikes():
    assert agent.is_safe_url("http://www.maniaplanet.com/login") is False
    assert agent.is_safe_url("https://www.maniaplanet.com.site/login") is False
    assert agent.is_safe_url("https://maniaplanet.com/log-in") is False


def test_require_safe_url_rejects_invalid_urls():
    for value in [
        "http://www.maniaplanet.com/login",
        "https://www.maniaplanet.com.site/login",
        "https://maniaplanet.com/log-in",
        "https://example.com/login",
    ]:
        try:
            agent._require_safe_url(value, "TEST_URL")
        except RuntimeError:
            continue
        raise AssertionError(f"Expected RuntimeError for {value}")
