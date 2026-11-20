"""Configuration for the Wildberries Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT                port the API listens on (default 8000)
    WILDBERRIES_PROXY   optional. Leave it unset to go out from your own
                        connection; if Wildberries refuses your IP, set one
                        datacenter proxy, http://user:pass@host:port. Keep it
                        to ONE exit: Wildberries revokes a cookie that is
                        replayed from many addresses within a minute.

Wildberries answers its own JSON only to a visitor that carries the
x_wbaas_token cookie, so the scraper opens https://www.wildberries.ru/robots.txt
once in a real, visible Chrome (patchright) to earn it, then carries on over
plain HTTP.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

WILDBERRIES_PROXY = os.environ.get("WILDBERRIES_PROXY") or None

# The exit every request leaves through: the proxy above, else your own connection.
WILDBERRIES_EXIT = os.environ.get("WILDBERRIES_PROXY") or None

WILDBERRIES_SPA_VERSION = "14.33.1"       # the x-spa-version header the site's own pages send
WILDBERRIES_TOKEN_MAX_AGE = 6 * 3600      # seconds a cookie is reused before Chrome earns a fresh one
WILDBERRIES_LIST_INTERVAL = 1.0           # seconds between two seller / brand list calls (a faster burst draws HTTP 429); 0 = no pacing


def exit_geo(proxy, timeout=12):
    """Geo of a proxy's exit IP, looked up THROUGH the proxy (ip-api.com, free
    tier, keyed per exit IP so the quota is never shared). Returns the dict
    {countryCode, regionName, city, timezone, query} or None on any failure —
    callers keep their configured/system timezone then."""
    try:
        import requests
        r = requests.get(
            "http://ip-api.com/json/?fields=status,countryCode,regionName,city,timezone,query",
            proxies={"http": proxy, "https": proxy}, timeout=timeout)
        d = r.json()
        if d.get("status") == "success" and d.get("timezone"):
            return d
    except Exception:
        pass
    return None


# ---- what the wildberries module reads: defaults for a direct run ----
def burst_slots(share):
    return share

