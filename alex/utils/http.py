from __future__ import annotations
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional
import requests

logger = logging.getLogger(__name__)

CACHE = Path(__file__).resolve().parents[2] / ".alex_cache.json"


class HttpClient:
    def __init__(self, mailto: str = "") -> None:
        self.session = requests.Session()
        ua = "AlexResearchLibrary/2.1.1"
        if mailto:
            ua += f" (mailto:{mailto})"
        self.session.headers.update({"User-Agent": ua, "Accept": "application/json"})
        if CACHE.exists():
            try:
                self.cache: dict[str, Any] = json.loads(CACHE.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}
        else:
            self.cache = {}
        # Purge legacy None entries from cache
        stale = [k for k, v in self.cache.items() if v is None]
        if stale:
            for k in stale:
                del self.cache[k]
            self._save_cache()
            logger.info("Purged %d stale None entries from cache", len(stale))

    def _save_cache(self) -> None:
        CACHE.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_raw(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: int = 30,
    ) -> str | None:
        """HTTP GET returning raw response text. Cached, rate-limited, logged on failure."""
        key = json.dumps({"url": url, "params": params or {}, "headers": headers or {}, "_raw": True}, sort_keys=True)
        if key in self.cache:
            return self.cache[key]
        try:
            r = self.session.get(url, params=params, headers=headers, timeout=timeout)
            r.raise_for_status()
            text = r.text
            self.cache[key] = text
            self._save_cache()
            return text
        except requests.exceptions.RequestException as exc:
            logger.warning("HTTP request failed for %s: %s", url, exc)
            return None
        finally:
            time.sleep(0.5)

    def get_json(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: int = 30,
    ) -> Any:
        key = json.dumps({"url": url, "params": params or {}, "headers": headers or {}}, sort_keys=True)
        if key in self.cache:
            return self.cache[key]
        try:
            r = self.session.get(url, params=params, headers=headers, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            self.cache[key] = data
            self._save_cache()
            return data
        except (requests.exceptions.RequestException, ValueError) as exc:
            logger.warning("HTTP request failed for %s: %s", url, exc)
            return None
        finally:
            time.sleep(0.5)
