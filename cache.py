"""The hosted service keeps responses in a database. This repo keeps them in
memory, for this process only, behind the same calls the wildberries module
uses: it is what lets two endpoints that read the same record pay one fetch.
An entry expires after `ttl` (a datetime.timedelta).

Every hit is a deep copy, like a row read back from a database: a caller
that edits its result never changes what the next caller gets.
"""
import copy
import json
import threading
import time

_store = {}
_lock = threading.Lock()
MAX_ENTRIES = 2000


class DontCache:
    """Wrap a result to return it without keeping it."""

    def __init__(self, data):
        self.data = data


def _key(namespace, data):
    return namespace + ":" + json.dumps(data, sort_keys=True, default=str)


def cached_call(namespace, data, fn, ttl, cache=True, refresh=False):
    """Serve fn(**data) from memory for `ttl`, else run it and keep the result.
    `ttl` may be a function (data, result) -> timedelta or None (None: do not
    keep). An exception from fn is never kept; `refresh=True` skips the read
    and overwrites the entry."""
    if not (cache and ttl):
        result = fn(**data)
        return result.data if isinstance(result, DontCache) else result
    key = _key(namespace, data)
    now = time.time()
    if not refresh:
        with _lock:
            hit = _store.get(key)
        if hit and hit[0] > now:
            return copy.deepcopy(hit[1])
    result = fn(**data)
    if isinstance(result, DontCache):
        return result.data
    keep = ttl(data, result) if callable(ttl) else ttl
    if keep:
        with _lock:
            if len(_store) >= MAX_ENTRIES:
                for stale in [k for k, (expires, _) in _store.items() if expires <= now] or list(_store)[:100]:
                    _store.pop(stale, None)
            _store[key] = (now + keep.total_seconds(), copy.deepcopy(result))
    return result


def cached(namespace, ttl):
    """Decorator form of cached_call for keyword-only functions. A
    `refresh=True` keyword is consumed here and overwrites the entry."""
    def decorate(fn):
        def inner(**kwargs):
            refresh = bool(kwargs.pop("refresh", False))
            return cached_call(namespace, kwargs, fn, ttl, refresh=refresh)
        inner.__name__ = fn.__name__
        inner.__doc__ = fn.__doc__
        return inner
    return decorate
