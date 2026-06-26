"""Configuration loaded from the environment (.env).

Holds Contentstack credentials, the target environment/locale, content-type
defaults, region-derived API base URLs, and migration behaviour flags.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# --- Credentials / stack -------------------------------------------------
CS_API_KEY = os.getenv("CS_API_KEY")
CS_DELIVERY_TOKEN = os.getenv("CS_DELIVERY_TOKEN")
CS_MANAGEMENT_TOKEN = os.getenv("CS_MANAGEMENT_TOKEN")

# --- Target environment --------------------------------------------------
CS_ENVIRONMENT = os.getenv("CS_ENVIRONMENT", "production")
CS_LOCALE = os.getenv("CS_LOCALE", "en-us")

# --- Content types (defaults; the mapping file may override these) -------
OLD_CONTENT_TYPE_UID = os.getenv("OLD_CONTENT_TYPE_UID")
NEW_CONTENT_TYPE_UID = os.getenv("NEW_CONTENT_TYPE_UID")

# --- Migration behaviour -------------------------------------------------
MAPPING_FILE = os.getenv("MAPPING_FILE", "mapping.json")

# What to do when a target entry with the same URL already exists:
#   skip   -> leave existing content untouched (still (re)publishes it; default)
#   update -> merge the mapped fields over the existing entry, then write
#   create -> create another entry anyway (may produce duplicates)
VALID_ON_EXISTING = {"skip", "update", "create"}
ON_EXISTING = os.getenv("ON_EXISTING", "skip").strip().lower()
if ON_EXISTING not in VALID_ON_EXISTING:
    raise ValueError(
        f"Invalid ON_EXISTING={ON_EXISTING!r}. Expected one of: "
        f"{', '.join(sorted(VALID_ON_EXISTING))}."
    )

# Publish the new/updated entry after writing it.
AUTO_PUBLISH = os.getenv("AUTO_PUBLISH", "true").lower() in ("1", "true", "yes")

# --- Region --------------------------------------------------------------
# Contentstack serves each region from a different host pair (CDA / CMA).
CS_REGION = os.getenv("CS_REGION", "NA").upper()

_REGION_HOSTS = {
    "NA":       ("https://cdn.contentstack.io",          "https://api.contentstack.io"),
    "EU":       ("https://eu-cdn.contentstack.com",       "https://eu-api.contentstack.com"),
    "AZURE_NA": ("https://azure-na-cdn.contentstack.com", "https://azure-na-api.contentstack.com"),
    "AZURE_EU": ("https://azure-eu-cdn.contentstack.com", "https://azure-eu-api.contentstack.com"),
    "GCP_NA":   ("https://gcp-na-cdn.contentstack.com",   "https://gcp-na-api.contentstack.com"),
    "GCP_EU":   ("https://gcp-eu-cdn.contentstack.com",   "https://gcp-eu-api.contentstack.com"),
}

if CS_REGION not in _REGION_HOSTS:
    raise ValueError(
        f"Unknown CS_REGION={CS_REGION!r}. Expected one of: {', '.join(_REGION_HOSTS)}"
    )

CDA_BASE_URL, CMA_BASE_URL = _REGION_HOSTS[CS_REGION]


def require(*names):
    """Raise if any of the named module-level config values is missing/empty.

    Call this from entry points so a missing credential fails loudly up front
    instead of surfacing later as a confusing 401 from the API.
    """
    missing = [n for n in names if not globals().get(n)]
    if missing:
        raise EnvironmentError(
            "Missing required configuration: " + ", ".join(missing)
            + ". Set them in your environment or .env file."
        )
