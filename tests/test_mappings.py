import json

import pytest

from mappings import apply_mapping, load_mapping

BASIC = {
    "source_content_type": "web_page",
    "target_content_type": "web_page_v2",
    "url_field": "url",
    "required_target_fields": ["title", "url"],
    "fields": [
        {"source": "title", "target": "headline"},
        {"source": "url", "target": "url"},
        {"source": "hero", "target": "hero", "transform": "asset"},
        {"target": "migrated_from", "transform": "constant", "value": "web_page"},
    ],
}


def test_apply_mapping_renames_and_transforms():
    src = {"title": "Hello", "url": "/x", "hero": {"uid": "blt9"}, "uid": "blt1"}
    out = apply_mapping(src, BASIC)
    assert out["headline"] == "Hello"
    assert out["url"] == "/x"
    assert out["hero"] == "blt9"          # asset object reduced to UID
    assert out["migrated_from"] == "web_page"
    assert "uid" not in out                # not copied (copy_unmapped is false)
    assert "title" not in out              # renamed to headline, not kept


def test_copy_unmapped_brings_extra_fields_but_not_system():
    mapping = dict(BASIC, copy_unmapped=True)
    src = {"title": "Hello", "url": "/x", "extra": 1, "uid": "blt1", "_version": 2}
    out = apply_mapping(src, mapping)
    assert out["extra"] == 1               # unmapped field copied through
    assert "uid" not in out                # system field stripped
    assert "_version" not in out
    assert out["headline"] == "Hello"      # explicit mapping still applied on top


def test_default_used_when_source_missing():
    mapping = {"fields": [{"source": "subtitle", "target": "subtitle", "default": "n/a"}]}
    out = apply_mapping({}, mapping)
    assert out["subtitle"] == "n/a"


def test_skip_if_empty_drops_none_results():
    mapping = {"fields": [{"source": "missing", "target": "x", "skip_if_empty": True}]}
    out = apply_mapping({}, mapping)
    assert "x" not in out


def test_load_mapping_rejects_missing_target(tmp_path):
    bad = tmp_path / "m.json"
    bad.write_text(json.dumps({"fields": [{"source": "a"}]}))
    with pytest.raises(ValueError):
        load_mapping(str(bad))


def test_load_mapping_rejects_empty_fields(tmp_path):
    bad = tmp_path / "m.json"
    bad.write_text(json.dumps({"fields": []}))
    with pytest.raises(ValueError):
        load_mapping(str(bad))


def test_load_mapping_rejects_unknown_transform(tmp_path):
    bad = tmp_path / "m.json"
    bad.write_text(json.dumps({"fields": [{"source": "a", "target": "b", "transform": "refrence"}]}))
    with pytest.raises(ValueError):
        load_mapping(str(bad))


def test_load_mapping_roundtrip(tmp_path):
    good = tmp_path / "m.json"
    good.write_text(json.dumps(BASIC))
    assert load_mapping(str(good))["target_content_type"] == "web_page_v2"
