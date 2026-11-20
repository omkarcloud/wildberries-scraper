"""The /wildberries/* endpoint functions (route_glue's route_table calls
them with the schema's loaded kwargs). Caching happens here
(cache.cached_call keyed on the validated params):

  * one upstream page = one cache row for the lists
  * a product's static card is one row shared by details, reviews and
    questions (they all need its card id), so a client reading all three
    fetches it once
  * a card's reviews are ONE upstream file: its parse is cached once per
    card and every page is a slice of it
  * paged endpoints return a `pagination` block for route_glue.paginate
"""
import math
import threading

from cache import cached_call
from scraper_utils import fanout, memo
from wildberries import cache_config as ttl
from wildberries import fetch, parsers
from wildberries.fetch import (WildberriesBadRequest, WildberriesNotFound, WildberriesUpstreamError)
from wildberries.refs import (MAX_CATALOG_PAGE, MAX_SEARCH_PAGE, QUESTIONS_PAGE_SIZE, REVIEWS_PAGE_SIZE, SORTS,
                              category_link, city_of, product_link, seller_link)


# ---- shared pieces --------------------------------------------------------------------

def _basket():
    """A function article -> the base link of its files (for photo links).
    A list page is still answered when the host table cannot be read: its
    rows then carry no photo link."""
    try:
        table = fetch.basket_table()
    except WildberriesUpstreamError:
        table = []
    return lambda article: parsers.basket_base(table, article)


def _market(destination, currency):
    return {"destination": {"id": destination, "city": city_of(destination)}, "currency": currency}


def _tokens(brand=None, seller=None, subject=None, top_rated=None, max_delivery_hours=None, original=None,
            premium_seller=None, express=None, has_video=None, filters=None):
    """The request's filters as the site's own query tokens."""
    tokens = {}
    if brand:
        tokens["fbrand"] = brand
    if seller:
        tokens["fsupplier"] = seller
    if subject:
        tokens["xsubject"] = subject
    if top_rated:
        tokens["frating"] = 1
    if max_delivery_hours:
        tokens["fdlvr"] = max_delivery_hours
    if original:
        tokens["foriginal"] = 1
    if premium_seller:
        tokens["fpremium"] = 1
    if express:
        tokens["fexpress"] = 1
    if has_video:
        tokens["fvideo"] = 1
    for key, options in filters or []:
        tokens[key] = options
    return tokens


def _listing(raw, page, max_page, currency):
    parsed = parsers.parse_listing(raw, currency, _basket())
    total = parsed["total"]
    if total is None and page == 1:
        total = len(parsed["results"])
    return {"results": parsed["results"],
            "pagination": parsers.pagination(page, total, max_page, len(parsed["results"]))}


# ---- products/search -------------------------------------------------------------------

def _filters_of(query, destination, currency):
    return cached_call("wildberries.filters", {"query": query, "destination": destination, "currency": currency},
                       lambda **data: parsers.parse_filters(fetch.fetch_search_filters(**data)), ttl.FILTERS_CACHE)


def _check_attribute_filters(filters, query, destination, currency):
    """A key this search does not offer would be ignored by the site: refuse it."""
    if not filters:
        return
    offered = {f["key"]: f for f in _filters_of(query, destination, currency)["filters"]}
    for key, _ in filters:
        if key not in offered:
            raise WildberriesBadRequest(f"filters: this search has no filter '{key}'. "
                                        "/wildberries/products/filters lists the ones it has.")
        if offered[key]["type"] != "choice":
            raise WildberriesBadRequest(f"filters: '{key}' is not a list of options and cannot be set here.")


def _products_search(query, page, sort, min_price, max_price, destination, currency, filters=None, **named):
    _check_attribute_filters(filters, query, destination, currency)
    raw = fetch.fetch_search(query, page=page, sort=SORTS[sort], destination=destination, currency=currency,
                             filters=_tokens(filters=filters, **named), min_price=min_price, max_price=max_price)
    return {"query": query, "sort": sort, **_market(destination, currency),
            **_listing(raw, page, MAX_SEARCH_PAGE, currency)}


def products_search(**data):
    return cached_call("wildberries.search", data, _products_search, ttl.LISTING_CACHE)


# ---- products/filters ------------------------------------------------------------------

def _public_filter(row):
    """A filter row without the site's internal key for its full option list."""
    return {key: value for key, value in row.items() if key != "full_key"}


def _products_filters(query, filter, destination, currency):
    base = _filters_of(query, destination, currency)
    body = {"query": query, **_market(destination, currency), "total_count": base["total_count"]}
    if not filter:
        return {**body, "filters": [_public_filter(f) for f in base["filters"]]}
    wanted = next((f for f in base["filters"] if f["key"] == filter), None)
    if wanted is None:
        raise WildberriesBadRequest(f"filter: this search has no filter '{filter}'. Leave `filter` out to list them.")
    if wanted["full_key"]:
        full = parsers.parse_filters(fetch.fetch_search_filters(query, destination=destination, currency=currency,
                                                                full_key=wanted["full_key"]))
        wanted = next((f for f in full["filters"] if f["key"] == filter), wanted)
    return {**body, "filters": [_public_filter(wanted)]}


def products_filters(**data):
    return cached_call("wildberries.products_filters", data, _products_filters, ttl.FILTERS_CACHE)


# ---- products/details ------------------------------------------------------------------

def _static_card(product):
    return cached_call("wildberries.static_card", {"product": product},
                       lambda product: fetch.fetch_static_card(product), ttl.STATIC_CARD_CACHE)


def _product_details(product, destination, currency):
    live_raw, static, history = fetch.together([
        lambda: fetch.fetch_cards([product], destination, currency),
        fanout.soft(lambda: _static_card(product), None, (WildberriesNotFound,)),
        fanout.soft(lambda: fetch.fetch_price_history(product), [], (WildberriesUpstreamError, WildberriesNotFound)),
    ])
    live = next((row for row in live_raw["products"] if str(row.get("id")) == str(product)), None)
    if live is None and static is None:
        raise WildberriesNotFound(f"product {product} not found")
    record = parsers.parse_product(product, live, static, history, currency, destination, _basket())
    record["destination"] = _market(destination, currency)["destination"]
    return record


def products_details(**data):
    return cached_call("wildberries.product", data, _product_details, ttl.PRODUCT_CACHE)


# ---- products/batch --------------------------------------------------------------------

def _products_batch(products, destination, currency):
    rows = parsers.parse_cards(fetch.fetch_cards(products, destination, currency), currency, _basket())
    by_id = {str(row["id"]): row for row in rows}
    results = [by_id[article] for article in products if article in by_id]
    return {**_market(destination, currency), "count": len(results), "results": results,
            "not_found": [int(article) for article in products if article not in by_id]}


def products_batch(**data):
    return cached_call("wildberries.batch", data, _products_batch, ttl.BATCH_CACHE)


# ---- products/reviews ------------------------------------------------------------------

def _card_id(product):
    """The card a product belongs to (its static card names it)."""
    card_id = parsers.card_id_of(_static_card(product))
    if not card_id:
        raise WildberriesNotFound(f"product {product} not found")
    return card_id


def _reviews_record(card_id, product):
    return cached_call("wildberries.reviews", {"card_id": card_id},
                       lambda card_id: parsers.parse_reviews(fetch.fetch_reviews(card_id, product)), ttl.REVIEWS_CACHE)


def products_reviews(product, page):
    """One page of the reviews of the product's card (every colour of the
    product shares them), newest first, with the card's rating summary."""
    card_id = _card_id(product)
    record = _reviews_record(card_id, product)
    reviews = record["reviews"]
    start = (page - 1) * REVIEWS_PAGE_SIZE
    summary = {key: value for key, value in record["summary"].items() if key != "card_id"}
    return {
        "product_id": int(product),
        "card_id": card_id,
        "link": product_link(product),
        **summary,
        "reviews": reviews[start:start + REVIEWS_PAGE_SIZE],
        "pagination": {"page": page, "items_per_page": REVIEWS_PAGE_SIZE,
                       "total_pages": math.ceil(len(reviews) / REVIEWS_PAGE_SIZE), "total_count": len(reviews)},
    }


# ---- products/questions ----------------------------------------------------------------

def _questions_page(card_id, page, product):
    def fetch_page(card_id, page):
        raw = fetch.fetch_questions(card_id, product, QUESTIONS_PAGE_SIZE, (page - 1) * QUESTIONS_PAGE_SIZE)
        return parsers.parse_questions(raw)
    return cached_call("wildberries.questions", {"card_id": card_id, "page": page}, fetch_page, ttl.QUESTIONS_CACHE)


def products_questions(product, page):
    """One page of the questions asked about the product's card, with the
    seller's answers."""
    card_id = _card_id(product)
    parsed = _questions_page(card_id, page, product)
    questions, count = parsed["questions"], parsed["count"]
    if page > 1 and not questions:
        # the site sends no total with a page past the end: the first page has it
        count = _questions_page(card_id, 1, product)["count"]
    return {
        "product_id": int(product),
        "card_id": card_id,
        "link": product_link(product),
        "questions_count": count,
        "questions": questions,
        "pagination": {"page": page, "items_per_page": QUESTIONS_PAGE_SIZE,
                       "total_pages": math.ceil(count / QUESTIONS_PAGE_SIZE), "total_count": count},
    }


# ---- categories ------------------------------------------------------------------------
_index_memo = {}
_index_lock = threading.Lock()
INDEX_TTL = 3600        # seconds the menu's lookup tables are kept in this process (the menu itself: fetch.ROUTES_TTL)


def _menu():
    return memo.expiring(_index_memo, _index_lock, "index", INDEX_TTL, lambda: parsers.menu_index(fetch.fetch_menu()))


def _category(index, category):
    node = parsers.find_category(index, category)
    if node is None:
        raise WildberriesNotFound(f"category {category} not found")
    return node


def _categories_list(category):
    index = _menu()
    if category is None:
        node, children = None, index["top"]
    else:
        node = _category(index, category)
        children = [child for child in node.get("childs") or [] if isinstance(child, dict)]
    rows = [parsers.category_row(child) for child in children]
    return {
        "category": parsers.category_row(node) if node else None,
        "path": parsers.category_path(index, node) if node else [],
        "count": len(rows),
        "results": rows,
    }


def categories_list(**data):
    return cached_call("wildberries.categories", data, _categories_list, ttl.CATEGORIES_CACHE)


def _categories_products(category, page, sort, min_price, max_price, destination, currency, **named):
    node = _category(_menu(), category)
    phrase = node.get("searchQuery")
    if not phrase:
        raise WildberriesBadRequest(f"category: '{node.get('name')}' is a promotional collection the site lists "
                                    "another way; pick a category whose is_listable is true.")
    raw = fetch.fetch_search(phrase, page=page, sort=SORTS[sort], destination=destination, currency=currency,
                             filters=_tokens(**named), min_price=min_price, max_price=max_price,
                             referer=category_link(node.get("url")), inherit_filters=False)
    return {"category": parsers.category_row(node), "sort": sort, **_market(destination, currency),
            **_listing(raw, page, MAX_SEARCH_PAGE, currency)}


def categories_products(**data):
    return cached_call("wildberries.category_products", data, _categories_products, ttl.LISTING_CACHE)


# ---- brands ----------------------------------------------------------------------------

def _brand(brand):
    return cached_call("wildberries.brand", {"brand": brand}, lambda brand: parsers.parse_brand(fetch.fetch_brand(brand)),
                       ttl.BRAND_CACHE)


def _brands_products(brand, page, sort, min_price, max_price, destination, currency, **named):
    record = _brand(brand)
    raw = fetch.fetch_brand_products(record["id"], record["slug"], page=page, sort=SORTS[sort],
                                     destination=destination, currency=currency, filters=_tokens(**named),
                                     min_price=min_price, max_price=max_price)
    return {"brand": {"id": record["id"], "name": record["name"], "link": record["link"]}, "sort": sort,
            **_market(destination, currency), **_listing(raw, page, MAX_CATALOG_PAGE, currency)}


def brands_products(**data):
    return cached_call("wildberries.brand_products", data, _brands_products, ttl.LISTING_CACHE)


# ---- sellers ---------------------------------------------------------------------------

def _seller_records(seller):
    return fetch.together([lambda: fetch.fetch_seller_legal(seller), lambda: fetch.fetch_seller_stats(seller, "RUB")])


def _sellers_details(seller):
    legal, stats = _seller_records(seller)
    if not parsers.seller_exists(legal, stats):
        raise WildberriesNotFound(f"seller {seller} not found")
    return parsers.parse_seller(seller, legal, stats)


def sellers_details(**data):
    return cached_call("wildberries.seller", data, _sellers_details, ttl.SELLER_CACHE)


def _sellers_products(seller, page, sort, min_price, max_price, destination, currency, **named):
    raw = fetch.fetch_seller_products(seller, page=page, sort=SORTS[sort], destination=destination, currency=currency,
                                      filters=_tokens(**named), min_price=min_price, max_price=max_price)
    listing = _listing(raw, page, MAX_CATALOG_PAGE, currency)
    if page == 1 and not listing["results"] and not parsers.seller_exists(*_seller_records(seller)):
        # an id the site never had answers an empty list like a seller with nothing on sale
        raise WildberriesNotFound(f"seller {seller} not found")
    return {"seller": {"id": int(seller), "link": seller_link(seller)}, "sort": sort,
            **_market(destination, currency), **listing}


def sellers_products(**data):
    return cached_call("wildberries.seller_products", data, _sellers_products, ttl.LISTING_CACHE)


# ---- search/suggestions ------------------------------------------------------------------

def _search_suggestions(query):
    return {"query": query, **parsers.parse_suggestions(fetch.fetch_suggestions(query))}


def search_suggestions(**data):
    return cached_call("wildberries.suggestions", data, _search_suggestions, ttl.SUGGESTIONS_CACHE)
