from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import Any, Optional
import requests

CACHE = Path(".alex_cache.json")

class HttpClient:
    def __init__(self, mailto: str = "") -> None:
        self.session = requests.Session()
        ua = "AlexResearchLibrary/2.1.1"
        if mailto:
            ua += f" (mailto:{mailto})"
        self.session.headers.update({"User-Agent": ua, "Accept": "application/json"})
        if CACHE.exists():
            try:
                self.cache = json.loads(CACHE.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}
        else:
            self.cache = {}

    def _save_cache(self) -> None:
        CACHE.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_json(self, url: str, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None, timeout: int = 30):
        key = json.dumps({"url": url, "params": params or {}, "headers": headers or {}}, sort_keys=True)
        if key in self.cache:
            return self.cache[key]
        try:
            r = self.session.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                self.cache[key] = data
                self._save_cache()
                time.sleep(0.5)
                return data
        except Exception:
            pass
        self.cache[key] = None
        self._save_cache()
        time.sleep(0.5)
        return None
