"""The 12 Wildberries endpoints. Every path is served with and without the
`/wildberries` prefix, so code written against the hosted API runs unchanged
against this server.

Params are validated by the same marshmallow schemas the hosted API uses
(wildberries/schemas.py): the same defaults, allowed values and error messages,
and an unknown param is refused. A list endpoint pages with `page` and
answers count / per_page / current_page / total_pages / next / previous
first, like the hosted API.
"""
from urllib.parse import urlencode

from bottle import request, response, route

import fastjson
from schema_fields import load_query
from scraper_errors import BadRequest, Blocked, NotFound, Unavailable, UpstreamError
from wildberries import api, schemas

SITE = "wildberries"
PREFIX = "/wildberries"
# Params only the hosted API acts on. They are accepted and ignored here, so a call copied from the hosted
# API's playground runs unchanged (the answer simply has no `website_contacts`).
HOSTED_ONLY = {"website_contacts_crawl_mode"}


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return fastjson.dumps(data)      # compact, non-ASCII as it is


def query_dict():
    """The request query as unicode strings (bottle 0.12's .get() hands back
    latin-1 decoded bytes, so a UTF-8 "Amélie" would arrive garbled)."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _page_link(params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    return f"{request.urlparts.scheme}://{request.urlparts.netloc}{request.path}?{urlencode(query, doseq=True)}"


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def paginate(result, params):
    """Lift the scraper's `pagination` block into the flat shape the hosted
    API answers: count / per_page / current_page / total_pages / next /
    previous first, then the data. A listing whose total the site does not
    publish says `has_next` instead: total_pages is null then and the next
    link follows `has_next`."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)   # the page's own count; `count` is the total
    page = _as_int(pagination.get("page")) or _as_int(params.get("page")) or 1
    if "has_next" in pagination:
        has_next = bool(pagination["has_next"])
        total_pages = pagination.get("total_pages")
        if total_pages is not None:
            total_pages = _as_int(total_pages, None)
    else:
        total_pages = max(_as_int(pagination.get("total_pages")), 0)
        has_next = page < total_pages
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(params, page + 1 if has_next else None),
        "previous": _page_link(params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def _error_body(message, exc):
    """{"error": message} plus the exception's machine-readable `reason` and
    its details when the module sets them."""
    body = {"error": message}
    reason = getattr(exc, "reason", None)
    if reason:
        body["reason"] = reason
        for key, value in (getattr(exc, "details", None) or {}).items():
            body.setdefault(key, value)
    return body


def call(path, schema, impl, paginated=False):
    """Validate the query with the endpoint's schema, run it, and answer every
    failure the way the hosted API does: bad params 400, a record that does
    not exist 404, a pause 503 with Retry-After, the site blocking or failing
    502, anything else 500."""
    label = f"{SITE} {path.strip('/')}"
    params = {key: value for key, value in query_dict().items() if key not in HOSTED_ONLY}
    data, error = load_query(schema, params)
    if error:
        return json_response(error, 400)
    if getattr(schema, "CACHE_REFRESH", False):
        data.pop("refresh", None)   # the hosted response cache's switch; nothing is kept between calls here
    try:
        result = impl(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response(_error_body(f"{SITE} rejected the request: {e}", e), 400)
    except NotFound as e:
        return json_response(_error_body(str(e) or "not found", e), 404)
    except Unavailable as e:
        response.set_header("Retry-After", str(e.retry_after))
        return json_response({"error": str(e)}, 503)
    except Blocked as e:
        print(f"{SITE} {path}: upstream failure: {type(e).__name__}: {e}")
        return json_response({"error": f"{SITE} blocked the request, retry later: {e}"}, 502)
    except UpstreamError as e:
        print(f"{SITE} {path}: upstream failure: {type(e).__name__}: {e}")
        return json_response({"error": f"{label} failed: {e}"}, 502)
    except Exception as e:
        print(f"{SITE} {path}: {type(e).__name__}: {e}")
        return json_response({"error": f"{label} failed: {type(e).__name__}: {e}"}, 500)
    return json_response(paginate(result, params) if paginated else result)


# (public path, request schema, endpoint function, pages with `page`), in the order of the docs.
ENDPOINTS = [
    ("/products/details", schemas.ProductSchema, api.products_details, False),
    ("/products/reviews", schemas.ProductReviewsSchema, api.products_reviews, True),
    ("/products/questions", schemas.ProductQuestionsSchema, api.products_questions, True),
    ("/products/batch", schemas.ProductsBatchSchema, api.products_batch, False),
    ("/search/suggestions", schemas.SuggestionsSchema, api.search_suggestions, False),
    ("/products/search", schemas.ProductsSearchSchema, api.products_search, True),
    ("/products/filters", schemas.ProductsFiltersSchema, api.products_filters, False),
    ("/categories/list", schemas.CategoriesListSchema, api.categories_list, False),
    ("/categories/products", schemas.CategoryProductsSchema, api.categories_products, True),
    ("/brands/products", schemas.BrandProductsSchema, api.brands_products, True),
    ("/sellers/details", schemas.SellerSchema, api.sellers_details, False),
    ("/sellers/products", schemas.SellerProductsSchema, api.sellers_products, True),
]


def mount(path, schema, impl, paginated):
    """Serve one endpoint at /path and at /wildberries/path."""
    def handler():
        return call(path, schema, impl, paginated)
    handler.__name__ = "wildberries_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route(PREFIX + path, method="GET")(handler)


for _path, _schema, _impl, _paginated in ENDPOINTS:
    mount(_path, _schema, _impl, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [path for path, *_ in ENDPOINTS]})
