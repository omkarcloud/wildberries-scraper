"""Marshmallow request schemas for every /wildberries/* route.

ONE param per input (never a sibling `url` / `id` pair):

    product      a product's article (90858341) OR its wildberries.ru link
    products     up to 100 of those, separated by commas
    seller       a seller id (843763) OR a /seller/<id> link
    brand        on /brands/products: a brand id (14447), its page name
                 (barista) OR a /brands/<name> link
    category     a menu category id (9515) OR its page link
    destination  a city name (moscow, saint_petersburg, ...) OR the site's
                 own destination id; prices, stock and delivery times are
                 answered for it

The list endpoints share their filters. `brand`, `seller` and `subject`
there are ids as /wildberries/products/filters lists them (a subject is a
product type, e.g. 5133 "whole-bean coffee"; it is not a menu category).
A value the site would silently ignore (a sort it does not have, a filter
switched "off", a currency it does not price in) is refused here.
"""
from marshmallow import ValidationError, post_load, validates_schema

from schema_fields import (BaseSchema, ChoiceField, PageField, PositiveInt, Price, QueryField, RefField,
                           TrueOnlyFlag)
from wildberries import refs

MAX_REVIEWS_PAGE = 20           # a card's reviews file holds about 1,000 reviews: 100 a page
MAX_QUESTIONS_PAGE = 200        # 30 a page


class ProductRefField(RefField):
    resolver = staticmethod(refs.resolve_product)


class ProductsRefField(RefField):
    resolver = staticmethod(refs.resolve_products)


class SellerRefField(RefField):
    resolver = staticmethod(refs.resolve_seller)


class BrandRefField(RefField):
    resolver = staticmethod(refs.resolve_brand)


class CategoryRefField(RefField):
    resolver = staticmethod(refs.resolve_category)


class DestinationField(RefField):
    resolver = staticmethod(refs.resolve_destination)


def _id_list(what):
    return lambda value: refs.resolve_id_list(value, what)


def _product_field():
    return ProductRefField(metadata={
        "description": "the product's article (90858341) or its link "
                       "(https://www.wildberries.ru/catalog/90858341/detail.aspx)"})


def _seller_field():
    return SellerRefField(metadata={
        "description": "the seller's id (843763) or its link (https://www.wildberries.ru/seller/843763)"})


def _destination_field():
    return DestinationField(required=False, load_default=refs.DEFAULT_DESTINATION, metadata={
        "description": "where the order would be delivered: a city (" + ", ".join(refs.CITIES) + ") or the site's own "
                       "destination id. Default moscow. Prices, stock and delivery times are answered for it; an id "
                       "the site does not know shows every product as out of stock"})


def _currency_field():
    return ChoiceField({code: code for code in refs.CURRENCIES}, load_default=refs.DEFAULT_CURRENCY, metadata={
        "description": "currency of every price: " + ", ".join(refs.CURRENCIES) + ". Default RUB"})


def _sort_field():
    return ChoiceField(list(refs.SORTS), load_default=refs.DEFAULT_SORT, metadata={
        "description": "order: popular (default), rating, price_asc, price_desc, newest"})


def _page_field(max_page):
    return PageField(max_page=max_page, metadata={
        "description": f"result page, 100 products each (1-{max_page}: the site serves no page past {max_page})"})


class _Market(BaseSchema):
    destination = _destination_field()
    currency = _currency_field()

    @post_load
    def _empty_means_default(self, data, **kwargs):
        """`?currency=` (a param sent empty) loads as None: it means the default, like a param left out."""
        if data.get("destination") is None:
            data["destination"] = refs.DEFAULT_DESTINATION
        if data.get("currency") is None:
            data["currency"] = refs.DEFAULT_CURRENCY
        if "sort" in self.fields and data.get("sort") is None:
            data["sort"] = refs.DEFAULT_SORT
        return data


class _ListFilters(_Market):
    """The filters every product list takes."""
    sort = _sort_field()
    min_price = Price(metadata={"description": "lowest price to include, in the request's currency"})
    max_price = Price(metadata={"description": "highest price to include, in the request's currency"})
    subject = RefField(resolver=_id_list("a subject"), required=False, load_default=None, metadata={
        "description": "product type id(s), separated by commas, as /wildberries/products/filters lists them under "
                       "xsubject (5133 = whole-bean coffee)"})
    top_rated = TrueOnlyFlag(metadata={"description": "true = only products rated 4.7 or higher"})
    max_delivery_hours = PositiveInt(max_value=1000, metadata={
        "description": "only products the site can deliver to the destination within this many hours"})
    original = TrueOnlyFlag(metadata={"description": "true = only products the site marks as original"})
    premium_seller = TrueOnlyFlag(metadata={"description": "true = only products of premium sellers"})
    express = TrueOnlyFlag(metadata={"description": "true = only products with express delivery"})
    has_video = TrueOnlyFlag(metadata={"description": "true = only products that have a video"})

    @validates_schema
    def _price_range(self, data, **kwargs):
        low, high = data.get("min_price"), data.get("max_price")
        if low is not None and high is not None and low > high:
            raise ValidationError("min_price must not exceed max_price.", "max_price")


def _brand_filter():
    return RefField(resolver=_id_list("a brand"), required=False, load_default=None, metadata={
        "description": "brand id(s), separated by commas, as /wildberries/products/filters lists them under fbrand"})


def _seller_filter():
    return RefField(resolver=_id_list("a seller"), required=False, load_default=None, metadata={
        "description": "seller id(s), separated by commas, as /wildberries/products/filters lists them under fsupplier"})


def _attribute_filters():
    return RefField(resolver=refs.resolve_filters, required=False, load_default=None, metadata={
        "description": "attribute filters as key:id pairs separated by commas, with the keys and option ids "
                       "/wildberries/products/filters lists for this search (f128683:418141,f85571:136213)"})


class ProductsSearchSchema(_ListFilters):
    query = QueryField(metadata={"description": "what to search for, Russian or English (кофе, iphone 17)"})
    page = _page_field(refs.MAX_SEARCH_PAGE)
    brand = _brand_filter()
    seller = _seller_filter()
    filters = _attribute_filters()


class ProductsFiltersSchema(_Market):
    query = QueryField(metadata={"description": "the search whose filters to list (кофе, iphone 17)"})
    filter = RefField(resolver=refs.resolve_filter_key, required=False, load_default=None, metadata={
        "description": "one filter key (fbrand, xsubject, f128683): answers every option of that filter instead of "
                       "the top ones of each"})


class ProductSchema(_Market):
    product = _product_field()


class ProductsBatchSchema(_Market):
    products = ProductsRefField(metadata={
        "description": "up to 100 products, separated by commas: articles (90858341,12801489) and / or product links"})


class ProductReviewsSchema(BaseSchema):
    product = _product_field()
    page = PageField(max_page=MAX_REVIEWS_PAGE, metadata={
        "description": "review page, 100 reviews each, newest first (the site keeps about the 1,000 newest of a "
                       "product card)"})


class ProductQuestionsSchema(BaseSchema):
    product = _product_field()
    page = PageField(max_page=MAX_QUESTIONS_PAGE, metadata={"description": "questions page, 30 questions each"})


class CategoriesListSchema(BaseSchema):
    category = CategoryRefField(required=False, load_default=None, metadata={
        "description": "category id or link whose subcategories to list; empty = the top of the site's menu"})


class CategoryProductsSchema(_ListFilters):
    category = CategoryRefField(metadata={
        "description": "category id (9515, from /wildberries/categories/list) or its link "
                       "(https://www.wildberries.ru/catalog/pitanie/chay-kofe/kofe)"})
    page = _page_field(refs.MAX_SEARCH_PAGE)
    brand = _brand_filter()
    seller = _seller_filter()


class BrandProductsSchema(_ListFilters):
    brand = BrandRefField(metadata={
        "description": "brand id (14447), its page name (barista) or its link (https://www.wildberries.ru/brands/barista)"})
    page = _page_field(refs.MAX_CATALOG_PAGE)
    seller = _seller_filter()


class SellerSchema(BaseSchema):
    seller = _seller_field()


class SellerProductsSchema(_ListFilters):
    seller = _seller_field()
    page = _page_field(refs.MAX_CATALOG_PAGE)
    brand = _brand_filter()


class SuggestionsSchema(BaseSchema):
    query = QueryField(max_length=100, metadata={"description": "the first letters or words of a search (коф, iphone)"})
