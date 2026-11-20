"""Use the scraper straight from Python, no server needed.

    python main.py

Each call validates its params with the same schema the API uses (so the
defaults apply) and returns the same JSON the API does, except that a list
keeps its `pagination` block instead of next / previous links. The results
are written to output/*.json.
"""
import json
import os

from wildberries import api, schemas
from schema_fields import load_query

os.makedirs("output", exist_ok=True)


def run(schema_cls, impl, **params):
    data, error = load_query(schema_cls, {k: str(v) for k, v in params.items()})
    if error:
        raise ValueError(error)
    return impl(**data)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a full product: price, discount, stock per size and warehouse, photos, specs, variants, seller and weekly price history
    save("products_details.json", run(schemas.ProductSchema, api.products_details, product='534219106'))

    # its 100 newest reviews (stars, text, pros, cons, photos, seller replies) with the card's star split and size fit
    save("products_reviews.json", run(schemas.ProductReviewsSchema, api.products_reviews, product='534219106'))

    # its buyer questions with the seller's answers, 30 per page
    save("products_questions.json", run(schemas.ProductQuestionsSchema, api.products_questions, product='534219106'))
