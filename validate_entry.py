"""Validate a mapped payload before sending it to the CMA.

A cheap, offline guard against obvious mistakes (missing required fields, an
empty URL) so we fail before making a write call. It is *not* a substitute for
the content type's own schema validation, which the CMA enforces server-side.
"""


def validate_payload(payload, mapping):
    """Return a list of human-readable validation errors (empty == valid)."""
    errors = []

    for field in mapping.get("required_target_fields", []):
        value = payload.get(field)
        if value is None or value == "" or value == [] or value == {}:
            errors.append(f"Required target field {field!r} is missing or empty.")

    url_target = mapping.get("url_field", "url")
    if url_target in payload:
        url_value = payload.get(url_target)
        if not isinstance(url_value, str) or not url_value.strip():
            errors.append(f"URL field {url_target!r} must be a non-empty string.")

    return errors


def assert_valid(payload, mapping):
    """Raise ``ValueError`` if *payload* fails validation."""
    errors = validate_payload(payload, mapping)
    if errors:
        raise ValueError("Payload validation failed:\n  - " + "\n  - ".join(errors))
