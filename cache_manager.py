import time
import redis
import json
from threading import Lock
from typing import Dict, Any, Optional, Set

# Attempt to connect to a local Redis instance
_use_redis = False
_redis_client = None

try:
    _redis_client = redis.Redis(host="localhost", port=6379, db=0, socket_connect_timeout=1.0)
    # Ping to verify it is responsive
    _redis_client.ping()
    _use_redis = True
    print("🔋 [Redis] Connected successfully. Production distributed cache layer active.")
except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
    print("⚠️ [Redis] Offline or not installed. Falling back to local In-Memory Cache/Lock (ideal for local development).")
    _use_redis = False


class HybridAuditCache:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self.local_cache: Dict[str, tuple[Dict[str, Any], float]] = {}
        self.local_lock = Lock()

    def _get_key(self, url: str) -> str:
        return f"audit:{url.strip().lower()}"

    def get(self, url: str) -> Optional[Dict[str, Any]]:
        if _use_redis:
            try:
                cached_data = _redis_client.get(self._get_key(url))
                if cached_data:
                    return json.loads(cached_data)
            except redis.RedisError as e:
                print(f"[Redis Cache Error] {e}")
            return None
        else:
            normalized = url.strip().lower()
            with self.local_lock:
                if normalized in self.local_cache:
                    data, timestamp = self.local_cache[normalized]
                    if time.time() - timestamp < self.ttl:
                        return data
                    else:
                        del self.local_cache[normalized]
                return None

    def set(self, url: str, data: Dict[str, Any]) -> None:
        if _use_redis:
            try:
                _redis_client.setex(self._get_key(url), self.ttl, json.dumps(data))
            except redis.RedisError as e:
                print(f"[Redis Cache Error] {e}")
        else:
            normalized = url.strip().lower()
            with self.local_lock:
                self.local_cache[normalized] = (data, time.time())


class HybridActiveAuditTracker:
    def __init__(self):
        self.local_active_set: Set[str] = set()
        self.local_lock = Lock()

    def _get_lock_key(self, url: str) -> str:
        return f"lock:audit:{url.strip().lower()}"

    def acquire(self, url: str, timeout: int = 180) -> bool:
        if _use_redis:
            try:
                # set with nx=True returns True if the key is created successfully
                return bool(_redis_client.set(self._get_lock_key(url), "locked", nx=True, ex=timeout))
            except redis.RedisError:
                pass  # Fallback to local memory tracking if Redis connection drops
        
        normalized = url.strip().lower()
        with self.local_lock:
            if normalized in self.local_active_set:
                return False
            self.local_active_set.add(normalized)
            return True

    def release(self, url: str) -> None:
        if _use_redis:
            try:
                _redis_client.delete(self._get_lock_key(url))
                return
            except redis.RedisError:
                pass
                
        normalized = url.strip().lower()
        with self.local_lock:
            self.local_active_set.discard(normalized)


# Initialize global hybrid managers
audit_cache = HybridAuditCache(ttl_seconds=300)
active_tracker = HybridActiveAuditTracker()