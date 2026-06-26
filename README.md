# Contentstack Same-Stack Migration

Migrate a single page from an **old content type to a new one within the same
Contentstack stack** (e.g. `web_page` → `web_page_v2`). Because the source and
target live in the same stack, existing assets and entry references are reused
**by UID** — nothing is re-uploaded or duplicated.

---

## How it works (functionally)

One invocation migrates **one page**, identified by its URL. Here is exactly
what happens, end to end, when you run
`python migrate_one_page.py --url /about-us`:

### 1. Load config & mapping
`config.py` reads credentials and settings from the environment / `.env`, and
derives the region's API hosts (`CDA_BASE_URL`, `CMA_BASE_URL`). Missing
credentials fail fast before any network call. `mappings.load_mapping()` reads
`mapping.json` and validates it offline (every field has a `target`, every
`transform` name is known, etc.) so a malformed mapping is rejected up front.
The source/target content types come from the mapping file, falling back to
`OLD_/NEW_CONTENT_TYPE_UID` in the env.

### 2. Find the old page by URL — *Delivery API*
`client.find_published_entry_by_url()` queries the **Content Delivery API**
(`cdn.*`) for a *published* entry of the old content type whose `url` field
matches, scoped to the configured environment + locale. No match → the run
stops with exit code 1 (nothing was written).

### 3. Pull the full old entry — *Management API*
`client.get_entry()` fetches the complete, authoritative copy of that entry
from the **Content Management API** (`api.*`). The Delivery copy is only used to
discover the entry's `uid`; the CMA copy is what gets mapped.

### 4. Map old → new, reusing assets & references
`mappings.apply_mapping()` builds the new entry **payload** from the source
entry using `mapping.json`. For each target field it:

1. reads the source value (or a `default` if the source is absent),
2. runs the field's `transform` (default `copy`),
3. assigns the result to the target key.

Same-stack reuse happens here: `field_helpers` normalises **asset** fields down
to their asset UID and **reference** fields down to `{uid, _content_type_uid}`,
so the new entry points at the *same* assets/entries already in the stack.
System-managed keys (`uid`, `created_at`, `publish_details`, `_version`, …) are
never carried over.

### 5. Validate, then write — *Management API*
`validate_entry.validate_payload()` checks the payload offline (required fields
present, URL is a non-empty string). Any failure stops the run *before* writing.

The tool then does an **idempotency check** — `client.find_entry_by_url()` looks
for an existing target entry with the same URL — and branches on `--on-existing`:

| Situation | Action |
|---|---|
| No existing target | **Create** the new entry (CMA `POST`) |
| Exists, `skip` (default) | Leave content untouched, but still **(re)publish** it (see Safety) |
| Exists, `update` | **Merge** the mapped fields over the existing entry, then write (CMA `PUT`) |
| Exists, `create` | Create another entry anyway (may duplicate) |

### 6. Publish — *Management API*
Unless `--no-publish` / `AUTO_PUBLISH=false`, `client.publish_entry()` publishes
the new/updated entry to the configured environment + locale. The run prints
each step (`[1/6] … [6/6]`) and exits 0 on success.

> Use `--dry-run` to execute steps 1–5a (read + map + validate) and **print the
> exact payload that would be written**, without any write.

---

## The mapping engine

The field translation is **data, not code** — edit `mapping.json`, no Python
changes needed.

```json
{
  "source_content_type": "web_page",
  "target_content_type": "web_page_v2",
  "url_field": "url",
  "copy_unmapped": false,
  "drop_fields": [],
  "required_target_fields": ["title", "url"],
  "fields": [
    { "source": "title", "target": "title" },
    { "source": "hero_image", "target": "hero_image", "transform": "asset" },
    { "source": "related_pages", "target": "related_pages", "transform": "reference" },
    { "target": "migrated_from", "transform": "constant", "value": "web_page" }
  ]
}
```

**Top-level keys**

- `source_content_type` / `target_content_type` — override the `.env` UIDs.
- `url_field` — field used to look up and de-duplicate by URL (default `url`).
- `copy_unmapped` — when `true`, copy every source field not named in `fields`
  verbatim (system fields and `drop_fields` removed), then apply the explicit
  `fields` on top. See the caveat under Safety.
- `drop_fields` — source fields to exclude when `copy_unmapped` is on.
- `required_target_fields` — fail validation before any write if these are
  missing/empty in the mapped payload.

**Per-field `fields[]` keys**

- `target` (required) — destination field on the new content type.
- `source` — source field (required unless `transform` is `constant`).
- `default` — value used when the source field is absent.
- `skip_if_empty` — drop the field from the payload when the result is `None`.
- `transform` — one of:
  - `copy` (default) — copy the value through unchanged.
  - `constant` — use a literal `value` from the spec (no source needed).
  - `asset` — reduce a file field to its asset UID(s).
  - `reference` — reduce an entry reference to `{uid, _content_type_uid}`.

Add custom transforms by extending the `TRANSFORMS` registry in
`field_helpers.py`.

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in your real values
```

`.env` keys (see `.env.example`):

| Key | Purpose |
|---|---|
| `CS_API_KEY` | Stack API key |
| `CS_DELIVERY_TOKEN` | Read published content (Delivery API) |
| `CS_MANAGEMENT_TOKEN` | Read full entries + write/publish (Management API) |
| `CS_ENVIRONMENT` | Publish target, e.g. `production` |
| `CS_LOCALE` | Locale, e.g. `en-us` |
| `CS_REGION` | `NA`, `EU`, `AZURE_NA`, `AZURE_EU`, `GCP_NA`, `GCP_EU` |
| `OLD_CONTENT_TYPE_UID` / `NEW_CONTENT_TYPE_UID` | Defaults if the mapping file omits them |
| `MAPPING_FILE` | Path to the mapping JSON (default `mapping.json`) |
| `ON_EXISTING` | `skip` (default), `update`, or `create` — validated at startup |
| `AUTO_PUBLISH` | `true`/`false` |

## Run

```bash
# preview the mapped payload without writing anything
python migrate_one_page.py --url /about-us --dry-run

# migrate for real (create + publish)
python migrate_one_page.py --url /about-us

# update an existing target entry instead of skipping it, without publishing
python migrate_one_page.py --url /about-us --on-existing update --no-publish
```

CLI flags override the matching `.env` values: `--mapping`, `--on-existing`,
`--no-publish`, `--dry-run`.

---

## Behaviour & safety semantics

- **Idempotent re-runs.** With the default `ON_EXISTING=skip`, re-running on a
  URL that already migrated does **not** create a duplicate. An invalid
  `ON_EXISTING` value is rejected at startup rather than silently falling
  through to a destructive action.
- **`skip` ensures the page is live.** If a prior run created the target entry
  but failed before publishing, `skip` will (idempotently) **re-publish** the
  existing entry rather than reporting success while the page stays unpublished.
  Content is never modified in `skip` mode.
- **`update` is a merge, not a wipe.** A Contentstack CMA update replaces the
  whole entry, so the tool first merges the mapped fields *over* the existing
  target entry — fields outside the mapping are preserved, not blanked.
- **`create` can duplicate.** It is the explicit opt-in for intentionally making
  another entry; if you don't want duplicates, leave it on `skip`.
- **Duplicate detection is best-effort.** If more than one target entry already
  shares the URL, the tool warns and acts on the first match.
- **Retries.** Rate limits (429) are retried for all calls; transient 5xx and
  network errors are retried only for idempotent reads/updates — a `create`
  POST is **not** auto-retried, to avoid creating a duplicate when the server
  committed the write but the response was lost. Backoff honours `Retry-After`
  (clamped) and otherwise backs off exponentially.
- **Validation before writes.** Required-field and URL checks run offline, so a
  bad mapping fails before touching the live stack.
- **`copy_unmapped` caveat.** When enabled, unmapped **asset/file** fields are
  copied in their read shape rather than reduced to a UID. List complex fields
  (assets/references) explicitly in `fields[]` with the right transform.

---

## Project layout

| File | Responsibility |
|---|---|
| `config.py` | Env + region → base URLs and behaviour flags (validated) |
| `contentstack_client.py` | Thin CDA/CMA REST client (auth, retries, backoff) |
| `mappings.py` | Load + apply the configurable field mapping |
| `field_helpers.py` | Asset/reference reuse + transform registry |
| `validate_entry.py` | Offline payload validation |
| `migrate_one_page.py` | CLI runner that wires the 6-step pipeline together |
| `mapping.json` | The editable mapping config |

## Tests

Pure-logic tests (mapping, transforms, validation) run offline — no network or
credentials:

```bash
pip install -r requirements-dev.txt
pytest -q
```
