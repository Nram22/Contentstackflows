import pytest

from validate_entry import assert_valid, validate_payload

MAPPING = {"required_target_fields": ["title", "url"], "url_field": "url"}


def test_valid_payload_has_no_errors():
    assert validate_payload({"title": "Hi", "url": "/x"}, MAPPING) == []


def test_missing_required_field_reported():
    errors = validate_payload({"title": "Hi"}, MAPPING)
    assert any("url" in e for e in errors)


def test_empty_required_field_reported():
    errors = validate_payload({"title": "", "url": "/x"}, MAPPING)
    assert any("title" in e for e in errors)


def test_whitespace_url_rejected():
    errors = validate_payload({"title": "Hi", "url": "   "}, MAPPING)
    assert any("URL" in e for e in errors)


def test_assert_valid_raises_on_error():
    with pytest.raises(ValueError):
        assert_valid({"title": "Hi"}, MAPPING)


def test_assert_valid_passes_clean_payload():
    assert_valid({"title": "Hi", "url": "/x"}, MAPPING)  # should not raise
