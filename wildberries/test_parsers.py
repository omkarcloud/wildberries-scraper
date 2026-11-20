"""Offline tests for the Wildberries parsers, reference resolvers and the
pure parts of the transport (query strings, answer shapes).

    python -m pytest wildberries/test_parsers.py -q

Fixtures are raw answers of www.wildberries.ru and its static hosts
captured 2026-11-19 (wildberries/fixtures/, gzipped when large): search and
list pages, live cards, static cards, a reviews file, questions pages, the
menu, brand and seller records, suggestions, and the anti-bot page of a
refused call. No network.
"""
import gzip
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wildberries import parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
MOSCOW = refs.DEFAULT_DESTINATION


def fixture(name):
    path = os.path.join(FX, name)
    if os.path.exists(path + ".gz"):
        with gzip.open(path + ".gz", "rt", encoding="utf-8") as f:
            return json.load(f)
    with open(path, encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


@pytest.fixture(scope="module")
def basket():
    table = P.parse_basket_hosts(fixture("basket_hosts.json"))
    return lambda article: P.basket_base(table, article)


def _camel_keys(value, found=None):
    found = [] if found is None else found
    if isinstance(value, dict):
        for key, item in value.items():
            if key != key.lower() or key == "url":
                found.append(key)
            _camel_keys(item, found)
    elif isinstance(value, list):
        for item in value:
            _camel_keys(item, found)
    return found


def _empty_strings(value, found=None, path=""):
    found = [] if found is None else found
    if isinstance(value, dict):
        for key, item in value.items():
            _empty_strings(item, found, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _empty_strings(item, found, f"{path}[{i}]")
    elif value == "":
        found.append(path)
    return found


# ---- refs ------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "90858341", " 090858341 ", "https://www.wildberries.ru/catalog/90858341/detail.aspx",
    "www.wildberries.ru/catalog/90858341/feedbacks?imtId=70662956",
    "https://wildberries.ru/catalog/90858341/questions",
    "https://global.wildberries.ru/catalog/90858341/detail.aspx?targetUrl=XS",
])
def test_resolve_product(value):
    assert refs.resolve_product(value) == "90858341"


@pytest.mark.parametrize("value", [
    "", "abc", "https://www.ozon.ru/product/1", "https://www.wildberries.ru/seller/843763",
    "https://www.wildberries.ru/catalog/pitanie/chay-kofe/kofe", "9085834109085834109",
])
def test_resolve_product_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_product(value)


def test_resolve_products_keeps_order_and_drops_repeats():
    got = refs.resolve_products("12801489, https://www.wildberries.ru/catalog/90858341/detail.aspx,12801489")
    assert got == ["12801489", "90858341"]
    with pytest.raises(ValueError, match="At most 100"):
        refs.resolve_products(",".join(str(1000 + i) for i in range(101)))
    with pytest.raises(ValueError):
        refs.resolve_products(" , ")


def test_resolve_seller():
    assert refs.resolve_seller("843763") == "843763"
    assert refs.resolve_seller("https://www.wildberries.ru/seller/843763?sort=rate") == "843763"
    with pytest.raises(ValueError, match="name instead of the id"):
        refs.resolve_seller("https://www.wildberries.ru/seller/rivegauche")
    with pytest.raises(ValueError):
        refs.resolve_seller("rivegauche")


def test_resolve_brand():
    assert refs.resolve_brand("14447") == "14447"
    assert refs.resolve_brand("Barista") == "barista"
    assert refs.resolve_brand("https://www.wildberries.ru/brands/barista/kofe-zernovoy") == "barista"
    with pytest.raises(ValueError):
        refs.resolve_brand("https://www.wildberries.ru/seller/843763")
    with pytest.raises(ValueError):
        refs.resolve_brand("кофе")


def test_resolve_category():
    assert refs.resolve_category("9515") == "9515"
    assert refs.resolve_category("https://www.wildberries.ru/catalog/pitanie/chay-kofe/kofe?sort=rate&page=2") == \
        "/catalog/pitanie/chay-kofe/kofe"
    assert refs.resolve_category("/catalog/pitanie/") == "/catalog/pitanie"
    for bad in ("kofe", "https://www.wildberries.ru/catalog/90858341/detail.aspx", "https://www.wildberries.ru/catalog",
                "https://www.wildberries.ru/brands/barista"):
        with pytest.raises(ValueError):
            refs.resolve_category(bad)


def test_resolve_destination():
    assert refs.resolve_destination("moscow") == MOSCOW
    assert refs.resolve_destination("Saint Petersburg") == refs.CITIES["saint_petersburg"]
    assert refs.resolve_destination("rostov-on-don") == refs.CITIES["rostov_on_don"]
    assert refs.resolve_destination("-1257786") == -1257786
    assert refs.city_of(MOSCOW) == "moscow" and refs.city_of(5) is None
    with pytest.raises(ValueError, match="Cities: moscow"):
        refs.resolve_destination("paris")


def test_resolve_filters():
    assert refs.resolve_filters("f85571:136213, f128683:418141,f128683:535608") == \
        [["f128683", "418141;535608"], ["f85571", "136213"]]
    with pytest.raises(ValueError, match="param of its own"):
        refs.resolve_filters("fbrand:14447")
    for bad in ("f128683", "f128683=418141", "x:1", "f128683:abc"):
        with pytest.raises(ValueError):
            refs.resolve_filters(bad)
    assert refs.resolve_id_list("14447, 24007,14447", "a brand") == "14447;24007"
    with pytest.raises(ValueError):
        refs.resolve_id_list("barista", "a brand")
    assert refs.resolve_filter_key("fbrand") == "fbrand" and refs.resolve_filter_key("f128683") == "f128683"
    with pytest.raises(ValueError):
        refs.resolve_filter_key("brand")


def test_static_paths():
    assert refs.card_path(90858341) == "/vol908/part90858/90858341"
    # the three cards whose reviews file answered at these paths on 2026-11-19
    assert refs.reviews_path(70662956) == "/vol130/part13062/13062956/reviews/v1/ru/ru/imt/list/date/70662956.json"
    assert refs.reviews_path(298064219).startswith("/vol100/part10064/10064219/")
    assert refs.reviews_path(773316000).startswith("/vol101/part10116/10116000/")
    assert refs.search_link("кофе в зернах").endswith("search=%D0%BA%D0%BE%D1%84%D0%B5+%D0%B2+%D0%B7%D0%B5%D1%80%D0%BD%D0%B0%D1%85")


# ---- basket hosts ------------------------------------------------------------------------

def test_basket_hosts(basket):
    table = P.parse_basket_hosts(fixture("basket_hosts.json"))
    assert len(table) == 65 and table[0] == (0, 143, "basket-01.wbbasket.ru")
    assert basket(90858341) == "https://basket-05.wbbasket.ru/vol908/part90858/90858341"
    assert basket(12801489) == "https://basket-01.wbbasket.ru/vol128/part12801/12801489"
    assert basket(2280175570) == "https://basket-58.wbbasket.ru/vol22801/part2280175/2280175570"
    assert basket(99999999999) is None and basket(None) is None
    assert P.parse_basket_hosts({}) == [] and P.parse_basket_hosts(None) == []


# ---- list pages --------------------------------------------------------------------------

def test_search_page(basket):
    page = P.parse_listing(fixture("search_kofe.json"), "RUB", basket)
    assert len(page["results"]) == 100 and page["total"] == 110858
    row = page["results"][0]
    assert row == {
        "id": 90858341,
        "name": "Кофе в зернах Pro Bar 1 кг бленд арабики и робусты",
        "link": "https://www.wildberries.ru/catalog/90858341/detail.aspx",
        "card_id": 70662956,
        "brand": {"id": 14447, "name": "BARISTA"},
        "seller": {"id": 843763, "name": "Лучшие покупки по приятным ценам",
                   "link": "https://www.wildberries.ru/seller/843763", "rating": 4.9},
        "subject_id": 5133,
        "parent_subject_id": 3109,
        "colors": [],
        "price": 1437,
        "original_price": 2268,
        "discount_percent": 37,
        "currency": "RUB",
        "delivery_fee": 0,
        "rating": 4.9,
        "reviews_count": 37161,
        "quantity": 43,
        "is_in_stock": True,
        "delivery_hours": 62,
        "image": "https://basket-05.wbbasket.ru/vol908/part90858/90858341/images/big/1.webp",
        "images_count": 14,
        "weight_kg": 1.01,
        "is_new": False,
        "review_reward_points": None,
        "sizes": [{"id": 146253476, "name": None, "original_name": None, "price": 1437, "original_price": 2268}],
    }
    assert not _camel_keys(page) and not _empty_strings(page)
    assert all(r["id"] and r["name"] and r["price"] is not None for r in page["results"])
    assert any(r["review_reward_points"] for r in page["results"]) and any(r["is_new"] for r in page["results"])
    assert P.pagination(1, page["total"], refs.MAX_SEARCH_PAGE, 100) == \
        {"page": 1, "items_per_page": 100, "total_pages": 60, "total_count": 110858}


def test_search_page_2_differs(basket):
    first = {r["id"] for r in P.parse_listing(fixture("search_kofe.json"), "RUB", basket)["results"]}
    second = {r["id"] for r in P.parse_listing(fixture("search_kofe_page_2.json"), "RUB", basket)["results"]}
    assert len(second) == 100 and len(first & second) <= 1


def test_search_row_with_sizes_and_colors(basket):
    rows = P.parse_listing(fixture("search_tshirt_sizes.json"), "RUB", basket)["results"]
    shirt = next(r for r in rows if r["id"] == 12801489)
    assert shirt["colors"] == ["черный"] and shirt["price"] == 384 and shirt["original_price"] == 960
    assert shirt["discount_percent"] == 60 and shirt["delivery_hours"] == 51
    assert len(shirt["sizes"]) == 11
    assert shirt["sizes"][0] == {"id": 39402429, "name": "48-50", "original_name": "L", "price": 384,
                                 "original_price": 960}
    assert "quantity" not in shirt["sizes"][0]          # a list page carries no stock per size


@pytest.mark.parametrize("name", ["search_no_results.json", "search_stand_in.json", "search_page_past_end.json"])
def test_search_answers_without_products(name):
    raw = fixture(name)
    assert not P.has_products(raw)
    assert P.parse_listing(raw, "RUB") == {"results": [], "total": None}


def test_list_page_past_the_end():
    assert P.parse_listing(None, "RUB") == {"results": [], "total": None}        # an empty HTTP 200 body
    past = P.parse_listing(fixture("seller_products_843763_past_end.json"), "RUB")
    assert past == {"results": [], "total": 81}
    assert P.pagination(2, 81, refs.MAX_CATALOG_PAGE, 0)["total_pages"] == 1
    assert P.pagination(101, None, refs.MAX_CATALOG_PAGE, 0) == \
        {"page": 101, "items_per_page": 100, "total_pages": None, "total_count": None, "has_next": False}
    # the site serves 60 search pages and 100 list pages, whatever the total says
    assert P.pagination(1, 545000, refs.MAX_CATALOG_PAGE, 100)["total_pages"] == 100


def test_category_brand_and_seller_pages(basket):
    category = P.parse_listing(fixture("category_9515_kofe.json"), "RUB", basket)
    assert len(category["results"]) == 100 and category["total"] == 156388
    brand = P.parse_listing(fixture("brand_products_14447.json"), "RUB", basket)
    assert brand["total"] == 208 and all(r["brand"]["id"] == 14447 for r in brand["results"])
    last = P.parse_listing(fixture("brand_products_14447_last_page.json"), "RUB", basket)
    assert len(last["results"]) == 8 and last["total"] == 208
    assert P.parse_listing(fixture("brand_products_unknown_brand.json"), "RUB") == {"results": [], "total": 0}
    seller = P.parse_listing(fixture("seller_products_843763.json"), "RUB", basket)
    assert len(seller["results"]) == 81 and all(r["seller"]["id"] == 843763 for r in seller["results"])


# ---- live cards --------------------------------------------------------------------------

def test_card(basket):
    row, = P.parse_cards(fixture("card_90858341.json"), "RUB", basket)
    assert (row["id"], row["price"], row["original_price"], row["discount_percent"]) == (90858341, 1437, 2268, 37)
    assert row["quantity"] == 43 and row["is_in_stock"] and row["delivery_hours"] == 62
    assert row["sizes"] == [{"id": 146253476, "name": None, "original_name": None, "price": 1437,
                             "original_price": 2268, "quantity": 43, "is_in_stock": True, "delivery_hours": 62,
                             "warehouses": [{"id": 302065, "quantity": 43, "delivery_hours": 62}]}]


def test_card_with_sizes(basket):
    row, = P.parse_cards(fixture("card_12801489_sizes.json"), "RUB", basket)
    assert len(row["sizes"]) == 11 and row["colors"] == ["черный"]
    small = next(s for s in row["sizes"] if s["original_name"] == "S")
    assert small["name"] == "44-46" and small["quantity"] == 1 and small["is_in_stock"]
    assert small["warehouses"] == [{"id": 5662519148, "quantity": 1, "delivery_hours": 51}]


def test_card_sparse_and_out_of_stock(basket):
    sparse, = P.parse_cards(fixture("card_2280175570_sparse.json"), "RUB", basket)
    assert sparse["brand"] is None and sparse["rating"] is None and sparse["reviews_count"] == 0
    assert sparse["price"] == 1062 and sparse["quantity"] == 5
    gone, = P.parse_cards(fixture("card_out_of_stock_90858342.json"), "RUB", basket)
    assert gone["id"] == 90858342 and gone["price"] is None and gone["original_price"] is None
    assert gone["quantity"] == 0 and gone["is_in_stock"] is False and gone["delivery_hours"] is None
    assert gone["sizes"][0]["quantity"] == 0 and gone["sizes"][0]["warehouses"] == []


def test_card_unknown_destination_looks_out_of_stock(basket):
    row, = P.parse_cards(fixture("card_90858341_unknown_destination.json"), "RUB", basket)
    assert row["price"] is None and row["is_in_stock"] is False and row["quantity"] == 0


def test_card_currency_and_delivery_fee(basket):
    usd, = P.parse_cards(fixture("card_90858341_usd.json"), "USD", basket)
    assert (usd["price"], usd["original_price"], usd["currency"]) == (17.47, 27.58, "USD")
    tashkent, = P.parse_cards(fixture("card_90858341_tashkent_delivery_fee.json"), "RUB", basket)
    assert tashkent["delivery_fee"] == 158 and tashkent["price"] == 1437


def test_cards_not_found_and_batches(basket):
    assert P.parse_cards(fixture("card_not_found.json"), "RUB", basket) == []
    assert [r["id"] for r in P.parse_cards(fixture("card_batch_found_and_not.json"), "RUB", basket)] == \
        [90858341, 2280175570]
    rows = P.parse_cards(fixture("card_batch_100.json"), "RUB", basket)
    assert len(rows) == 100 and len({r["id"] for r in rows}) == 100
    assert P.parse_cards(None, "RUB") == [] and P.parse_cards({}, "RUB") == []


# ---- the full product record ---------------------------------------------------------------

def test_product(basket):
    live = fixture("card_90858341.json")["products"][0]
    record = P.parse_product("90858341", live, fixture("static_card_90858341.json"),
                             fixture("price_history_90858341.json"), "RUB", MOSCOW, basket)
    assert record["id"] == 90858341 and record["card_id"] == 70662956 and record["is_listed"] is True
    assert record["vendor_code"] == "4813785001256_PRO_BAR_1KG"
    assert record["slug"] == "kofe-v-zernakh-pro-bar-1-kg-blend-arabiki-i-robusty"
    assert record["subject"] == {"id": 5133, "name": "Кофе зерновой", "parent_id": 3109, "parent_name": "Продукты"}
    assert record["description"].startswith("Любителям насыщенного аромата")
    assert record["package_contents"] == "1 шт; кофе зерновой 1 кг"
    assert len(record["characteristics"]) == 15
    assert record["characteristics"][0].keys() == {"group", "name", "value"}
    assert {"group": "Габариты", "name": "Длина упаковки", "value": "8 см"} in record["characteristics"]
    assert len(record["images"]) == record["images_count"] == 14
    assert record["images"][13] == "https://basket-05.wbbasket.ru/vol908/part90858/90858341/images/big/14.webp"
    assert len(record["variants"]) == 19 and record["variants"][0] == \
        {"id": 145611931, "link": "https://www.wildberries.ru/catalog/145611931/detail.aspx"}
    assert record["price"] == 1437 and record["currency"] == "RUB" and record["is_in_stock"]
    assert record["is_certificate_verified"] is True and record["sizes_table"] is None
    assert len(record["price_history"]) == 12
    assert record["price_history"][0] == {"date": "2026-07-05", "price": 1261.84, "currency": "RUB"}
    assert record["price_history"][-1]["date"] == "2026-09-20"
    assert (record["created_at"], record["updated_at"]) == ("2022-06-23T17:22:45Z", "2026-10-23T06:26:46Z")
    assert not _camel_keys(record) and not _empty_strings(record)


def test_product_with_sizes_table(basket):
    live = fixture("card_12801489_sizes.json")["products"][0]
    record = P.parse_product(12801489, live, fixture("static_card_12801489_sizes.json"), [], "RUB", MOSCOW, basket)
    assert record["composition"] == ["100% хлопок", "плотность 180г/м2", "пенье"]
    assert record["kinds"] == ["Мужской"] and record["color"] == "черный"
    assert len(record["sizes_table"]) == 11
    assert record["sizes_table"][0]["size"] == "XXS" and record["sizes_table"][0]["option_id"] == 39402435
    assert record["sizes_table"][0]["measurements"][0] == {"name": "RU", "value": "40-42"}
    assert len(record["sizes"]) == 11 and record["price_history"] == []
    assert len(record["variants"]) == 30 and len(record["images"]) == 29


def test_product_delisted_keeps_its_static_card(basket):
    record = P.parse_product(2280175570, None, fixture("static_card_2280175570_sparse.json"), [], "RUB", MOSCOW, basket)
    assert record["is_listed"] is False and record["price"] is None and record["is_in_stock"] is False
    assert record["quantity"] == 0 and record["sizes"] == []
    assert record["name"].startswith("Кофе молотый Legend of AIDA")
    assert record["seller"] == {"id": 812280, "name": None, "link": "https://www.wildberries.ru/seller/812280",
                                "rating": None}
    assert record["brand"] is None and record["composition"] == ["Кофе натуральный жареный молотый"]
    assert record["card_id"] == 4526613009 and P.card_id_of(fixture("static_card_2280175570_sparse.json")) == 4526613009


def test_product_without_a_static_card(basket):
    live = fixture("card_90858341.json")["products"][0]
    record = P.parse_product(90858341, live, None, None, "RUB", MOSCOW, basket)
    assert record["name"].startswith("Кофе в зернах") and record["description"] is None
    assert record["characteristics"] == [] and record["price_history"] == [] and record["created_at"] is None
    assert len(record["images"]) == 14


def test_price_history_junk():
    assert P.parse_price_history(None) == [] and P.parse_price_history("<html>") == []
    assert P.parse_price_history([{"dt": 0, "price": {"RUB": 100}}, {"dt": 1783209600}]) == []


# ---- reviews -----------------------------------------------------------------------------

def test_reviews():
    record = P.parse_reviews(fixture("reviews_295583596.json"))
    summary, reviews = record["summary"], record["reviews"]
    assert summary["card_id"] == 295583596 and summary["rating"] == 4.8 and summary["reviews_count"] == 531
    assert (summary["reviews_with_text_count"], summary["reviews_with_photo_count"],
            summary["reviews_with_video_count"]) == (152, 7, 4)
    assert summary["rating_distribution"][0] == {"stars": 5, "count": 473, "percent": 89}
    assert [d["stars"] for d in summary["rating_distribution"]] == [5, 4, 3, 2, 1]
    assert summary["size_fit"] is None and len(summary["variant_ratings"]) == 6
    assert len(reviews) == 153
    dates = [r["created_at"] for r in reviews]
    assert dates == sorted(dates, reverse=True) and dates[0] == "2026-11-18T13:34:08Z"
    first = reviews[0]
    assert first["id"] == "lQMuJKlcYPd0Zrsv4IWw" and first["product_id"] == 314312043 and first["rating"] == 5
    assert first["text"] == "Спасибо огромное!!! Кофе великолепный!" and first["pros"] is None
    assert first["author"] == {"id": "KuFlX9kwfhLzqiyFfTqPUGLEbdo3m3IeDJBX3HRfnD8=", "name": "Татьяна", "country": "RU",
                               "region": None, "has_photo": False}
    assert first["seller_reply"]["created_at"] == "2026-11-18T14:03:17Z" and first["seller_reply"]["updated_at"] is None
    assert first["seller_reply"]["seller_id"] == 843763
    assert first["size"] is None and first["color"] == "250 г"
    with_video = next(r for r in reviews if r["video"])
    assert with_video["video"] == {
        "link": "https://videofeedback04.wbbasket.ru/0dda7ea4-6586-4f49-a9d1-c0f7d3c595da/index.m3u8",
        "preview": "https://videofeedback04.wbbasket.ru/0dda7ea4-6586-4f49-a9d1-c0f7d3c595da/preview.webp",
        "duration_seconds": 19}
    assert sum(len(r["photos"]) for r in reviews) == 16
    assert all(p.startswith("https://feedback-0") and p.endswith("/fs.webp") for r in reviews for p in r["photos"])
    assert not _camel_keys(record) and not _empty_strings(record)


def test_reviews_of_a_card_nobody_reviewed():
    assert fixture("reviews_none.txt").strip() == "Not found"        # HTTP 404: fetch hands the parser None
    empty = P.parse_reviews(None)
    assert empty["reviews"] == [] and empty["summary"]["reviews_count"] == 0 and empty["summary"]["rating"] is None


def test_review_links_and_fit():
    assert P.review_photo_link("3/f8c93b5b-a282-41f8-ab80-524f7d5c7630") == \
        "https://feedback-03.wbbasket.ru/f8c93b5b-a282-41f8-ab80-524f7d5c7630/fs.webp"
    assert P.review_photo_link("12/abc") == "https://feedback-12.wbbasket.ru/abc/fs.webp"
    assert P.review_photo_link(None) is None and P.review_photo_link("2000000") is None
    assert P._fit({"bigger": 1, "ok": 97, "smaller": 2}) == \
        {"runs_small_percent": 2, "true_to_size_percent": 97, "runs_large_percent": 1}
    assert P._author({"country": "RU-MSK", "name": "A"}) == \
        {"id": None, "name": "A", "country": "RU", "region": "RU-MSK", "has_photo": False}


# ---- questions ---------------------------------------------------------------------------

def test_questions():
    page = P.parse_questions(fixture("questions_70662956.json"))
    assert page["count"] == 240 and len(page["questions"]) == 30
    first = page["questions"][0]
    assert first["id"] == "OrJZi6EBJxIQnrig3Bja" and first["product_id"] == 446306439
    assert first["product_name"] == "Кофе в зернах ART ПИКАССО 1 кг"
    assert first["created_at"] == "2026-10-30T05:48:04Z" and first["author"]["name"] == "Альбина"
    assert first["author"]["id"] == "x+X3mxmfMwX1acfXl08qRSx8+geiGfBMw3VnartuhEQ="
    assert any(q["tags"] == ["SELLER_QUESTION"] for q in page["questions"])
    assert first["answer"] == {"text": "Здравствуйте ! 100% арабика - 91532080", "seller_id": 843763, "likes": 0,
                               "dislikes": 0, "created_at": "2026-10-30T06:55:19Z", "updated_at": None}
    assert not _camel_keys(page) and not _empty_strings(page)


@pytest.mark.parametrize("name", ["questions_none.json", "questions_past_end.json"])
def test_questions_empty(name):
    assert P.parse_questions(fixture(name)) == {"count": 0, "questions": []}


def test_questions_bad_request_body_is_not_a_page():
    raw = fixture("questions_bad_request.json")          # `take` above 30: HTTP 400, fetch raises on it
    assert raw["ErrorCode"] == 400 and P.parse_questions(raw) == {"count": 0, "questions": []}


# ---- filters -----------------------------------------------------------------------------

def test_filters():
    parsed = P.parse_filters(fixture("search_filters_kofe.json"))
    assert parsed["total_count"] == 316160 and len(parsed["filters"]) == 32
    by_key = {f["key"]: f for f in parsed["filters"]}
    assert by_key["priceU"] == {"key": "priceU", "name": "Цена", "param": "min_price, max_price",
                                "type": "price_range", "max_selected": None, "min": 79, "max": 849999,
                                "options": [], "full_key": None}
    assert by_key["fdlvr"]["type"] == "delivery_hours" and (by_key["fdlvr"]["min"], by_key["fdlvr"]["max"]) == (7, 386)
    assert by_key["fbrand"]["param"] == "brand" and by_key["fbrand"]["full_key"] == "ffbrand"
    assert by_key["fbrand"]["options"][0] == {"id": 32069, "name": "Monarch"}
    assert by_key["xsubject"]["options"][0] == {"id": 5133, "name": "Кофе зерновой", "parent_id": 3109,
                                                "parent_name": "Продукты"}
    assert by_key["frating"]["type"] == "toggle" and by_key["frating"]["param"] == "top_rated"
    assert by_key["f128683"]["param"] == "filters" and by_key["f128683"]["type"] == "choice"
    assert by_key["f1000000103"]["type"] == "range" and by_key["f1000000103"]["param"] is None
    assert by_key["fdtype"]["type"] == "dtype" and by_key["fdtype"]["param"] is None
    assert by_key["fnds"]["param"] is None
    assert by_key["fsupplier"]["options"][0] == {"id": -100, "name": "Wildberries"}


def test_filter_full_options_and_empty():
    full = P.parse_filters(fixture("search_filters_kofe_brand_full.json"))
    assert len(full["filters"]) == 1 and full["filters"][0]["key"] == "fbrand"
    assert len(full["filters"][0]["options"]) == 1056
    assert P.parse_filters(fixture("search_filters_no_results.json")) == {"total_count": 0, "filters": []}
    assert P.parse_filters(None) == {"total_count": 0, "filters": []}


# ---- the menu ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def menu():
    return P.menu_index(fixture("menu.json"))


def test_menu_index(menu):
    assert len(menu["top"]) == 34 and len(menu["by_id"]) == 3136
    coffee = P.find_category(menu, "9515")
    assert P.find_category(menu, "/catalog/pitanie/chay-kofe/kofe") is coffee
    assert P.category_row(coffee) == {
        "id": 9515, "name": "Кофе и цикорий", "link": "https://www.wildberries.ru/catalog/pitanie/chay-kofe/kofe",
        "full_name": None, "parent_id": 9510, "children_count": 0,
        "subject_ids": [5134, 5135, 5136, 5133, 9106, 3381], "is_listable": True}
    assert coffee["searchQuery"] == "menu_redirect_subject_v2_9515 кофе и цикорий"
    assert [row["name"] for row in P.category_path(menu, coffee)] == ["Продукты", "Чай и кофе", "Кофе и цикорий"]
    food = P.category_row(P.find_category(menu, "10296"))
    assert food["children_count"] == 17 and food["full_name"] == "Продукты питания" and food["parent_id"] is None
    assert food["subject_ids"] == [] and P.category_row(P.find_category(menu, "9463"))["subject_ids"] == [515]


def test_menu_unknown_and_unlistable(menu):
    assert P.find_category(menu, "999999999") is None and P.find_category(menu, "/catalog/no-such") is None
    express = P.category_row(P.find_category(menu, "131289"))
    assert express["is_listable"] is False            # a promotional collection: no search phrase
    assert sum(1 for node in menu["by_id"].values() if not node.get("searchQuery")) == 93
    assert P.menu_index(None) == {"top": [], "by_id": {}, "by_path": {}, "parent": {}}


# ---- brands and sellers ------------------------------------------------------------------

def test_brand():
    assert P.parse_brand(fixture("brand_barista.json")) == \
        {"id": 14447, "name": "BARISTA", "link": "https://www.wildberries.ru/brands/barista", "slug": "barista"}
    assert P.parse_brand(fixture("brand_6049_apple.json"))["id"] == 6049
    assert P.parse_brand(None) == {"id": None, "name": None, "link": None, "slug": None}


def test_seller():
    legal, stats = fixture("seller_legal_843763.json"), fixture("seller_stats_843763.json")
    assert P.seller_exists(legal, stats)
    seller = P.parse_seller("843763", legal, stats)
    assert seller["id"] == 843763 and seller["name"] == "Лучшие покупки по приятным ценам"
    assert seller["legal_name"] == 'ООО "МАРКЕТ ПЛЮС"' and seller["inn"] == "6732230927"
    assert seller["ogrn"] == "1226700010734" and seller["kpp"] == "673201001" and seller["unp"] is None
    assert seller["email"] == "dm@1marketplus.ru" and seller["legal_address"].startswith("214014, Смоленская область")
    assert seller["rating"] == 4.9 and seller["reviews_count"] == 364716 and seller["items_sold"] == 1788405
    assert seller["delivery_hours"] == 12 and seller["is_premium"] is False
    assert seller["registered_at"] == "2022-06-13T09:27:50Z"
    assert not _camel_keys(seller) and not _empty_strings(seller)


def test_seller_sparse_and_unknown():
    legal, stats = fixture("seller_legal_250239754_sparse.json"), fixture("seller_stats_250239754_sparse.json")
    seller = P.parse_seller(250239754, legal, stats)
    assert seller["name"] == "суперунивермаг18" and seller["email"] is None and seller["legal_address"] is None
    assert seller["rating"] is None and seller["reviews_count"] == 0 and seller["ogrn"] is None
    # an id the site never had: no legal file (404), and a rating record of zeros with no registration date
    assert P.seller_exists(None, fixture("seller_stats_not_found.json")) is False
    assert P.seller_exists(None, stats) is True


# ---- suggestions -------------------------------------------------------------------------

def test_suggestions():
    parsed = P.parse_suggestions(fixture("suggestions_kof.json"))
    assert len(parsed["suggestions"]) == 7 and len(parsed["tags"]) == 5
    assert parsed["suggestions"][1] == {
        "text": "кофе в зернах 1 кг",
        "link": "https://www.wildberries.ru/catalog/0/search.aspx?search=%D0%BA%D0%BE%D1%84%D0%B5+%D0%B2+%D0%B7%D0%B5%D1%80%D0%BD%D0%B0%D1%85+1+%D0%BA%D0%B3"}
    assert parsed["tags"][1] == {"text": "кофе", "query": "кофе",
                                 "link": "https://www.wildberries.ru/catalog/0/search.aspx?search=%D0%BA%D0%BE%D1%84%D0%B5"}
    assert P.parse_suggestions(fixture("suggestions_none.json")) == {"suggestions": [], "tags": []}
    assert P.parse_suggestions(None) == {"suggestions": [], "tags": []}


# ---- the transport's pure parts ------------------------------------------------------------

def test_fetch_answer_shapes():
    from wildberries import fetch
    assert fetch._is_stand_in(fixture("search_stand_in.json")) is True
    assert fetch._is_stand_in(fixture("search_no_results.json")) is False
    assert fetch._is_stand_in(fixture("search_kofe.json")) is False
    assert fetch.CHALLENGE_MARKER in fixture("challenge_page.html")
    assert "404 Not Found" in fixture("static_card_not_found.html")
    assert fixture("search_page_past_end.json") == {"error": "binding request: page param malformed", "code": 500}


def test_fetch_query_strings():
    from wildberries import fetch
    common = fetch._common(MOSCOW, "RUB")
    # the seller list call as the site's own page sent it (samples/calls/p8-12, 2026-11-19)
    assert fetch._listing_query({**common, "supplier": "843763", "page": 1}, None, "popular", None, None, None) == \
        "ab_testing=false&appType=1&curr=rub&dest=1259570991&hide_vflags=4294967296&lang=ru&page=1&sort=popular&spp=30&supplier=843763"
    # the brand list call: no `page` on the first page (samples/calls/p12-17)
    assert fetch._listing_query({**common, "brand": 14447}, 1, "popular", None, None, None) == \
        "ab_testing=false&appType=1&brand=14447&curr=rub&dest=1259570991&hide_vflags=4294967296&lang=ru&sort=popular&spp=30"
    with_filters = fetch._listing_query({**common, "brand": 14447}, 3, "priceup", {"fsupplier": "843763;72728"}, 500, 1000)
    assert "&fsupplier=843763%3B72728&" in with_filters and "&page=3&priceU=50000%3B100000&sort=priceup&" in with_filters
    # the site wants both ends of a price range
    assert fetch._price_token(None, None) is None
    assert fetch._price_token(500, None) == f"50000;{refs.PRICE_CEILING_MINOR}"
    assert fetch._price_token(None, 100) == "1;10000" and fetch._price_token(0, 100.5) == "1;10050"
    assert fetch._query_id("9840461861795087996").startswith("qid9840461861795087996")
    assert len(fetch._query_id("1")) == len("qid1") + 14
