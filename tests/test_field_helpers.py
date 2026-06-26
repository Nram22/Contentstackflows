import pytest

from field_helpers import (
    apply_transform,
    normalize_asset,
    normalize_reference,
    strip_system_fields,
)


def test_normalize_asset_from_object():
    assert normalize_asset({"uid": "blt123", "url": "https://x"}) == "blt123"


def test_normalize_asset_from_string():
    assert normalize_asset("blt123") == "blt123"


def test_normalize_asset_list():
    assert normalize_asset([{"uid": "a"}, {"uid": "b"}]) == ["a", "b"]


def test_normalize_asset_none():
    assert normalize_asset(None) is None


def test_normalize_reference_keeps_uid_and_content_type():
    src = [{"uid": "blt1", "_content_type_uid": "author", "title": "noise"}]
    assert normalize_reference(src) == [{"uid": "blt1", "_content_type_uid": "author"}]


def test_normalize_reference_single_dict():
    assert normalize_reference({"uid": "blt1", "_content_type_uid": "author"}) == {
        "uid": "blt1",
        "_content_type_uid": "author",
    }


def test_strip_system_fields_removes_known_keys():
    entry = {"title": "Hi", "uid": "blt1", "created_at": "t", "_version": 3}
    assert strip_system_fields(entry) == {"title": "Hi"}


def test_apply_transform_constant_ignores_source_value():
    assert apply_transform("constant", None, {"value": 42}, {}) == 42


def test_apply_transform_default_is_copy():
    assert apply_transform(None, "x", {}, {}) == "x"


def test_apply_transform_unknown_raises():
    with pytest.raises(KeyError):
        apply_transform("nope", "x", {}, {})
