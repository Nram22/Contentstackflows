"""Field-level helpers for same-stack migration.

In a same-stack migration the source and target live in the *same* stack, so
asset UIDs and entry-reference UIDs stay valid and can be reused verbatim -- we
only normalise their JSON shape into what the Content Management API expects on
create/update, and drop system-managed fields that must not be sent back.
"""

# Read-only / system-managed keys that must be stripped before creating or
# updating an entry. The CMA rejects or ignores these, and copying them from
# one entry to another is meaningless.
SYSTEM_FIELDS = {
    "uid",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
    "_version",
    "ACL",
    "_in_progress",
    "publish_details",
    "_metadata",
    "stackHeaders",
    "locale",       # set via the query param, not the body
    "_workflow",    # workflow stage is stack/state-managed
    "_owner",
    "_branch",
}


def strip_system_fields(entry):
    """Return a shallow copy of *entry* without system-managed keys."""
    return {k: v for k, v in entry.items() if k not in SYSTEM_FIELDS}


def normalize_asset(value):
    """Normalise an asset/file field value to what the CMA expects on write.

    The API may return a file field as a full asset object
    (``{"uid": "...", ...}``) or as a bare UID string. On create the CMA
    accepts the asset UID. Handles single values and lists (multiple-file
    fields). Returns ``None`` for empty input.
    """
    if value is None:
        return None
    if isinstance(value, list):
        return [normalize_asset(v) for v in value if v is not None]
    if isinstance(value, dict):
        return value.get("uid")
    return value  # already a UID string


def normalize_reference(value):
    """Normalise an entry-reference field to ``{uid, _content_type_uid}`` form.

    Same-stack references stay valid, so we keep the UID and its content type
    and drop the resolved/embedded entry data. Accepts the CMA shape (list of
    dicts), a single dict, or a bare UID string (returned as-is, since it
    cannot be fully qualified).
    """
    if value is None:
        return None
    if isinstance(value, list):
        out = []
        for v in value:
            normalized = normalize_reference(v)
            if isinstance(normalized, list):
                out.extend(normalized)
            elif normalized is not None:
                out.append(normalized)
        return out
    if isinstance(value, dict):
        ref = {"uid": value.get("uid")}
        if value.get("_content_type_uid"):
            ref["_content_type_uid"] = value["_content_type_uid"]
        return ref
    return value  # bare UID string


def _transform_copy(value, spec, source_entry):
    return value


def _transform_constant(value, spec, source_entry):
    return spec.get("value")


def _transform_asset(value, spec, source_entry):
    return normalize_asset(value)


def _transform_reference(value, spec, source_entry):
    return normalize_reference(value)


# Registry of named transforms usable from the mapping file via
# ``{"transform": "<name>"}``. Extend this dict to add custom logic.
TRANSFORMS = {
    "copy": _transform_copy,
    "constant": _transform_constant,
    "asset": _transform_asset,
    "reference": _transform_reference,
}


def apply_transform(name, value, spec, source_entry):
    """Apply a named transform; defaults to ``copy`` when *name* is falsy."""
    fn = TRANSFORMS.get(name or "copy")
    if fn is None:
        raise ValueError(
            f"Unknown transform {name!r}. Available: {', '.join(sorted(TRANSFORMS))}"
        )
    return fn(value, spec, source_entry)
