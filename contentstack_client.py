"""Minimal Contentstack REST client (Delivery + Management APIs).

Uses ``requests`` directly -- no SDK -- and adds what a migration needs:
region-aware base URLs, retry/backoff on rate limits (429) and transient 5xx,
and the small set of CDA/CMA calls the pipeline uses.

Header conventions:
  * Delivery API (CDA):    api_key + access_token (delivery token)
  * Management API (CMA):  api_key + authorization (management token)
"""
import json
import time

import requests


class ContentstackError(RuntimeError):
    """Raised when the Contentstack API returns an error response."""


class ContentstackClient:
    def __init__(
        self,
        api_key,
        management_token,
        delivery_token,
        cda_base_url,
        cma_base_url,
        environment,
        locale,
        max_retries=5,
        timeout=30,
    ):
        self.api_key = api_key
        self.management_token = management_token
        self.delivery_token = delivery_token
        self.cda_base_url = cda_base_url.rstrip("/")
        self.cma_base_url = cma_base_url.rstrip("/")
        self.environment = environment
        self.locale = locale
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = requests.Session()

    # Methods safe to auto-retry on a 5xx or a transient network error: the
    # request is idempotent, so re-applying it cannot duplicate data. POST is
    # excluded -- a retried create could duplicate an entry if the server
    # committed the write before the failure.
    _IDEMPOTENT = frozenset({"GET", "HEAD", "PUT", "DELETE"})

    # -- low level --------------------------------------------------------
    def _request(self, method, url, headers, params=None, json_body=None):
        idempotent = method.upper() in self._IDEMPOTENT
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self.session.request(
                    method, url, headers=headers, params=params,
                    json=json_body, timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                # Transient network error (timeout, connection reset). Retry only
                # idempotent methods; a POST may already have reached the server.
                if idempotent and attempt <= self.max_retries:
                    time.sleep(self._retry_delay(None, attempt))
                    continue
                raise ContentstackError(f"{method} {url} -> network error: {exc}") from exc

            # 429 is always safe to retry (the request was rejected, not
            # processed). 5xx is only retried for idempotent methods.
            retry = attempt <= self.max_retries and (
                resp.status_code == 429
                or (resp.status_code >= 500 and idempotent)
            )
            if retry:
                time.sleep(self._retry_delay(resp, attempt))
                continue
            if not resp.ok:
                raise ContentstackError(f"{method} {url} -> {resp.status_code}: {resp.text}")
            if not resp.content:
                return {}
            return resp.json()

    @staticmethod
    def _retry_delay(resp, attempt):
        if resp is not None:
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    # Clamp: a negative/already-elapsed value would crash
                    # time.sleep; cap a server-supplied delay so we never block
                    # for an unreasonable amount of time.
                    return min(max(0.0, float(retry_after)), 60.0)
                except ValueError:
                    pass  # HTTP-date form -> fall back to exponential backoff
        return min(2 ** (attempt - 1), 30)  # exponential backoff, capped at 30s

    def _cda_headers(self):
        return {
            "api_key": self.api_key,
            "access_token": self.delivery_token,
            "Content-Type": "application/json",
        }

    def _cma_headers(self):
        return {
            "api_key": self.api_key,
            "authorization": self.management_token,
            "Content-Type": "application/json",
        }

    # -- Delivery API (published content) ---------------------------------
    def find_published_entry_by_url(self, content_type, url, url_field="url"):
        """Return the first *published* entry whose url matches, or ``None``."""
        endpoint = f"{self.cda_base_url}/v3/content_types/{content_type}/entries"
        params = {
            "environment": self.environment,
            "locale": self.locale,
            "query": json.dumps({url_field: url}),
            "limit": 1,
        }
        data = self._request("GET", endpoint, self._cda_headers(), params=params)
        entries = data.get("entries", [])
        return entries[0] if entries else None

    # -- Management API (authoritative read + write) ----------------------
    def get_entry(self, content_type, entry_uid):
        endpoint = f"{self.cma_base_url}/v3/content_types/{content_type}/entries/{entry_uid}"
        data = self._request("GET", endpoint, self._cma_headers(), params={"locale": self.locale})
        return data.get("entry")

    def find_entry_by_url(self, content_type, url, url_field="url"):
        """Find an entry (published or not) by url via the CMA.

        Returns ``(entry_or_None, total_count)``. A ``total_count`` greater than
        1 signals ambiguous duplicates the caller should warn about before
        acting on the (arbitrary) first match.
        """
        endpoint = f"{self.cma_base_url}/v3/content_types/{content_type}/entries"
        params = {
            "locale": self.locale,
            "query": json.dumps({url_field: url}),
            "limit": 2,
            "include_count": "true",
        }
        data = self._request("GET", endpoint, self._cma_headers(), params=params)
        entries = data.get("entries", [])
        count = data.get("count", len(entries))
        return (entries[0] if entries else None), count

    def create_entry(self, content_type, entry):
        endpoint = f"{self.cma_base_url}/v3/content_types/{content_type}/entries"
        data = self._request(
            "POST", endpoint, self._cma_headers(),
            params={"locale": self.locale}, json_body={"entry": entry},
        )
        return data.get("entry")

    def update_entry(self, content_type, entry_uid, entry):
        endpoint = f"{self.cma_base_url}/v3/content_types/{content_type}/entries/{entry_uid}"
        data = self._request(
            "PUT", endpoint, self._cma_headers(),
            params={"locale": self.locale}, json_body={"entry": entry},
        )
        return data.get("entry")

    def publish_entry(self, content_type, entry_uid, environments=None, locales=None):
        endpoint = (
            f"{self.cma_base_url}/v3/content_types/{content_type}/entries/{entry_uid}/publish"
        )
        body = {
            "entry": {
                "environments": environments or [self.environment],
                "locales": locales or [self.locale],
            }
        }
        return self._request("POST", endpoint, self._cma_headers(), json_body=body)
