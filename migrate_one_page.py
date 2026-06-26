"""Migrate a single page from the old content type to the new one.

Pipeline (see README):
  1. find old page by URL        (Delivery API)
  2. pull the full old entry     (Management API -- authoritative copy)
  3. reuse assets/references     (field_helpers, driven by the mapping)
  4. map to the new content type (mappings.apply_mapping)
  5. validate + create/update    (validate_entry, Management API)
  6. publish                     (Management API)

Usage:
  python migrate_one_page.py --url /about-us
  python migrate_one_page.py --url /about-us --dry-run
  python migrate_one_page.py --url /about-us --mapping mapping.json \
      --on-existing update --no-publish
"""
import argparse
import json
import sys

import config
from contentstack_client import ContentstackClient, ContentstackError
from mappings import (
    apply_mapping,
    load_mapping,
    source_content_type,
    target_content_type,
    url_field,
)
from field_helpers import strip_system_fields
from validate_entry import validate_payload


def build_client():
    return ContentstackClient(
        api_key=config.CS_API_KEY,
        management_token=config.CS_MANAGEMENT_TOKEN,
        delivery_token=config.CS_DELIVERY_TOKEN,
        cda_base_url=config.CDA_BASE_URL,
        cma_base_url=config.CMA_BASE_URL,
        environment=config.CS_ENVIRONMENT,
        locale=config.CS_LOCALE,
    )


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Migrate one page within a Contentstack stack.")
    p.add_argument("--url", required=True, help="URL of the source page, e.g. /about-us")
    p.add_argument("--mapping", default=config.MAPPING_FILE, help="Path to the mapping JSON.")
    p.add_argument(
        "--on-existing", default=config.ON_EXISTING,
        choices=["skip", "update", "create"],
        help="What to do if a target entry with this URL already exists.",
    )
    p.add_argument("--no-publish", action="store_true",
                   help="Create/update the entry but do not publish it.")
    p.add_argument("--dry-run", action="store_true",
                   help="Do everything except writing to Contentstack; print the payload.")
    return p.parse_args(argv)


def log(msg):
    print(msg, flush=True)


def main(argv=None):
    args = parse_args(argv)

    # Fail fast on missing credentials before any network call.
    config.require("CS_API_KEY", "CS_DELIVERY_TOKEN", "CS_MANAGEMENT_TOKEN")

    mapping = load_mapping(args.mapping)
    old_ct = source_content_type(mapping, config.OLD_CONTENT_TYPE_UID)
    new_ct = target_content_type(mapping, config.NEW_CONTENT_TYPE_UID)
    if not old_ct or not new_ct:
        log("ERROR: source/target content type not set (in mapping file or env).")
        return 2
    uf = url_field(mapping)

    client = build_client()

    # 1. find old page by URL (published copy via the Delivery API)
    log(f"[1/6] Finding {old_ct} entry with {uf}={args.url} ...")
    found = client.find_published_entry_by_url(old_ct, args.url, url_field=uf)
    if not found:
        log(f"ERROR: no published {old_ct} entry found for {uf}={args.url!r}.")
        return 1
    entry_uid = found.get("uid")
    log(f"      found uid={entry_uid}")

    # 2. pull the full entry (the CMA copy is authoritative and complete)
    log(f"[2/6] Pulling full entry {entry_uid} ...")
    source_entry = client.get_entry(old_ct, entry_uid) or found

    # 3 + 4. reuse assets/references + map to the new content type
    log(f"[3/6] + [4/6] Mapping {old_ct} -> {new_ct} ...")
    payload = apply_mapping(source_entry, mapping)

    # 5a. validate offline before any write
    errors = validate_payload(payload, mapping)
    if errors:
        log("ERROR: mapped payload failed validation:")
        for e in errors:
            log(f"   - {e}")
        return 1

    if args.dry_run:
        log("[dry-run] payload that WOULD be created:")
        log(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    # 5b. idempotency: does a target entry with this URL already exist?
    publish = not args.no_publish and config.AUTO_PUBLISH
    target_url = payload.get(uf, args.url)
    existing, existing_count = client.find_entry_by_url(new_ct, target_url, url_field=uf)
    if existing_count > 1:
        log(f"      WARNING: {existing_count} existing {new_ct} entries match "
            f"{uf}={target_url!r}; acting on the first (uid={existing.get('uid')}).")

    if existing and args.on_existing == "skip":
        log(f"[5/6] target {new_ct} entry already exists (uid={existing.get('uid')}); "
            f"on-existing=skip -> leaving its content untouched.")
        # Re-publish defensively: a previous run may have created the entry but
        # failed before publishing it. Publishing is idempotent.
        if publish:
            log(f"[6/6] ensuring uid={existing.get('uid')} is published ...")
            client.publish_entry(new_ct, existing["uid"])
            log("Done.")
        else:
            log("[6/6] skipping publish (--no-publish or AUTO_PUBLISH=false).")
        return 0

    if existing and args.on_existing == "update":
        # A CMA update replaces the WHOLE entry, so merge the mapped fields over
        # the existing target to avoid blanking fields outside the mapping.
        merged = strip_system_fields(existing)
        merged.update(payload)
        log(f"[5/6] updating existing {new_ct} entry uid={existing.get('uid')} "
            f"({len(payload)} mapped field(s) merged over {len(merged)} total) ...")
        created = client.update_entry(new_ct, existing["uid"], merged)
    else:
        if existing:
            log(f"      note: existing entry uid={existing.get('uid')} found; "
                f"on-existing=create -> creating another one anyway.")
        log(f"[5/6] creating new {new_ct} entry ...")
        created = client.create_entry(new_ct, payload)

    new_uid = created.get("uid")
    log(f"      target uid={new_uid}")

    # 6. publish
    if not publish:
        log("[6/6] skipping publish (--no-publish or AUTO_PUBLISH=false).")
        return 0

    log(f"[6/6] publishing {new_uid} to env={config.CS_ENVIRONMENT} "
        f"locale={config.CS_LOCALE} ...")
    client.publish_entry(new_ct, new_uid)
    log("Done.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ContentstackError as exc:
        print(f"Contentstack API error: {exc}", file=sys.stderr)
        sys.exit(1)
    except (EnvironmentError, ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
