"""Offline tests for the /wildberries/* request schemas.

    python -m pytest wildberries/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wildberries import refs, schemas  # noqa: E402

MOSCOW = refs.DEFAULT_DESTINATION
LIST_DEFAULTS = {"sort": "popular", "min_price": None, "max_price": None, "subject": None, "top_rated": None,
                 "max_delivery_hours": None, "original": None, "premium_seller": None, "express": None,
                 "has_video": None, "destination": MOSCOW, "currency": "RUB"}


def _errors(schema, query):
    with pytest.raises(ValidationError) as caught:
        schema().load(query)
    return caught.value.messages


# ---- products/search ---------------------------------------------------------------------

def test_search_defaults():
    assert schemas.ProductsSearchSchema().load({"query": "  кофе   в зернах "}) == {
        "query": "кофе в зернах", "page": 1, "brand": None, "seller": None, "filters": None, **LIST_DEFAULTS}


def test_search_every_param():
    loaded = schemas.ProductsSearchSchema().load({
        "query": "кофе", "page": "60", "sort": "PRICE_ASC", "min_price": "500", "max_price": "1000.5",
        "brand": "14447, 24007", "seller": "843763", "subject": "5133,5135", "top_rated": "true",
        "max_delivery_hours": "24", "original": "1", "premium_seller": "yes", "express": "true", "has_video": "true",
        "filters": "f128683:418141,f85571:136213", "destination": "Novosibirsk", "currency": "kzt"})
    assert loaded == {
        "query": "кофе", "page": 60, "sort": "price_asc", "min_price": 500.0, "max_price": 1000.5,
        "brand": "14447;24007", "seller": "843763", "subject": "5133;5135", "top_rated": True,
        "max_delivery_hours": 24, "original": True, "premium_seller": True, "express": True, "has_video": True,
        "filters": [["f128683", "418141"], ["f85571", "136213"]],
        "destination": refs.CITIES["novosibirsk"], "currency": "KZT"}


@pytest.mark.parametrize("query, field", [
    ({}, "query"),
    ({"query": ""}, "query"),
    ({"query": "кофе", "page": "61"}, "page"),
    ({"query": "кофе", "page": "0"}, "page"),
    ({"query": "кофе", "sort": "benefit"}, "sort"),             # the site would silently sort by popularity
    ({"query": "кофе", "sort": "fastest_delivery"}, "sort"),
    ({"query": "кофе", "currency": "EUR"}, "currency"),         # the site does not price in it
    ({"query": "кофе", "destination": "paris"}, "destination"),
    ({"query": "кофе", "min_price": "-1"}, "min_price"),
    ({"query": "кофе", "min_price": "10", "max_price": "5"}, "max_price"),
    ({"query": "кофе", "brand": "barista"}, "brand"),
    ({"query": "кофе", "seller": "843763,x"}, "seller"),
    ({"query": "кофе", "subject": "coffee"}, "subject"),
    ({"query": "кофе", "top_rated": "false"}, "top_rated"),     # "off" is not a filter: leave it out
    ({"query": "кофе", "original": "maybe"}, "original"),
    ({"query": "кофе", "max_delivery_hours": "0"}, "max_delivery_hours"),
    ({"query": "кофе", "filters": "fbrand:14447"}, "filters"),
    ({"query": "кофе", "filters": "f128683=418141"}, "filters"),
    ({"query": "кофе", "category": "9515"}, "category"),        # unknown params are refused, never ignored
    ({"query": "кофе", "limit": "10"}, "limit"),
])
def test_search_rejects(query, field):
    assert field in _errors(schemas.ProductsSearchSchema, query)


def test_search_error_messages():
    assert _errors(schemas.ProductsSearchSchema, {"query": "кофе", "sort": "benefit"})["sort"] == \
        ["Must be one of: popular, rating, price_asc, price_desc, newest."]
    message = _errors(schemas.ProductsSearchSchema, {"query": "кофе", "destination": "paris"})["destination"][0]
    assert message.startswith("Not a known city or destination id. Cities: moscow, saint_petersburg")
    assert "RUB, BYN, KZT" in _errors(schemas.ProductsSearchSchema, {"query": "кофе", "currency": "eur"})["currency"][0].upper()


# ---- products/filters, details, batch ------------------------------------------------------

def test_filters_schema():
    assert schemas.ProductsFiltersSchema().load({"query": "кофе"}) == \
        {"query": "кофе", "filter": None, "destination": MOSCOW, "currency": "RUB"}
    assert schemas.ProductsFiltersSchema().load({"query": "кофе", "filter": "fbrand"})["filter"] == "fbrand"
    assert "filter" in _errors(schemas.ProductsFiltersSchema, {"query": "кофе", "filter": "brand"})
    assert "query" in _errors(schemas.ProductsFiltersSchema, {})


@pytest.mark.parametrize("value", [
    "90858341", "https://www.wildberries.ru/catalog/90858341/detail.aspx",
    "wildberries.ru/catalog/90858341/feedbacks?imtId=70662956"])
def test_product_accepts_article_and_link(value):
    assert schemas.ProductSchema().load({"product": value}) == \
        {"product": "90858341", "destination": MOSCOW, "currency": "RUB"}


@pytest.mark.parametrize("value", ["", "кофе", "https://www.ozon.ru/product/90858341/",
                                   "https://www.wildberries.ru/brands/barista"])
def test_product_rejects(value):
    message = _errors(schemas.ProductSchema, {"product": value})["product"][0]
    assert value == "" or "Pass the product's article (90858341) or its link" in message
    assert value != "https://www.ozon.ru/product/90858341/" or message.startswith("Not a wildberries.ru link.")


def test_product_rejects_sibling_params():
    for sibling in ("url", "id", "article", "link"):
        assert sibling in _errors(schemas.ProductSchema, {"product": "90858341", sibling: "90858341"})


def test_product_destination_forms():
    assert schemas.ProductSchema().load({"product": "1", "destination": "-1257786"})["destination"] == -1257786
    assert schemas.ProductSchema().load({"product": "1", "destination": "Saint Petersburg"})["destination"] == \
        refs.CITIES["saint_petersburg"]
    assert schemas.ProductSchema().load({"product": "1", "destination": ""})["destination"] == MOSCOW
    assert schemas.ProductSchema().load({"product": "1", "currency": "usd"})["currency"] == "USD"
    # a param sent empty means its default, never None
    assert schemas.ProductSchema().load({"product": "1", "currency": ""})["currency"] == "RUB"
    assert schemas.ProductsSearchSchema().load({"query": "кофе", "sort": "", "destination": ""})["sort"] == "popular"


def test_batch_schema():
    loaded = schemas.ProductsBatchSchema().load(
        {"products": "90858341, https://www.wildberries.ru/catalog/12801489/detail.aspx ,90858341"})
    assert loaded == {"products": ["90858341", "12801489"], "destination": MOSCOW, "currency": "RUB"}
    too_many = ",".join(str(1000 + i) for i in range(refs.MAX_BATCH + 1))
    assert _errors(schemas.ProductsBatchSchema, {"products": too_many})["products"] == ["At most 100 products in one call."]
    assert "products" in _errors(schemas.ProductsBatchSchema, {"products": "90858341,кофе"})
    assert "products" in _errors(schemas.ProductsBatchSchema, {})


# ---- reviews, questions --------------------------------------------------------------------

def test_reviews_and_questions_schemas():
    assert schemas.ProductReviewsSchema().load({"product": "90858341"}) == {"product": "90858341", "page": 1}
    assert schemas.ProductReviewsSchema().load({"product": "90858341", "page": "20"})["page"] == 20
    assert "page" in _errors(schemas.ProductReviewsSchema, {"product": "90858341", "page": "21"})
    assert "destination" in _errors(schemas.ProductReviewsSchema, {"product": "90858341", "destination": "moscow"})
    assert schemas.ProductQuestionsSchema().load({"product": "90858341", "page": "200"})["page"] == 200
    assert "page" in _errors(schemas.ProductQuestionsSchema, {"product": "90858341", "page": "201"})
    assert "product" in _errors(schemas.ProductQuestionsSchema, {})


# ---- categories ----------------------------------------------------------------------------

def test_categories_list_schema():
    assert schemas.CategoriesListSchema().load({}) == {"category": None}
    assert schemas.CategoriesListSchema().load({"category": "10296"}) == {"category": "10296"}
    assert schemas.CategoriesListSchema().load({"category": "https://www.wildberries.ru/catalog/pitanie"}) == \
        {"category": "/catalog/pitanie"}
    assert "category" in _errors(schemas.CategoriesListSchema, {"category": "coffee"})


def test_category_products_schema():
    loaded = schemas.CategoryProductsSchema().load(
        {"category": "https://www.wildberries.ru/catalog/pitanie/chay-kofe/kofe?sort=rate&page=2", "sort": "rating",
         "brand": "14447"})
    assert loaded == {"category": "/catalog/pitanie/chay-kofe/kofe", "page": 1, "brand": "14447", "seller": None,
                      **LIST_DEFAULTS, "sort": "rating"}
    assert "category" in _errors(schemas.CategoryProductsSchema, {})
    assert "page" in _errors(schemas.CategoryProductsSchema, {"category": "9515", "page": "61"})
    assert "filters" in _errors(schemas.CategoryProductsSchema, {"category": "9515", "filters": "f1:2"})
    assert "category" in _errors(schemas.CategoryProductsSchema,
                                 {"category": "https://www.wildberries.ru/catalog/90858341/detail.aspx"})


# ---- brands, sellers, suggestions ------------------------------------------------------------

@pytest.mark.parametrize("value, resolved", [
    ("14447", "14447"), ("Barista", "barista"), ("https://www.wildberries.ru/brands/barista", "barista")])
def test_brand_products_schema(value, resolved):
    assert schemas.BrandProductsSchema().load({"brand": value}) == \
        {"brand": resolved, "page": 1, "seller": None, **LIST_DEFAULTS}


def test_brand_products_rejects():
    assert "brand" in _errors(schemas.BrandProductsSchema, {})
    assert "brand" in _errors(schemas.BrandProductsSchema, {"brand": "https://www.wildberries.ru/seller/843763"})
    assert schemas.BrandProductsSchema().load({"brand": "14447", "page": "100"})["page"] == 100
    assert "page" in _errors(schemas.BrandProductsSchema, {"brand": "14447", "page": "101"})


def test_seller_schemas():
    assert schemas.SellerSchema().load({"seller": "https://www.wildberries.ru/seller/843763"}) == {"seller": "843763"}
    message = _errors(schemas.SellerSchema, {"seller": "https://www.wildberries.ru/seller/rivegauche"})["seller"][0]
    assert message.startswith("A seller link with a name instead of the id cannot be looked up.")
    assert "currency" in _errors(schemas.SellerSchema, {"seller": "843763", "currency": "RUB"})
    assert schemas.SellerProductsSchema().load({"seller": "843763", "brand": "14447", "sort": "newest"}) == \
        {"seller": "843763", "page": 1, "brand": "14447", **LIST_DEFAULTS, "sort": "newest"}
    assert "page" in _errors(schemas.SellerProductsSchema, {"seller": "843763", "page": "101"})


def test_suggestions_schema():
    assert schemas.SuggestionsSchema().load({"query": " коф "}) == {"query": "коф"}
    assert "query" in _errors(schemas.SuggestionsSchema, {})
    assert "query" in _errors(schemas.SuggestionsSchema, {"query": "к" * 101})


def test_every_field_has_a_description():
    for name in dir(schemas):
        schema = getattr(schemas, name)
        if isinstance(schema, type) and issubclass(schema, schemas.BaseSchema) and name.endswith("Schema") \
                and schema is not schemas.BaseSchema:
            for field_name, field in schema().fields.items():
                assert field.metadata.get("description"), f"{name}.{field_name} has no description"
