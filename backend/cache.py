"""A small in-memory cache where every entry expires (TTL = "time to live").

Used the "cache-aside" way: look in the cache first; on a miss, fetch the real data and
store it for next time. When the real data changes, delete the cache entry
("cache invalidation"), as document_service does after a new PDF is indexed.

This cache lives in the server's memory, so it is STATEFUL and per process. With two or more
server processes each would have its own copy, which is why production setups share one
cache in Redis. The interface (get / set / delete) would stay the same.
"""
import threading
import time


class TTLCache:
    def __init__(self, max_items: int = 1000):
        self.max_items = max_items
        self._data: dict[str, tuple[float, object]] = {}  # key -> (expires at, value)
        self._lock = threading.Lock()  # requests run in several threads at once
        self.hits = 0
        self.misses = 0

    def get(self, key: str):
        with self._lock:
            item = self._data.get(key)
            if item and item[0] > time.monotonic():
                self.hits += 1
                return item[1]
            self._data.pop(key, None)  # expired or missing
            self.misses += 1
            return None

    def set(self, key: str, value, ttl_seconds: float) -> None:
        with self._lock:
            if key not in self._data and len(self._data) >= self.max_items:
                self._data.pop(next(iter(self._data)))  # full: drop the oldest entry
            self._data[key] = (time.monotonic() + ttl_seconds, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = self.misses = 0

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._data), "hits": self.hits, "misses": self.misses}
