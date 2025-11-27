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


def test_get_moon_phases_2025():
    """Test moon phase calculation for November 2025."""
    phases = agent._get_moon_phase_dates_for_month(2025, 11)
    phase_days = [day for day, _ in phases]
    # November 2025: Full Moon 5th, Third Quarter 12th, New Moon 20th, First Quarter 28th
    assert 5 in phase_days, "Full Moon on Nov 5, 2025"
    assert 12 in phase_days, "Third Quarter on Nov 12, 2025"
    assert 20 in phase_days, "New Moon on Nov 20, 2025"
    assert 28 in phase_days, "First Quarter on Nov 28, 2025"
    # 27th should NOT be a phase date
    assert 27 not in phase_days, "Nov 27 should NOT be a phase date"


def test_is_phase_date_exact_dates_2025():
    """Test that exact moon phase dates for 2025 are correctly detected."""
    # Known phase dates from skyfield astronomical calculations (UTC)
    # Note: Some dates may differ by 1 day from local timezone calendars
    phase_dates = [
        (2025, 1, 13),   # Full Moon
        (2025, 3, 29),   # New Moon
        (2025, 11, 28),  # First Quarter (NOT 27!)
        (2025, 12, 4),   # Full Moon (23:14 UTC, some calendars show Dec 5 in CET)
    ]
    for year, month, day in phase_dates:
        d = dt.datetime(year, month, day, 12, 0, tzinfo=dt.timezone.utc)
        assert agent._is_phase_date(d) is True, f"Expected {year}-{month}-{day} to be a phase date"


def test_is_phase_date_non_phase_dates_2025():
    """Test that non-phase dates are correctly rejected."""
    non_phase_dates = [
        (2025, 11, 27),  # Day BEFORE First Quarter (NOT a phase date)
        (2025, 11, 29),  # Day AFTER First Quarter
        (2025, 1, 15),   # Random date
        (2025, 6, 1),    # Random date
    ]
    for year, month, day in non_phase_dates:
        d = dt.datetime(year, month, day, 12, 0, tzinfo=dt.timezone.utc)
        assert agent._is_phase_date(d) is False, f"Expected {year}-{month}-{day} to NOT be a phase date"


def test_moon_phases_future_years():
    """Test that moon phase calculation works for future years (2026-2050)."""
    # Verify that we get 4 phases per month (roughly) for future years
    for year in [2026, 2030, 2040, 2050]:
        for month in [1, 6, 12]:
            phases = agent._get_moon_phase_dates_for_month(year, month)
            assert len(phases) >= 3, f"Expected at least 3 phases in {year}-{month}"
            assert len(phases) <= 5, f"Expected at most 5 phases in {year}-{month}"


def test_sanitize_html_redacts_jwt_and_tokens():
    html = 'Authorization: Bearer abc.def.ghi\n<script>var token="s3cr3t"</script>?access_token=TOKEN123'
    out = agent.sanitize_html(html)
    assert "[REDACTED]" in out
    assert "abc.def.ghi" not in out
    assert "s3cr3t" not in out
    assert "TOKEN123" not in out
