"""Raw Wildberries JSON -> clean dicts for every /wildberries/* endpoint.
Pure functions, no I/O.

Fixtures (wildberries/fixtures/, raw answers captured 2026-11-19; the large
ones are gzipped, never edited):
  search_kofe / search_kofe_page_2 / search_tshirt_sizes   one search page (100 rows)
  search_no_results / search_stand_in / search_page_past_end
  search_filters_kofe / search_filters_kofe_brand_full / search_filters_no_results
  category_9515_kofe                                      a menu category's page
  card_90858341 / card_12801489_sizes / card_2280175570_sparse / card_out_of_stock_90858342
  card_not_found / card_batch_100 / card_batch_found_and_not
  card_90858341_unknown_destination / _usd / _tashkent_delivery_fee
  static_card_90858341 / static_card_12801489_sizes / static_card_2280175570_sparse / static_card_not_found.html
  price_history_90858341
  reviews_295583596 / reviews_none.txt
  questions_70662956 / questions_none / questions_past_end / questions_bad_request
  menu, basket_hosts
  brand_barista / brand_6049_apple / brand_products_14447 (+ _last_page, _unknown_brand)
  seller_legal_843763 / seller_stats_843763 / seller_*_250239754_sparse / seller_stats_not_found
  seller_products_843763 (+ _past_end)
  suggestions_kof / suggestions_none
  challenge_page.html                                     the anti-bot page of a refused call

Units and forms the site uses:
  * prices are whole numbers of the currency's minor unit (kopecks): 143700
    is 1,437.00. `basic` is the price before the discount, `product` the
    price to pay, `logistics` a delivery fee (0 inside Russia).
  * `time1` + `time2` is the delivery time in hours: the "delivery within
    24 h" filter returns only rows whose sum is 24 or less.
  * stock quantities are capped by the site (every well-stocked size of
    unrelated products showed the same number, 43 and later 54, on
    2026-11-19): a number below the cap is real, the cap means "at least".
  * dates are ISO UTC with fractions; a never-edited answer carries
    "0001-01-01T00:00:00Z".
  * text is plain (no HTML), with line breaks.
"""
import math

from scraper_utils.dates import epoch_utc, iso_utc
from scraper_utils.text import clean, multiline
from scraper_utils.values import amount, as_dict, as_list, bool_or_none, g, num, number, rating as _rating, to_int
from wildberries.refs import (FILTER_PARAMS, PAGE_SIZE, SITE, brand_link, card_path, category_link, product_link,
                              search_link, seller_link)

ZERO_DATE = "0001-01-01"


# ---- values --------------------------------------------------------------------------

def money(minor):
    """A price in minor units (kopecks) -> an amount; None for a missing one."""
    value = num(minor)
    return None if value is None else amount(value / 100)


def _date(value):
    """An ISO time -> 'YYYY-MM-DDTHH:MM:SSZ'; the site's zero date -> None."""
    text = iso_utc(value)
    return None if not text or text.startswith(ZERO_DATE) else text


def _id(value):
    """A positive id, else None (the site writes 0 for "none")."""
    number = to_int(value)
    return number if number and number > 0 else None


def _discount(price, original):
    if price is None or not original or original <= price:
        return None
    return int(round((1 - price / original) * 100))


# ---- basket hosts --------------------------------------------------------------------

def parse_basket_hosts(raw):
    """The site's host table -> [(first volume, last volume, host)], or []
    for an unknown shape."""
    table = []
    for row in as_list(g(raw, "origin", "mediabasket_route_map", 0, "hosts", default=None)):
        first, last, host = to_int(g(row, "vol_range_from")), to_int(g(row, "vol_range_to")), g(row, "host")
        if first is not None and last is not None and host:
            table.append((first, last, host))
    return table


def basket_base(table, article):
    """https://<host>/vol../part../<article> for an article, or None when no
    host of the table holds its volume."""
    article = to_int(article)
    if article is None:
        return None
    volume = article // 100000
    for first, last, host in table:
        if first <= volume <= last:
            return f"https://{host}{card_path(article)}"
    return None


def image_links(base, count):
    """The product's photos, largest size, in the site's order."""
    count = to_int(count) or 0
    return [f"{base}/images/big/{i}.webp" for i in range(1, count + 1)] if base else []


# ---- products: list rows and live cards ------------------------------------------------

def _size_prices(size):
    price = as_dict(g(size, "price", default=None))
    return money(price.get("product")), money(price.get("basic")), money(price.get("logistics"))


def _hours(row):
    first, second = to_int(g(row, "time1")), to_int(g(row, "time2"))
    return None if first is None and second is None else (first or 0) + (second or 0)


def _size(size, detailed):
    price, original, _fee = _size_prices(size)
    name, original_name = clean(g(size, "name")), clean(g(size, "origName"))
    row = {
        "id": _id(g(size, "optionId")),
        "name": name,
        # "0" is what the site writes for a product sold in one size
        "original_name": None if original_name == "0" else original_name,
        "price": price,
        "original_price": original,
    }
    if detailed:
        warehouses = [{"id": _id(g(stock, "wh")), "quantity": to_int(g(stock, "qty")), "delivery_hours": _hours(stock)}
                      for stock in as_list(g(size, "stocks", default=None)) if isinstance(stock, dict)]
        quantity = sum(w["quantity"] or 0 for w in warehouses)
        row.update({
            "quantity": quantity,
            "is_in_stock": quantity > 0,
            "delivery_hours": _hours(size),
            "warehouses": warehouses,
        })
    return row


def parse_product_row(raw, currency, basket=None, detailed=False):
    """One product of a list page or of the live card call. `detailed` adds
    the stock of every size and warehouse (the card call carries it, a list
    page does not). `basket(article)` gives the product's file base, for the
    photo link."""
    article = _id(g(raw, "id"))
    sizes = [_size(size, detailed) for size in as_list(g(raw, "sizes", default=None)) if isinstance(size, dict)]
    priced = [(_size_prices(size), size) for size in as_list(g(raw, "sizes", default=None)) if isinstance(size, dict)]
    priced = [(prices, size) for prices, size in priced if prices[0] is not None]
    (price, original, fee), _ = min(priced, key=lambda item: item[0][0]) if priced else ((None, None, None), None)
    quantity = to_int(g(raw, "totalQuantity"))
    brand_id, brand_name = _id(g(raw, "brandId")), clean(g(raw, "brand"))
    seller_id = to_int(g(raw, "supplierId"))
    base = basket(article) if basket and article else None
    images_count = to_int(g(raw, "pics")) or 0
    return {
        "id": article,
        "name": clean(g(raw, "name")),
        "link": product_link(article) if article else None,
        "card_id": _id(g(raw, "root")),
        "brand": {"id": brand_id, "name": brand_name} if (brand_id or brand_name) else None,
        "seller": {
            "id": seller_id,
            "name": clean(g(raw, "supplier")),
            "link": seller_link(seller_id) if seller_id and seller_id > 0 else None,
            "rating": _rating(g(raw, "supplierRating")),
        } if seller_id is not None else None,
        "subject_id": _id(g(raw, "subjectId")),
        "parent_subject_id": _id(g(raw, "subjectParentId")),
        "colors": [name for name in (clean(g(color, "name")) for color in as_list(g(raw, "colors", default=None))) if name],
        "price": price,
        "original_price": original,
        "discount_percent": _discount(price, original),
        "currency": currency,
        "delivery_fee": fee,
        "rating": _rating(g(raw, "reviewRating")),
        "reviews_count": to_int(g(raw, "feedbacks")) or 0,
        "quantity": quantity,
        "is_in_stock": bool(quantity) and price is not None,
        "delivery_hours": _hours(raw) if price is not None else None,
        "image": image_links(base, 1)[0] if base and images_count else None,
        "images_count": images_count,
        "weight_kg": num(g(raw, "weight")) or None,
        "is_new": bool(g(raw, "isNew", default=False)),
        "review_reward_points": to_int(g(raw, "feedbackPoints")),
        "sizes": sizes,
    }


def has_products(raw):
    """True when a list answer carries a `products` list. A search with no
    result has no such key; a seller / brand page past the end is None."""
    return isinstance(raw, dict) and isinstance(raw.get("products"), list)


def parse_listing(raw, currency, basket=None):
    """A search / category / seller / brand page -> {"results", "total"}."""
    if not has_products(raw):
        return {"results": [], "total": to_int(g(raw, "total")) if isinstance(raw, dict) else None}
    results = [parse_product_row(row, currency, basket) for row in raw["products"] if isinstance(row, dict)]
    return {"results": [row for row in results if row["id"]], "total": to_int(raw.get("total"))}


def pagination(page, total, max_page, count):
    """The `pagination` block of a list page. The site serves `max_page`
    pages at most, whatever the total says."""
    if total is None:
        return {"page": page, "items_per_page": PAGE_SIZE, "total_pages": None, "total_count": None,
                "has_next": count >= PAGE_SIZE and page < max_page}
    return {"page": page, "items_per_page": PAGE_SIZE,
            "total_pages": min(max_page, math.ceil(total / PAGE_SIZE)), "total_count": total}


def parse_cards(raw, currency, basket=None):
    """The live card call -> a list of detailed product rows (only the
    articles the site still lists come back)."""
    rows = [parse_product_row(row, currency, basket, detailed=True)
            for row in as_list(g(raw, "products", default=None)) if isinstance(row, dict)]
    return [row for row in rows if row["id"]]


# ---- products: the static card and the full record ---------------------------------------

def card_id_of(static):
    """The card id (reviews and questions belong to it) of a static card."""
    return _id(g(static, "imt_id"))


def _characteristics(static):
    rows = []
    groups = as_list(g(static, "grouped_options", default=None))
    for group in groups:
        for option in as_list(g(group, "options", default=None)):
            name, value = clean(g(option, "name")), clean(g(option, "value"))
            if name:
                rows.append({"group": clean(g(group, "group_name")), "name": name, "value": value})
    if not rows:
        for option in as_list(g(static, "options", default=None)):
            name, value = clean(g(option, "name")), clean(g(option, "value"))
            if name:
                rows.append({"group": None, "name": name, "value": value})
    return rows


def _sizes_table(static):
    table = as_dict(g(static, "sizes_table", default=None))
    columns = [clean(c) for c in as_list(table.get("details_props"))]
    rows = []
    for row in as_list(table.get("values")):
        values = as_list(g(row, "details", default=None))
        rows.append({
            "size": clean(g(row, "tech_size")),
            "option_id": _id(g(row, "chrt_id")),
            "measurements": [{"name": name, "value": clean(values[i]) if i < len(values) else None}
                             for i, name in enumerate(columns) if name],
        })
    return rows or None


def parse_price_history(raw):
    """Weekly price points -> [{date, price, currency}], oldest first. The
    file holds roubles only."""
    points = []
    for point in as_list(raw):
        when = epoch_utc(g(point, "dt"))
        for code, minor in as_dict(g(point, "price", default=None)).items():
            if when and money(minor) is not None:
                points.append({"date": when[:10], "price": money(minor), "currency": str(code).upper()})
    return sorted(points, key=lambda p: p["date"])


def parse_product(article, live, static, history, currency, destination, basket=None):
    """The full product record: `live` is the product's row of the live card
    call (None when the site no longer lists the article), `static` its
    static card (None when there is none), `history` the raw price points."""
    article = int(article)
    row = parse_product_row(live, currency, basket, detailed=True) if live else None
    static = as_dict(static)
    base = basket(article) if basket else None
    images_count = (row or {}).get("images_count") or to_int(g(static, "media", "photo_count")) or 0
    seller_id = (row or {}).get("seller", {}).get("id") if row and row.get("seller") else to_int(g(static, "selling", "supplier_id"))
    brand = (row or {}).get("brand")
    if not brand and clean(g(static, "selling", "brand_name")):
        brand = {"id": None, "name": clean(g(static, "selling", "brand_name"))}
    seller = (row or {}).get("seller")
    if not seller and seller_id is not None:
        seller = {"id": seller_id, "name": None, "link": seller_link(seller_id) if seller_id > 0 else None, "rating": None}
    subject_id = (row or {}).get("subject_id") or _id(g(static, "data", "subject_id"))
    parent_subject_id = (row or {}).get("parent_subject_id") or _id(g(static, "data", "subject_root_id"))
    variants = [_id(g(v, "nm_id")) for v in as_list(g(static, "full_colors", default=None))] or \
               [_id(v) for v in as_list(g(static, "colors", default=None))]
    return {
        "id": article,
        "name": (row or {}).get("name") or clean(g(static, "imt_name")),
        "link": product_link(article),
        "card_id": (row or {}).get("card_id") or card_id_of(static),
        "is_listed": row is not None,
        "slug": clean(g(static, "slug")),
        "vendor_code": clean(g(static, "vendor_code")),
        "brand": brand,
        "seller": seller,
        "subject": {
            "id": subject_id,
            "name": clean(g(static, "subj_name")),
            "parent_id": parent_subject_id,
            "parent_name": clean(g(static, "subj_root_name")),
        },
        "description": multiline(g(static, "description")),
        "package_contents": clean(g(static, "contents")),
        "composition": [name for name in (clean(g(c, "name")) for c in as_list(g(static, "compositions", default=None))) if name],
        "kinds": [name for name in (clean(k) for k in as_list(g(static, "kinds", default=None))) if name],
        "color": clean(g(static, "nm_colors_names")) or (", ".join(row["colors"]) if row and row["colors"] else None),
        "characteristics": _characteristics(static),
        "sizes_table": _sizes_table(static),
        "images": image_links(base, images_count),
        "images_count": images_count,
        "price": (row or {}).get("price"),
        "original_price": (row or {}).get("original_price"),
        "discount_percent": (row or {}).get("discount_percent"),
        "currency": currency,
        "delivery_fee": (row or {}).get("delivery_fee"),
        "destination": destination,
        "rating": (row or {}).get("rating"),
        "reviews_count": (row or {}).get("reviews_count"),
        "quantity": (row or {}).get("quantity") if row else 0,
        "is_in_stock": bool(row and row["is_in_stock"]),
        "delivery_hours": (row or {}).get("delivery_hours"),
        "weight_kg": (row or {}).get("weight_kg"),
        "is_new": bool(row and row["is_new"]),
        "review_reward_points": (row or {}).get("review_reward_points"),
        "is_certificate_verified": bool_or_none(g(static, "certificate", "verified")),
        "sizes": (row or {}).get("sizes") or [],
        "variants": [{"id": v, "link": product_link(v)} for v in variants if v],
        "price_history": parse_price_history(history),
        "created_at": _date(g(static, "create_date")),
        "updated_at": _date(g(static, "update_date")),
    }


# ---- reviews -------------------------------------------------------------------------

def _distribution(counts, percents):
    counts, percents = as_dict(counts), as_dict(percents)
    return [{"stars": stars, "count": to_int(counts.get(str(stars))) or 0, "percent": to_int(percents.get(str(stars)))}
            for stars in (5, 4, 3, 2, 1)]


def _fit(raw):
    """{"bigger": 1, "ok": 97, "smaller": 2} -> the same three shares, or None."""
    raw = as_dict(raw)
    if not raw:
        return None
    return {"runs_small_percent": to_int(raw.get("smaller")), "true_to_size_percent": to_int(raw.get("ok")),
            "runs_large_percent": to_int(raw.get("bigger"))}


def review_photo_link(key):
    """A photo key "3/<uuid>" -> its full-size link on the site's photo host."""
    shard, _, name = str(key or "").partition("/")
    if not (shard.isdigit() and name):
        return None
    return f"https://feedback-{int(shard):02d}.wbbasket.ru/{name}/fs.webp"


def _review_video(video):
    shard, _, name = str(g(video, "id", default="") or "").partition("/")
    if not (shard.isdigit() and name):
        return None
    base = f"https://videofeedback{int(shard):02d}.wbbasket.ru/{name}"
    return {"link": f"{base}/index.m3u8", "preview": f"{base}/preview.webp",
            "duration_seconds": to_int(g(video, "durationSec"))}


def _author(details, author_id=None):
    code = clean(g(details, "country"))
    return {
        "id": clean(author_id),             # the site's own anonymous id of the shopper, the same on every review
        "name": clean(g(details, "name")),
        "country": code[:2].upper() if code else None,
        "region": code.upper() if code and len(code) > 2 else None,
        "has_photo": bool(g(details, "hasPhoto", default=False)),
    }


def _review(raw):
    answer = as_dict(g(raw, "answer", default=None))
    size = clean(g(raw, "size"))
    excluded = as_dict(g(raw, "excludedFromRating", default=None))
    article = _id(g(raw, "nmId"))
    return {
        "id": clean(g(raw, "id")),
        "product_id": article,
        "product_link": product_link(article) if article else None,
        "rating": to_int(g(raw, "productValuation")),
        "text": multiline(g(raw, "text")),
        "pros": multiline(g(raw, "pros")),
        "cons": multiline(g(raw, "cons")),
        "color": clean(g(raw, "color")),
        "size": None if size == "0" else size,
        "size_fit": clean(g(raw, "matchingSize")),
        "tags": [tag for tag in (clean(t) for t in as_list(g(raw, "bables", default=None))) if tag],
        "photos": [link for link in (review_photo_link(g(p, "key")) for p in as_list(g(raw, "photos", default=None))) if link],
        "video": _review_video(g(raw, "video", default=None)),
        "likes": to_int(g(raw, "votes", "pluses")) or 0,
        "dislikes": to_int(g(raw, "votes", "minuses")) or 0,
        "author": _author(g(raw, "userDetails", default=None), g(raw, "globalUserId")),
        "seller_reply": {
            "text": multiline(answer.get("text")),
            "seller_id": _id(answer.get("supplierId")),
            "created_at": _date(answer.get("createDate")),
            "updated_at": _date(answer.get("lastUpdate")),
        } if multiline(answer.get("text")) else None,
        "is_excluded_from_rating": bool(excluded.get("isExcluded")),
        "exclusion_reasons": [r for r in (clean(x) for x in as_list(excluded.get("reasons"))) if r],
        "parent_review_id": clean(g(raw, "parentFeedbackId")),
        "child_review_id": clean(g(raw, "childFeedbackId")),
        "created_at": _date(g(raw, "createdDate")),
        "updated_at": _date(g(raw, "updatedDate")),
    }


def parse_reviews(raw):
    """A card's reviews file -> {"summary": {...}, "reviews": [...]}, the
    reviews newest first. None (a card nobody reviewed) -> an empty record."""
    raw = as_dict(raw)
    reviews = [_review(row) for row in as_list(raw.get("feedbacks")) if isinstance(row, dict)]
    reviews.sort(key=lambda r: r["created_at"] or "", reverse=True)
    summary = {
        "card_id": _id(raw.get("imtId")),
        "rating": _rating(raw.get("valuation")),
        "reviews_count": to_int(raw.get("feedbackCount")) or 0,
        "reviews_with_text_count": to_int(raw.get("feedbackCountWithText")) or 0,
        "reviews_with_photo_count": to_int(raw.get("feedbackCountWithPhoto")) or 0,
        "reviews_with_video_count": to_int(raw.get("feedbackCountWithVideo")) or 0,
        "rating_distribution": _distribution(raw.get("valuationDistribution"), raw.get("valuationDistributionPercent"))
        if raw else [],
        "size_fit": _fit(raw.get("matchingSizePercentages")),
        "variant_ratings": [{
            "product_id": _id(g(row, "nm")),
            "rating_distribution": _distribution(g(row, "valuationDistribution", default=None),
                                                 g(row, "valuationDistributionPercent", default=None)),
        } for row in as_list(raw.get("nmValuationDistribution")) if _id(g(row, "nm"))],
    }
    return {"summary": summary, "reviews": reviews}


# ---- questions -----------------------------------------------------------------------

def _question(raw):
    answer = as_dict(g(raw, "answer", default=None))
    article = _id(g(raw, "nmId"))
    return {
        "id": clean(g(raw, "id")),
        "product_id": article,
        "product_name": clean(g(raw, "productDetails", "productName")),
        "product_link": product_link(article) if article else None,
        "vendor_code": clean(g(raw, "productDetails", "supplierArticle")),
        "text": multiline(g(raw, "text")),
        "author": _author(g(raw, "wbUserDetails", default=None), g(raw, "globalUserId")),
        "tags": [tag for tag in (clean(t) for t in as_list(g(raw, "tags", default=None))) if tag],
        "answer": {
            "text": multiline(answer.get("text")),
            "seller_id": _id(answer.get("supplierId")),
            "likes": to_int(answer.get("plusesCount")) or 0,
            "dislikes": to_int(answer.get("minusesCount")) or 0,
            "created_at": _date(answer.get("createDate")),
            "updated_at": _date(answer.get("lastUpdate")),
        } if multiline(answer.get("text")) else None,
        "created_at": _date(g(raw, "createdDate")),
    }


def parse_questions(raw):
    """One questions page -> {"count", "questions"}. `count` is the card's
    total; the site sends 0 with a page past the end."""
    raw = as_dict(raw)
    return {"count": to_int(raw.get("count")) or 0,
            "questions": [_question(row) for row in as_list(raw.get("questions")) if isinstance(row, dict)]}


# ---- filters -------------------------------------------------------------------------

def _filter_kind(raw):
    kind = g(raw, "type")
    if g(raw, "key") == "priceU":
        return "price_range"
    if g(raw, "key") == "fdlvr":
        return "delivery_hours"
    if kind == "toggle":
        return "toggle"
    if kind == "range":
        return "range"
    if kind:
        return clean(kind)          # "dtype": the delivery methods, a form of its own
    return "choice"


def _filter(raw):
    key = clean(g(raw, "key"))
    options = [{"id": to_int(g(o, "id")), "name": clean(g(o, "name")), "parent_id": _id(g(o, "parentId")),
                "parent_name": clean(g(o, "parentName"))}
               for o in as_list(g(raw, "items", default=None)) if isinstance(o, dict) and to_int(g(o, "id")) is not None]
    for option in options:
        if option["parent_id"] is None and option["parent_name"] is None:
            del option["parent_id"], option["parent_name"]
    kind = _filter_kind(raw)
    low, high = (money(g(raw, "minPriceU")), money(g(raw, "maxPriceU"))) if kind == "price_range" else \
                (to_int(g(raw, "minTime")), to_int(g(raw, "maxTime"))) if kind == "delivery_hours" else \
                (num(g(raw, "from")), num(g(raw, "to")))
    return {
        "key": key,
        "name": clean(g(raw, "name")),
        # the request param that sets this filter: its own one, or `filters` (key:id pairs) for a list of
        # options; None for a filter this API does not set
        "param": FILTER_PARAMS.get(key) or ("filters" if kind == "choice" else None),
        "type": kind,
        "max_selected": to_int(g(raw, "maxselect")),
        "min": low,
        "max": high,
        "options": options,
        "full_key": clean(g(raw, "fullKey")),
    }


def parse_filters(raw):
    """A search's filters answer -> {"total_count", "filters"}."""
    filters = [_filter(row) for row in as_list(g(raw, "data", "filters", default=None)) if isinstance(row, dict)]
    return {"total_count": to_int(g(raw, "data", "total")) or 0, "filters": [f for f in filters if f["key"]]}


# ---- the menu ------------------------------------------------------------------------

def menu_index(raw):
    """The menu tree -> {"top": [nodes], "by_id": {id: node}, "by_path":
    {page path: node}, "parent": {id: parent node}}. Where two nodes share a
    page path the first one of the tree keeps it."""
    index = {"top": [n for n in as_list(raw) if isinstance(n, dict)], "by_id": {}, "by_path": {}, "parent": {}}

    def walk(node, parent):
        node_id = to_int(node.get("id"))
        if node_id is None:
            return
        index["by_id"].setdefault(node_id, node)
        if parent is not None:
            index["parent"].setdefault(node_id, parent)
        path = (node.get("url") or "").rstrip("/")
        if path:
            index["by_path"].setdefault(path, node)
        for child in as_list(node.get("childs")):
            if isinstance(child, dict):
                walk(child, node)

    for node in index["top"]:
        walk(node, None)
    return index


def find_category(index, ref):
    """The menu node for a resolved `category` (digits = its id, else its
    page path), or None."""
    ref = str(ref)
    if ref.isdigit():
        return index["by_id"].get(int(ref))
    return index["by_path"].get(ref.rstrip("/"))


def _subject_ids(node):
    """The product types a menu node covers ("subject=5134;5135" in its own
    query), as ids the `subject` filter takes."""
    for key in ("rawQuery", "query"):
        for part in str(node.get(key) or "").split("&"):
            name, _, value = part.partition("=")
            if name == "subject" and value:
                return [int(v) for v in value.split(";") if v.isdigit()]
    return []


def category_row(node):
    """One menu node as a row. `is_listable` is False for a promotional
    collection, which carries no search phrase to list its products by."""
    children = [c for c in as_list(node.get("childs")) if isinstance(c, dict)]
    return {
        "id": to_int(node.get("id")),
        "name": clean(node.get("name")),
        "link": category_link(node.get("url")),
        "full_name": clean(node.get("seo")),
        "parent_id": _id(node.get("parent")),
        "children_count": len(children),
        "subject_ids": _subject_ids(node),
        "is_listable": bool(node.get("searchQuery")),
    }


def category_path(index, node):
    """The chain of rows from the top of the menu down to `node`."""
    chain = []
    while node is not None:
        chain.append(category_row(node))
        node = index["parent"].get(to_int(node.get("id")))
    return list(reversed(chain))


# ---- brands and sellers ----------------------------------------------------------------

def parse_brand(raw):
    """A brand's own record -> {id, name, link}."""
    slug = clean(g(raw, "url")) or clean(g(raw, "wbBrandsUrl"))
    return {"id": _id(g(raw, "id")), "name": clean(g(raw, "name")), "link": brand_link(slug), "slug": slug}


def seller_exists(legal, stats):
    """False for an id the site never had: no legal file, and a rating
    record with no registration date."""
    return bool(legal) or bool(g(stats, "registrationDate"))


def parse_seller(seller_id, legal, stats):
    """A seller's legal record (may be None) and rating record -> one row."""
    legal, stats = as_dict(legal), as_dict(stats)
    seller_id = int(seller_id)
    trademark = clean(legal.get("trademark"))
    return {
        "id": seller_id,
        "name": trademark or clean(legal.get("supplierName")),
        "link": seller_link(seller_id),
        "trademark": trademark,
        "legal_name": clean(legal.get("supplierName")),
        "full_legal_name": clean(legal.get("supplierFullName")),
        "email": clean(legal.get("email")),
        "legal_address": clean(legal.get("legalAddress")),
        "inn": clean(legal.get("inn")),
        "ogrn": clean(legal.get("ogrn")),
        "ogrnip": clean(legal.get("ogrnip")),
        "kpp": clean(legal.get("kpp")),
        "unp": clean(legal.get("unp")),
        "bin": clean(legal.get("bin")),
        "unn": clean(legal.get("unn")),
        "taxpayer_code": clean(legal.get("taxpayerCode")),
        "rating": _rating(stats.get("valuationToHundredths")) or _rating(stats.get("valuation")),
        "reviews_count": to_int(stats.get("feedbacksCount")) or 0,
        "items_sold": to_int(stats.get("saleItemQuantity")) or 0,
        "delivery_hours": number(stats.get("deliveryDuration")),
        "is_premium": bool(stats.get("isPremium")),
        "loyalty_program_level": to_int(stats.get("supplierLoyaltyProgramLevel")),
        "has_logo": bool(stats.get("hasLogo")),
        "is_rating_hidden": bool(stats.get("ratingIsInvisible")),
        "is_deleted": bool(stats.get("isDeleted")),
        "is_deactivated": bool(stats.get("deactivated")),
        "registered_at": _date(stats.get("registrationDate")),
        "updated_at": _date(stats.get("updateDate")),
    }


# ---- suggestions -----------------------------------------------------------------------

def parse_suggestions(raw):
    """The search box's answer -> {"suggestions": [...], "tags": [...]}:
    whole phrases to search for, and words that narrow what was typed."""
    suggestions, tags = [], []
    for block in as_list(g(raw, "bl", default=None)):
        kind = g(block, "t")
        for item in as_list(g(block, "el", default=None)):
            text = clean(g(item, "txt"))
            if not text:
                continue
            if kind == "tag":
                phrase = clean(g(item, "in")) or text
                tags.append({"text": text, "query": phrase, "link": search_link(phrase)})
            else:
                link = g(item, "q")
                suggestions.append({"text": text,
                                    "link": SITE + link if isinstance(link, str) and link.startswith("/") else search_link(text)})
    return {"suggestions": suggestions, "tags": tags}
