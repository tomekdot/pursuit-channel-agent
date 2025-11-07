import agent
import datetime as dt


def test_lunar_day_range():
    d = dt.datetime(2025, 11, 7, tzinfo=dt.timezone.utc)
    val = agent.lunar_day(d)
    assert isinstance(val, int)
    assert 0 <= val <= 29


def test_is_phase_date_returns_bool():
    d = dt.datetime(2025, 11, 7, tzinfo=dt.timezone.utc)
    val = agent._is_phase_date(d)
    assert isinstance(val, bool)


def test_sanitize_html_redacts_jwt_and_tokens():
    html = 'Authorization: Bearer abc.def.ghi\n<script>var token="s3cr3t"</script>?access_token=TOKEN123'
    out = agent.sanitize_html(html)
    assert "[REDACTED]" in out
    assert "abc.def.ghi" not in out
    assert "s3cr3t" not in out
    assert "TOKEN123" not in out
