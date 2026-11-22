"""What every tracking service shares."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class Tracker:
    LABEL = ""
    NEEDS_KEY = True
    METERED = True
    FREE_LIMIT = 100

    @classmethod
    def available(cls, cfg: dict) -> bool:
        return True

    @classmethod
    def clean_settings(cls, new: dict, old: dict) -> dict:
        return old

    @staticmethod
    def http_json(url: str, *, method: str = "GET", headers: dict | None = None, body=None, timeout: int = 25,
                  error=None) -> dict:
        """JSON over HTTPS. HTTP errors go to error(status, parsed_body) -> exception to raise."""
        from ..tracking import TrackingError

        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Accept": "application/json", "Content-Type": "application/json",
                                              "User-Agent": "Kern-Mail/1", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed or checked host
                return json.loads(r.read(5_000_000).decode("utf-8", "replace") or "{}")
        except urllib.error.HTTPError as e:
            try:
                parsed = json.loads(e.read(200_000).decode("utf-8", "replace") or "{}")
            except ValueError:
                parsed = {}
            if error is not None:
                raise error(e.code, parsed if isinstance(parsed, dict) else {}) from e
            raise TrackingError(f"The service answered {e.code}.", status=e.code) from e
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise TrackingError("Couldn't reach the tracking service.") from e
