"""Reference resolvers, value tables and link builders for /wildberries/*.

ONE param per input (never a sibling `url` / `id` pair): each resolver takes
a bare id OR a wildberries.ru link of the same record and returns what
fetch.py needs; it raises ValueError with a user-facing message
(schema_fields.RefField turns that into a 400).

Identifier shapes (captured 2026-11-19):
  * product   the article ("Артикул", the site's nm id), digits. Links:
              /catalog/<article>/detail.aspx and its /feedbacks, /questions
              and /other-sellers sub-pages. A product's variants (colours)
              share one CARD id; reviews and questions belong to the card.
  * seller    digits. Link /seller/<id>. A seller link with a name instead
              of the id (/seller/rivegauche) is refused: no saved answer maps
              such a name to an id.
  * brand     digits, OR the slug of its page ("barista"), OR a
              /brands/<slug> link. The slug becomes the id through the
              site's own static brand file (fetch.fetch_brand).
  * category  the id of a node of the site's menu (9515), OR its page link
              (/catalog/pitanie/chay-kofe/kofe). Menu categories are not the
              product types ("subjects") a search can be narrowed to: those
              ids come from /wildberries/products/filters.
  * destination  where the order would be delivered: a city name of the
              table below, or the site's own destination id (a whole number,
              often negative). Prices, stock and delivery times are answered
              for a destination, and the site answers nothing without one.
"""
import re
from urllib.parse import quote, quote_plus, unquote, urlparse

SITE = "https://www.wildberries.ru"
HOST_SUFFIX = "wildberries.ru"

ARTICLE_RE = re.compile(r"^\d{1,12}$")
ID_RE = re.compile(r"^\d{1,12}$")
BRAND_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-_.]{0,100}$", re.I)

_PRODUCT_LINK_RE = re.compile(r"/catalog/(\d{1,12})(?:/|$)")
_SELLER_LINK_RE = re.compile(r"/seller/([^/?#]+)")
_BRAND_LINK_RE = re.compile(r"/brands/([^/?#]+)")
_CATEGORY_LINK_RE = re.compile(r"^/(?:catalog|promotions)(?:/[^?#]*)?$")

# The products of one upstream page (the site's own page size) and the last
# page it serves: search page 61 answers an error body, a seller's or
# brand's page 101 an empty one (2026-11-19).
PAGE_SIZE = 100
MAX_SEARCH_PAGE = 60
MAX_CATALOG_PAGE = 100
QUESTIONS_PAGE_SIZE = 30          # questions `take`: 31 answers HTTP 400
REVIEWS_PAGE_SIZE = 100           # our own slice of the card's one reviews file
MAX_BATCH = 100                   # ids per /products/batch call (one upstream call took 800)

# Public sort value -> the site's `sort` token (its own five; an unknown
# token silently means popular there, so anything else is refused here).
SORTS = {
    "popular": "popular",
    "rating": "rate",
    "price_asc": "priceup",
    "price_desc": "pricedown",
    "newest": "newly",
}
DEFAULT_SORT = "popular"

# The currencies the site prices in: its own list (settings-front-v2-ru.json
# `currencies`, 2026-11-19) without TZS, which the card call answers with
# HTTP 400. Any other code is answered with an unrelated product or an empty
# page, so it is refused here.
CURRENCIES = ("RUB", "BYN", "KZT", "KGS", "AMD", "UZS", "TJS", "AZN", "GEL", "USD", "ILS", "ETB", "TMT")
DEFAULT_CURRENCY = "RUB"

# Destination ids. "moscow" is the id the site itself gives a new visitor
# (every page call of 2026-11-19 carried it). The others are the id most
# pickup points of that city carry in the site's pickup-points file
# (all-poo-v12.json, 100,009 points, 2026-11-19); each one answered a card
# with a price and its own delivery time that day.
DEFAULT_DESTINATION = 1259570991
CITIES = {
    "moscow": DEFAULT_DESTINATION,
    "saint_petersburg": -1198680,
    "novosibirsk": -365401,
    "yekaterinburg": 123589409,
    "kazan": 1259571177,
    "nizhny_novgorod": 12358543,
    "chelyabinsk": -1579611,
    "samara": -284542,
    "rostov_on_don": 1259570240,
    "ufa": -5523261,
    "krasnoyarsk": -5854093,
    "voronezh": -3390370,
    "krasnodar": 12358082,
    "omsk": -3902910,
    "vladivostok": 1259571108,
}
_DESTINATION_ID_RE = re.compile(r"^-?\d{1,12}$")

# Search filters with a param of their own; an attribute filter of the
# `filters` param may not name one of these keys.
FILTER_PARAMS = {
    "priceU": "min_price, max_price",
    "fbrand": "brand",
    "fsupplier": "seller",
    "xsubject": "subject",
    "frating": "top_rated",
    "fdlvr": "max_delivery_hours",
    "foriginal": "original",
    "fpremium": "premium_seller",
    "fexpress": "express",
    "fvideo": "has_video",
}
NAMED_FILTER_KEYS = tuple(FILTER_PARAMS)
FILTER_KEY_RE = re.compile(r"^f[a-z0-9]{1,24}$")
# The largest upper price bound sent when only a lowest price is asked: the
# site wants both ends ("500000;" alone answers an empty page).
PRICE_CEILING_MINOR = 99999999900


# ---- link parsing ------------------------------------------------------------------

def _is_link(value):
    return "/" in value or "wildberries" in value.lower()


def _link_path(value, what):
    """The path of a wildberries.ru link (scheme optional); ValueError for
    another site's link."""
    text = value if "://" in value else "https://" + value.lstrip("/")
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if not (host == HOST_SUFFIX or host.endswith("." + HOST_SUFFIX)):
        raise ValueError(f"Not a wildberries.ru link. Pass {what}.")
    return unquote(parsed.path or "/")


# ---- product -----------------------------------------------------------------------

_PRODUCT_HELP = "the product's article (90858341) or its link (https://www.wildberries.ru/catalog/90858341/detail.aspx)"


def resolve_product(value):
    """An article or any product link -> the article as text."""
    value = value.strip()
    if ARTICLE_RE.match(value):
        return str(int(value))
    if _is_link(value):
        match = _PRODUCT_LINK_RE.search(_link_path(value, _PRODUCT_HELP))
        if match:
            return str(int(match.group(1)))
    raise ValueError(f"Not a Wildberries product. Pass {_PRODUCT_HELP}.")


def resolve_products(value):
    """'a, b, c' (articles and / or product links) -> a list of articles,
    in the order given, without repeats; at most MAX_BATCH."""
    items = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        article = resolve_product(part)
        if article not in items:
            items.append(article)
    if not items:
        raise ValueError(f"Pass at least one product: {_PRODUCT_HELP}.")
    if len(items) > MAX_BATCH:
        raise ValueError(f"At most {MAX_BATCH} products in one call.")
    return items


def product_link(article):
    return f"{SITE}/catalog/{article}/detail.aspx"


# ---- seller ------------------------------------------------------------------------

_SELLER_HELP = "the seller's id (843763) or its link (https://www.wildberries.ru/seller/843763)"


def resolve_seller(value):
    """A seller id or a /seller/<id> link -> the id as text."""
    value = value.strip()
    if ID_RE.match(value):
        return str(int(value))
    if _is_link(value):
        match = _SELLER_LINK_RE.search(_link_path(value, _SELLER_HELP))
        if match and ID_RE.match(match.group(1)):
            return str(int(match.group(1)))
        if match:
            raise ValueError("A seller link with a name instead of the id cannot be looked up. "
                             f"Pass {_SELLER_HELP}.")
    raise ValueError(f"Not a Wildberries seller. Pass {_SELLER_HELP}.")


def seller_link(seller_id):
    return f"{SITE}/seller/{seller_id}"


# ---- brand -------------------------------------------------------------------------

_BRAND_HELP = "the brand's id (14447), its page name (barista) or its link (https://www.wildberries.ru/brands/barista)"


def resolve_brand(value):
    """A brand id, a brand page name or a /brands/<name> link -> the id
    (digits) or the lower-cased page name; fetch.fetch_brand tells them
    apart the same way."""
    value = value.strip()
    if ID_RE.match(value):
        return str(int(value))
    if _is_link(value):
        match = _BRAND_LINK_RE.search(_link_path(value, _BRAND_HELP))
        if match:
            value = match.group(1)
        else:
            raise ValueError(f"Not a Wildberries brand link. Pass {_BRAND_HELP}.")
    if ID_RE.match(value):
        return str(int(value))
    if BRAND_SLUG_RE.match(value):
        return value.lower()
    raise ValueError(f"Not a Wildberries brand. Pass {_BRAND_HELP}.")


def brand_link(slug):
    return f"{SITE}/brands/{quote(str(slug))}" if slug else None


# ---- category ----------------------------------------------------------------------

_CATEGORY_HELP = ("the category's id (9515, from /wildberries/categories/list) or its link "
                  "(https://www.wildberries.ru/catalog/pitanie/chay-kofe/kofe)")


def resolve_category(value):
    """A menu category id or a category page link -> the id (digits) or the
    page path ("/catalog/pitanie/chay-kofe/kofe"); parsers.find_category
    looks either up in the menu."""
    value = value.strip()
    if ID_RE.match(value):
        return str(int(value))
    if value.startswith("/") or _is_link(value):
        path = value.split("?")[0].split("#")[0] if value.startswith("/") else _link_path(value, _CATEGORY_HELP)
        path = path.rstrip("/")
        if _PRODUCT_LINK_RE.search(path + "/"):
            raise ValueError(f"That is a product link, not a category. Pass {_CATEGORY_HELP}.")
        if _CATEGORY_LINK_RE.match(path) and path not in ("/catalog", "/promotions"):
            return path
    raise ValueError(f"Not a Wildberries category. Pass {_CATEGORY_HELP}.")


def category_link(path):
    return SITE + path if path else None


# ---- destination, currency ----------------------------------------------------------

def resolve_destination(value):
    """A city of CITIES ("Saint Petersburg", "saint-petersburg") or a
    destination id -> the id as a whole number."""
    text = value.strip()
    if _DESTINATION_ID_RE.match(text):
        return int(text)
    key = re.sub(r"[\s\-]+", "_", text.lower())
    if key in CITIES:
        return CITIES[key]
    raise ValueError(f"Not a known city or destination id. Cities: {', '.join(CITIES)}; "
                     "or the site's own destination id (a whole number).")


def city_of(destination):
    """The city name of a destination id of CITIES, else None."""
    return next((name for name, dest in CITIES.items() if dest == destination), None)


def search_link(query):
    return f"{SITE}/catalog/0/search.aspx?search={quote_plus(query)}"


# ---- filters -----------------------------------------------------------------------

_FILTERS_HELP = ("Pass attribute filters as key:id pairs separated by commas, with the keys and ids "
                 "/wildberries/products/filters lists (f128683:418141,f85571:136213).")


def resolve_filters(value):
    """'f128683:418141, f128683:535608, f85571:136213' -> a sorted tuple of
    (key, 'id;id') pairs, the form the site's own filter links carry."""
    wanted = {}
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        key, sep, option = part.partition(":")
        key, option = key.strip(), option.strip()
        if not sep or not FILTER_KEY_RE.match(key) or not ID_RE.match(option):
            raise ValueError(f"'{part}' is not a filter. {_FILTERS_HELP}")
        if key in NAMED_FILTER_KEYS:
            raise ValueError(f"'{key}' has a param of its own (brand, seller, subject, min_price, ...). {_FILTERS_HELP}")
        options = wanted.setdefault(key, [])
        if option not in options:
            options.append(option)
    if not wanted:
        raise ValueError(_FILTERS_HELP)
    if len(wanted) > 10:
        raise ValueError("At most 10 attribute filters in one call.")
    return [[key, ";".join(options)] for key, options in sorted(wanted.items())]


def resolve_filter_key(value):
    """The key of one filter, as /wildberries/products/filters lists it."""
    key = value.strip()
    if key in NAMED_FILTER_KEYS or FILTER_KEY_RE.match(key):
        return key
    raise ValueError("Not a filter key. Pass a key /wildberries/products/filters lists (fbrand, xsubject, f128683).")


def resolve_id_list(value, what, limit=20):
    """'14447, 24007' -> '14447;24007' (the site's own form), at most `limit` ids."""
    ids = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if not ID_RE.match(part):
            raise ValueError(f"'{part}' is not {what} id. Pass ids from /wildberries/products/filters, separated by commas.")
        if str(int(part)) not in ids:
            ids.append(str(int(part)))
    if not ids:
        raise ValueError(f"Pass at least one {what} id.")
    if len(ids) > limit:
        raise ValueError(f"At most {limit} {what} ids in one call.")
    return ";".join(ids)


# ---- static file paths ---------------------------------------------------------------

def card_path(article):
    """The path of a product's files on its basket host: vol<article // 100000>/part<article // 1000>/<article>."""
    article = int(article)
    return f"/vol{article // 100000}/part{article // 1000}/{article}"


def reviews_path(card_id):
    """The path of a card's reviews file on the reviews host. The volume is
    the card id's hundred-thousands modulo 144 and replaces them in the id
    (three cards, 2026-11-19: 70662956 -> vol130/part13062/13062956)."""
    card_id = int(card_id)
    volume = (card_id // 100000) % 144
    folded = volume * 100000 + card_id % 100000
    return f"/vol{volume}/part{folded // 1000}/{folded}/reviews/v1/ru/ru/imt/list/date/{card_id}.json"
