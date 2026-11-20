"""Wildberries transport: plain curl_cffi (chrome profile) from the server's
own address, plus one cookie a visible browser earns on the browser box.

Two kinds of upstream (captured 2026-11-19, every call as the site's own
pages send it):

  * FREE: the site's static files and side services. No cookie, no token;
    they answered the pod's own address 10 of 10 (pod probe 2026-11-19).
      - cdn.wbbasket.ru/api/v3/upstreams       which basket host holds an article
      - basket-NN.wbbasket.ru/vol../part../<article>/info/ru/card.json
                                               the static card: description,
                                               characteristics, the card id
      - .../<article>/info/price-history.json  weekly price points
      - feedback01.wbbasket.ru/.../imt/list/date/<card id>.json
                                               the card's newest ~1,000 reviews
      - questions.wildberries.ru/api/v1/questions
      - static-basket-01.wbbasket.ru/vol0/data/main-menu-ru-ru-v3.json,
        .../brands/<name>.json, .../brands-by-id/<id>.json,
        .../supplier-by-id/<id>.json
      - suppliers-shipment-2.wildberries.ru/api/v1/suppliers/<id>

  * TOKEN: every www.wildberries.ru/__internal/* call (search and its
    filters, live cards, seller and brand lists, suggestions). The site's
    own anti-bot answers HTTP 498 with a 1 KB challenge page unless the
    request carries the `x_wbaas_token` cookie. Only a visible Chrome clears
    that challenge, so the cookie is minted on the browser box
    (recipes/wildberries.py, the box's own address, no proxy) and replayed
    here with the minting browser's User-Agent and client hints.

What the token tolerates, measured 2026-11-19:
  * another address than the one it was minted on: yes (laptop-minted
    tokens passed from the pod direct, 5 runs over 4 minutes)
  * another chrome build in the TLS profile: yes
  * a Safari profile: NO. One such replay and the token was refused about
    two minutes later, for good. A refusal never switches the profile here.
  * many addresses within a minute (four exits at once): NO, same end. So
    every token call leaves through ONE exit (config.WILDBERRIES_EXIT).
  * the oldest token still alive was 114 minutes old with ~30 replays; the
    token itself names a 72 hour expiry.
One process-wide token lives in an identity_pool.Pool (shared mode): a 498
replaces it once per refusal wave, however many threads it hits.

Traps the calls have:
  * without the `deviceid` header an /__internal/ call is an empty HTTP 403
  * errors arrive as HTTP 200: `{"error": ..., "code": 500}` for a search
    page past 60, an empty body for a seller / brand page past 100
  * a search the site has not computed yet answers a stand-in body (one
    unrelated promoted product under `data.products`, no `total`); the same
    call a moment later answers the real page, so it is retried
  * a search with no result has no `products` key at all
  * HTTP 429 (empty) after a burst of seller / brand list calls from one
    address; one a second never drew it, so those calls are paced

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  WildberriesUpstreamError  transport failure / 5xx / stand-in body  — retryable
  WildberriesBlocked        498 / 403 / 429 / the box could not mint  — retryable
  WildberriesBadRequest     upstream 400 / an error body               — never retried
  WildberriesNotFound       404                                         — never retried
"""
import os
import random
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

# Allow direct execution (python wildberries/fetch.py): flat imports resolve
# like under the server. Idempotent when imported normally.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_client
import config
import egress
import fastjson
import identity_pool
from browser_client import BoxRefused, BoxUnavailable
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from scraper_utils import fanout, memo, sessions
from wildberries import parsers
from wildberries.refs import (PRICE_CEILING_MINOR, SITE, brand_link, product_link, reviews_path, search_link,
                              seller_link)

IMPERSONATE = "chrome"          # the only profile a token is replayed under (see the module docstring)
TIMEOUT = 30
REVIEWS_TIMEOUT = 45            # one file of ~1,000 reviews, up to 1.5 MB unpacked
FANOUT_WORKERS = 3              # a product's live card, static card and price history go out together

INTERNAL = SITE + "/__internal"
STATIC_DATA = "https://static-basket-01.wbbasket.ru/vol0/data"
UPSTREAMS = "https://cdn.wbbasket.ru/api/v3/upstreams"
REVIEWS_HOST = "https://feedback01.wbbasket.ru"
QUESTIONS = "https://questions.wildberries.ru/api/v1/questions"
SELLER_STATS = "https://suppliers-shipment-2.wildberries.ru/api/v1/suppliers"

BOX_SITE = "wildberries"        # recipes/wildberries.py
TOKEN_COOKIE = "x_wbaas_token"
CHALLENGE_MARKER = "/__wbaas/challenges/antibot/"
REMINT_GRACE_S = 10             # a re-mint this soon after the last one reuses it (a peer just re-minted)
ROUTES_TTL = 3600               # seconds the basket host table and the menu are kept in this process

# ---- headers: one dict per kind of call, as the site's own pages send them ----------
# (samples/calls/*.request.json, 2026-11-19). The session adds what a browser
# adds by itself: user-agent, the sec-ch-ua hints, accept-encoding. A token
# call takes the minting browser's user-agent, hints and accept-language
# (browser_client.headers_for); the free calls announce the exit's language.

# www.wildberries.ru/__internal/* (same-origin XHR of the storefront)
INTERNAL_HEADERS = {
    "accept": "*/*",
    "priority": "u=1, i",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "x-requested-with": "XMLHttpRequest",
}
# search, its filters and the suggestions also say who asks (0 = nobody signed in)
ANONYMOUS_HEADERS = {"x-userid": "0"}

# static files on the basket hosts (cross-site fetches of the storefront)
STATIC_HEADERS = {
    "accept": "*/*",
    "accept-language": egress.site_accept_language("wildberries"),
    "origin": SITE,
    "priority": "u=1, i",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
}
# the basket host table: fetched without the browser cache
UPSTREAMS_HEADERS = {
    "accept": "*/*",
    "accept-language": egress.site_accept_language("wildberries"),
    "cache-control": "no-cache",
    "origin": SITE,
    "pragma": "no-cache",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
}
# the reviews file (the page sends no priority header on this one)
REVIEWS_HEADERS = {
    "accept": "*/*",
    "accept-language": egress.site_accept_language("wildberries"),
    "origin": SITE,
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
}
QUESTIONS_HEADERS = {
    "accept": "*/*",
    "accept-language": egress.site_accept_language("wildberries"),
    "content-type": "application/json",
    "origin": SITE,
    "priority": "u=1, i",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "x-service-name": "site",
}
SELLER_STATS_HEADERS = {
    "accept": "*/*",
    "accept-language": egress.site_accept_language("wildberries"),
    "origin": SITE,
    "priority": "u=1, i",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "x-client-name": "site",
}


class WildberriesUpstreamError(UpstreamError):
    """Transport failure, 5xx, or a stand-in body — retryable."""


class WildberriesBlocked(WildberriesUpstreamError, Blocked):
    """498 challenge / 403 / the box could not mint a token — retryable with a fresh token."""


class WildberriesRateLimited(WildberriesBlocked):
    """HTTP 429 — retryable after a pause; the token is not at fault."""


class WildberriesBadRequest(BadRequest):
    """Upstream 400 or an error body — never retried."""


class WildberriesNotFound(NotFound):
    """The record does not exist — never retried."""


# ---- sessions ----------------------------------------------------------------------
# One curl session per worker thread (a curl handle must not be shared across
# threads), on the exit config.WILDBERRIES_EXIT names. It carries no cookie
# from call to call: the token is sent as a header on the calls that need it.
_local = threading.local()


def _session():
    return sessions.thread_session(_local, lambda: egress.exit_session(config.WILDBERRIES_EXIT, impersonate=IMPERSONATE))


def _drop_session():
    """Close the thread's session so a poisoned keep-alive connection dies."""
    sessions.drop(_local)


# ---- the token (shared, box-minted) -------------------------------------------------

def _token_of(ident):
    token = (ident.get("tokens") or {}).get(TOKEN_COOKIE)
    if not token:
        token = next((c["value"] for c in ident.get("cookies", []) if c.get("name") == TOKEN_COOKIE), None)
    return token or None


def _mint(key, hint):
    """The pool's mint function: one visible page load of /robots.txt on the
    browser box, on the box's own address (`hint` is None: no proxy). The
    identity keeps what every later call repeats: the cookie, the minting
    browser's headers, and the two ids the storefront makes up for a new
    visitor (the `deviceid` header and the `_wbauid` cookie)."""
    try:
        ident = browser_client.mint(BOX_SITE, proxy=hint)
    except (BoxUnavailable, BoxRefused) as e:
        raise WildberriesBlocked(f"token mint failed: {type(e).__name__}: {e}")
    token = _token_of(ident)
    if not token:
        raise WildberriesBlocked("the browser box answered without a token")
    visitor = f"{random.randint(10 ** 7, 10 ** 9 - 1)}{int(time.time())}"
    print(f"wildberries: token minted ({len(token)} chars)")
    value = {
        "cookie": f"{TOKEN_COOKIE}={token}; _wbauid={visitor}",
        "headers": browser_client.headers_for(ident),
        "device_id": "site_" + uuid.uuid4().hex,
        "visitor": visitor,
    }
    return identity_pool.Identity(value, exit=hint, expires_at=float(ident.get("expires_at") or 0) or None)


_tokens = identity_pool.Pool(BOX_SITE, _mint, max_age=lambda: config.WILDBERRIES_TOKEN_MAX_AGE, mints_per_minute=5,
                             min_interval=REMINT_GRACE_S)


def _token(replace=None):
    """The shared token identity, minted when the process has none;
    `replace` = the identity a refused call carried (re-minted only if it is
    still the current one). The pool's mint budget maps to a block."""
    try:
        return _tokens.get(replace=replace)
    except identity_pool.MintBudgetExceeded as e:
        raise WildberriesBlocked(f"token mint failed: {e}")


def _query_id(visitor):
    """The x-queryid the storefront sends with a search: "qid", the
    visitor id, the UTC time to the second."""
    return f"qid{visitor}{datetime.now(timezone.utc):%Y%m%d%H%M%S}"


# ---- requests ----------------------------------------------------------------------

def _retrying(fn, remint=None):
    """Shared retry policy. A transport error drops the session. A refused
    token (498 / 403) drops it and runs `remint()` before the next try; a
    429 only waits, the token is not at fault."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except WildberriesRateLimited as e:
            last = e
            _drop_session()
        except WildberriesBlocked as e:
            last = e
            _drop_session()
            if remint is not None and attempt < config.MAX_RETRIES:
                try:
                    remint()
                except WildberriesBlocked as mint_error:
                    last = mint_error
        except WildberriesUpstreamError as e:
            last = e
            _drop_session()
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _send(url, headers, timeout):
    sess = _session()
    sess.cookies.clear()
    try:
        return sess.get(url, headers=headers, timeout=timeout)
    except Exception as e:
        raise WildberriesUpstreamError(f"request failed: {type(e).__name__}: {e}")


def _decode(resp, label):
    try:
        return fastjson.loads(resp.content)
    except ValueError:
        raise WildberriesUpstreamError(f"non-JSON answer from {label}: {resp.text[:120]!r}")


def _get_free(url, headers, label, *, referer, timeout=TIMEOUT, missing=None):
    """GET a free call -> decoded JSON. A 404 raises WildberriesNotFound, or
    returns `missing` when the caller names one (a file the site simply does
    not have for this record)."""
    def once():
        resp = _send(url, {**headers, "referer": referer}, timeout)
        if resp.status_code == 404:
            if missing is not None:
                return missing
            raise WildberriesNotFound(f"{label} not found")
        if resp.status_code == 400:
            raise WildberriesBadRequest(f"{label}: {resp.text[:200]}")
        if resp.status_code == 429:
            raise WildberriesRateLimited(f"HTTP 429 on {label}")
        if resp.status_code in (401, 403, 498):
            raise WildberriesBlocked(f"HTTP {resp.status_code} on {label}")
        if resp.status_code != 200:
            raise WildberriesUpstreamError(f"HTTP {resp.status_code} on {label}")
        return _decode(resp, label)
    return _retrying(once)


def _get_internal(path, query, label, *, referer, extra=None, search=False, timeout=TIMEOUT, check=None):
    """GET an /__internal/ call with the shared token -> decoded JSON, or
    None for an HTTP 200 with an empty body (a list page past the end).
    `check(raw)` judges the decoded body inside the same tries: what it
    raises is retried (or not) like any other failure of the call, so a
    call never gets a second set of tries around this one."""
    url = f"{INTERNAL}{path}?{query}"
    used = [None]           # the token identity the last attempt carried (replaced after a refusal)

    def once():
        used[0] = None          # a try that fails at the mint carries no token (not the one of the try before)
        used[0] = _token()
        value = used[0].value
        headers = {**value["headers"], **INTERNAL_HEADERS, "deviceid": value["device_id"], "referer": referer,
                   "x-spa-version": config.WILDBERRIES_SPA_VERSION, "cookie": value["cookie"], **(extra or {})}
        if search:
            headers["x-queryid"] = _query_id(value["visitor"])
        resp = _send(url, headers, timeout)
        if resp.status_code == 429:
            raise WildberriesRateLimited(f"HTTP 429 on {label}")
        if resp.status_code in (498, 403, 401) or CHALLENGE_MARKER in resp.text[:2000]:
            raise WildberriesBlocked(f"HTTP {resp.status_code} on {label}: the token was refused")
        if resp.status_code == 404:
            raise WildberriesNotFound(f"{label} not found")
        if resp.status_code == 400:
            raise WildberriesBadRequest(f"{label}: {resp.text[:200]}")
        if resp.status_code != 200:
            raise WildberriesUpstreamError(f"HTTP {resp.status_code} on {label}")
        raw = _decode(resp, label) if resp.content.strip() else None
        if check is not None:
            check(raw)
        return raw

    def remint():
        # only a token the site refused is replaced: a try that failed at the mint itself carried none,
        # and the next try mints anyway
        if used[0] is not None:
            _token(replace=used[0])
    return _retrying(once, remint=remint)


# ---- pacing of the seller and brand lists ----------------------------------------------
# The list service answers HTTP 429 to a burst from one address: about 13
# calls in 40 seconds, several of them within one second, drew it for some
# minutes, while 40 calls at one a second all passed (2026-11-19). So these
# calls leave config.WILDBERRIES_LIST_INTERVAL seconds apart, process-wide;
# a caller waits for its slot. Search and card calls showed no such limit.
_pace_lock = threading.Lock()
_next_list_call = 0.0


def _wait_for_list_slot():
    global _next_list_call
    interval = float(config.WILDBERRIES_LIST_INTERVAL or 0)
    if interval <= 0:
        return
    with _pace_lock:
        now = time.monotonic()
        slot = max(now, _next_list_call)
        _next_list_call = slot + interval
    if slot > now:
        time.sleep(slot - now)


# ---- fan-out ------------------------------------------------------------------------
# A long-lived pool keeps its threads' curl sessions warm between requests.
_pool = ThreadPoolExecutor(max_workers=FANOUT_WORKERS * 4, thread_name_prefix="wildberries-fanout")


def together(fns):
    """Run zero-arg callables at once (the first on the caller's thread);
    results align with `fns`."""
    return fanout.on_pool_caller_first(_pool, fns)


# ---- the basket host table and the menu (kept in the process) ------------------------
_memo = {}
_memo_lock = threading.Lock()


def _site_file(url, headers, label):
    """GET one of the site's own reference files (the host table, the menu).
    A 404 / 400 on such a file is the site's failure, never "the caller's
    record does not exist" or "the caller's params are wrong"."""
    try:
        return _get_free(url, headers, label, referer=SITE + "/")
    except (WildberriesNotFound, WildberriesBadRequest) as e:
        raise WildberriesUpstreamError(f"the site did not serve its {label}: {e}")


def basket_table():
    """[(first volume, last volume, host)] from the site's own table."""
    def build():
        raw = _site_file(f"{UPSTREAMS}?t={int(time.time() * 1000)}", UPSTREAMS_HEADERS, "basket host table")
        table = parsers.parse_basket_hosts(raw)
        if not table:
            raise WildberriesUpstreamError("the basket host table has an unknown shape")
        return table
    return memo.expiring(_memo, _memo_lock, "basket_routes", ROUTES_TTL, build)


def basket_base(article):
    """https://<basket host>/vol../part../<article> for an article, or None
    when no host of the site's table holds its volume."""
    return parsers.basket_base(basket_table(), article)


def fetch_menu():
    """The site's whole menu tree (a list of top-level nodes, ~875 KB)."""
    return memo.expiring(_memo, _memo_lock, "menu", ROUTES_TTL, lambda: _site_file(
        f"{STATIC_DATA}/main-menu-ru-ru-v3.json", STATIC_HEADERS, "menu"))


# ---- products: the free files -------------------------------------------------------

def fetch_static_card(article):
    """A product's static card (description, characteristics, the card id).
    WildberriesNotFound for an article the site never had."""
    base = basket_base(article)
    if base is None:
        raise WildberriesNotFound(f"product {article} not found")
    return _get_free(f"{base}/info/ru/card.json", STATIC_HEADERS, f"product {article}", referer=product_link(article))


def fetch_price_history(article):
    """A product's weekly price points, or [] when the site keeps none."""
    base = basket_base(article)
    if base is None:
        return []
    raw = _get_free(f"{base}/info/price-history.json", STATIC_HEADERS, f"price history of {article}",
                    referer=product_link(article), missing=[])
    return raw if isinstance(raw, list) else []


def fetch_reviews(card_id, article):
    """The card's reviews file (its newest ~1,000 reviews plus the rating
    summary), or None for a card nobody reviewed (the file does not exist)."""
    return _get_free(REVIEWS_HOST + reviews_path(card_id), REVIEWS_HEADERS, f"reviews of card {card_id}",
                     referer=product_link(article), timeout=REVIEWS_TIMEOUT, missing={}) or None


def fetch_questions(card_id, article, take, skip):
    """One page of a card's questions: {questions, count, err}."""
    query = urlencode({"imtId": card_id, "take": take, "skip": skip})
    return _get_free(f"{QUESTIONS}?{query}", QUESTIONS_HEADERS, f"questions of card {card_id}",
                     referer=f"{SITE}/catalog/{article}/questions?imtId={card_id}")


# ---- products: the token calls ------------------------------------------------------

def fetch_cards(articles, destination, currency):
    """The live cards (price, stock, delivery) of one or more articles:
    {"products": [...]}, holding only the articles the site still lists."""
    query = (f"appType=1&curr={currency.lower()}&dest={destination}&spp=30&hide_vflags=4294967296&mtype=257&lang=ru"
             f"&ab_testing=false&nm={';'.join(str(a) for a in articles)}")
    raw = _get_internal("/u-card/cards/v4/detail", query, "product cards", referer=product_link(articles[0]))
    if not isinstance(raw, dict) or not isinstance(raw.get("products"), list):
        raise WildberriesUpstreamError("the card call answered an unknown shape")
    return raw


def _price_token(min_price, max_price):
    """`priceU` for a price range in the request's currency, or None. The
    site wants both ends: an open end answers an empty page."""
    if min_price is None and max_price is None:
        return None
    low = int(round((min_price or 0) * 100)) or 1
    high = int(round(max_price * 100)) if max_price is not None else PRICE_CEILING_MINOR
    return f"{low};{high}"


def _listing_query(base, page, sort, filters, min_price, max_price):
    """The query string of a list call, its keys in the order the site's
    own links carry them (sorted by name)."""
    params = dict(base)
    params.update(filters or {})
    price = _price_token(min_price, max_price)
    if price:
        params["priceU"] = price
    if page and page > 1:
        params["page"] = page
    if sort:
        params["sort"] = sort
    return urlencode(sorted(params.items()))


def _common(destination, currency):
    return {"ab_testing": "false", "appType": 1, "curr": currency.lower(), "dest": destination,
            "hide_vflags": 4294967296, "lang": "ru", "spp": 30}


def _is_stand_in(raw):
    """True for the body the search answers while it has not computed a
    query: no `total`, one unrelated promoted product under `data.products`."""
    return isinstance(raw, dict) and "products" not in raw and isinstance(raw.get("data"), dict) \
        and "products" in raw["data"]


def _search(params, label, referer):
    def check(raw):
        if not isinstance(raw, dict):
            raise WildberriesUpstreamError(f"{label} answered an unknown shape")
        if raw.get("error"):
            raise WildberriesBadRequest(f"{label}: {raw.get('error')}")
        if _is_stand_in(raw):
            raise WildberriesUpstreamError(f"{label} answered a stand-in page")
    # the body is judged inside the call's own tries: a second set of tries around it sent a refused or
    # failing search MAX_RETRIES x MAX_RETRIES times, minting a token on most of them
    return _get_internal("/u-search/exactmatch/ru/common/v18/search", urlencode(sorted(params.items())), label,
                         referer=referer, extra=ANONYMOUS_HEADERS, search=True, check=check)


def fetch_search(query, *, page, sort, destination, currency, filters=None, min_price=None, max_price=None,
                 referer=None, inherit_filters=True):
    """One page (100 products) of a search. `query` is the shopper's words,
    or a menu category's own search phrase (then `inherit_filters` is False
    and `referer` the category page, as the site sends it)."""
    params = {**_common(destination, currency), "locale": "ru", "query": query, "resultset": "catalog",
              "suppressSpellcheck": "false", **(filters or {})}
    if inherit_filters:
        params["inheritFilters"] = "true"
    price = _price_token(min_price, max_price)
    if price:
        params["priceU"] = price
    if page > 1:
        params["page"] = page
    params["sort"] = sort
    return _search(params, "search", referer or search_link(query))


def fetch_search_filters(query, *, destination, currency, full_key=None, filters=None):
    """The filters of a search: {"data": {"filters": [...], "total": n}}.
    `full_key` asks for every option of ONE filter (its `fullKey`); without
    it each filter lists its top options."""
    params = {**_common(destination, currency), "autoselectFilters": "false", "inheritFilters": "true", "locale": "ru",
              "query": query, "resultset": "filters", "scale": 5, "suppressSpellcheck": "false", **(filters or {})}
    if full_key:
        params["filters"] = full_key
    return _search(params, "search filters", search_link(query))


def fetch_seller_products(seller_id, *, page, sort, destination, currency, filters=None, min_price=None,
                          max_price=None):
    """One page (100 products) of a seller's list: {"products", "total"},
    or None past the last page the site serves."""
    base = {**_common(destination, currency), "supplier": seller_id, "page": page}
    query = _listing_query(base, None, sort, filters, min_price, max_price)
    _wait_for_list_slot()
    return _get_internal("/u-catalog/sellers/v4/catalog", query, f"products of seller {seller_id}",
                         referer=seller_link(seller_id))


def fetch_brand_products(brand_id, slug, *, page, sort, destination, currency, filters=None, min_price=None,
                         max_price=None):
    """One page (100 products) of a brand's list: {"products", "total"},
    or None past the last page the site serves."""
    base = {**_common(destination, currency), "brand": brand_id}
    query = _listing_query(base, page, sort, filters, min_price, max_price)
    _wait_for_list_slot()
    return _get_internal("/u-catalog/brands/v4/catalog", query, f"products of brand {brand_id}",
                         referer=brand_link(slug) or SITE + "/")


def fetch_suggestions(query):
    """The search box's suggestions for what was typed: {"bl": [...]}."""
    params = f"ab_testing=false&gender=common&locale=ru&lang=ru&appType=1&query={quote(query)}"
    raw = _get_internal("/u-suggests/suggests/api/v9/hint", params, "suggestions", referer=SITE + "/",
                        extra=ANONYMOUS_HEADERS)
    if not isinstance(raw, dict):
        raise WildberriesUpstreamError("the suggestions call answered an unknown shape")
    return raw


# ---- brands and sellers: the free files ----------------------------------------------

def fetch_brand(ref):
    """A brand's own record ({id, name, url, ...}) for an id (digits) or a
    page name. WildberriesNotFound when the site has no such brand."""
    if str(ref).isdigit():
        url, referer = f"{STATIC_DATA}/brands-by-id/{ref}.json", SITE + "/"
    else:
        url, referer = f"{STATIC_DATA}/brands/{quote(str(ref))}.json", brand_link(ref)
    raw = _get_free(url, STATIC_HEADERS, f"brand {ref}", referer=referer)
    if not isinstance(raw, dict) or not raw.get("id"):
        raise WildberriesNotFound(f"brand {ref} not found")
    return raw


def fetch_seller_legal(seller_id):
    """A seller's legal record, or None when the site has no such file."""
    return _get_free(f"{STATIC_DATA}/supplier-by-id/{seller_id}.json", STATIC_HEADERS, f"seller {seller_id}",
                     referer=seller_link(seller_id), missing={}) or None


def fetch_seller_stats(seller_id, currency):
    """A seller's rating record. An id the site never had still answers
    HTTP 200, with zeros and no registration date."""
    return _get_free(f"{SELLER_STATS}/{seller_id}?curr={currency.upper()}", SELLER_STATS_HEADERS,
                     f"seller {seller_id}", referer=seller_link(seller_id))
