"""Load and apply a configurable field mapping.

The mapping is *data, not code*: it lives in a JSON file (see ``mapping.json``)
so the old->new field translation can be changed without editing Python.
"""
import json

from field_helpers import TRANSFORMS, apply_transform, strip_system_fields


def load_mapping(path):
    """Load and validate a mapping config from *path* (JSON)."""
    with open(path, "r", encoding="utf-8") as fh:
        mapping = json.load(fh)
    _validate_mapping(mapping)
    return mapping


def _validate_mapping(mapping):
    if not isinstance(mapping, dict):
        raise ValueError("Mapping file must contain a JSON object.")
    fields = mapping.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValueError("Mapping must define a non-empty 'fields' list.")
    for i, spec in enumerate(fields):
        if not isinstance(spec, dict):
            raise ValueError(f"fields[{i}] must be an object.")
        if not spec.get("target"):
            raise ValueError(f"fields[{i}] is missing the required 'target' key.")
        # Catch unknown transform names offline, before any network call.
        transform = spec.get("transform")
        if transform is not None and transform not in TRANSFORMS:
            raise ValueError(
                f"fields[{i}] (target={spec['target']!r}) uses unknown transform "
                f"{transform!r}. Available: {', '.join(sorted(TRANSFORMS))}."
            )
        # 'constant' transforms synthesise a value; everything else needs a source.
        if transform != "constant" and not spec.get("source"):
            raise ValueError(
                f"fields[{i}] (target={spec['target']!r}) needs a 'source' "
                f"unless its transform is 'constant'."
            )


def _get_source_value(source_entry, spec):
    if "source" not in spec:
        return None
    value = source_entry.get(spec["source"])
    if value is None and "default" in spec:
        return spec["default"]
    return value


def apply_mapping(source_entry, mapping):
    """Build a target entry payload from *source_entry* using *mapping*.

    Per target field:
      1. read the source value (or ``default`` when the source is missing)
      2. run the named transform (default: ``copy``)
      3. assign to the target key

    When ``copy_unmapped`` is true, source fields not named by any mapping are
    copied across verbatim first (system fields and ``drop_fields`` removed),
    then the explicit field specs run on top.
    """
    payload = {}

    if mapping.get("copy_unmapped"):
        mapped_sources = {s["source"] for s in mapping["fields"] if s.get("source")}
        drop = set(mapping.get("drop_fields", []))
        for key, value in strip_system_fields(source_entry).items():
            if key in mapped_sources or key in drop:
                continue
            payload[key] = value

    for spec in mapping["fields"]:
        value = _get_source_value(source_entry, spec)
        result = apply_transform(spec.get("transform"), value, spec, source_entry)
        if result is None and spec.get("skip_if_empty"):
            continue
        payload[spec["target"]] = result

    return payload


def source_content_type(mapping, default=None):
    return mapping.get("source_content_type") or default


def target_content_type(mapping, default=None):
    return mapping.get("target_content_type") or default


def url_field(mapping):
    return mapping.get("url_field", "url")
