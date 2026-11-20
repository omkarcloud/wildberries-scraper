"""Cache TTL per /wildberries/* endpoint (cache.py, keyed on the validated
params). Prices and stock move during the day, so everything that carries
them is kept for minutes; what a seller or the site edits by hand (texts,
the menu, legal records) is kept for hours.
"""
from datetime import timedelta

# A list page carries live prices, stock and delivery times.
LISTING_CACHE = timedelta(minutes=10)
# A full product record: the live card joined with its static card and price history.
PRODUCT_CACHE = timedelta(minutes=10)
# The batch call is bought for fresh prices: shortest of all.
BATCH_CACHE = timedelta(minutes=5)
# The static card (description, characteristics, the card id) changes when the seller edits it.
STATIC_CARD_CACHE = timedelta(hours=12)
# One row per card: the whole parsed reviews file, sliced per page.
REVIEWS_CACHE = timedelta(hours=1)
# One row per questions page.
QUESTIONS_CACHE = timedelta(hours=1)
# A search's filters and their option lists follow the catalogue, not the minute.
FILTERS_CACHE = timedelta(hours=1)
# The site's menu changes a few times a month (its file was two days old when captured).
CATEGORIES_CACHE = timedelta(hours=6)
# A brand's id, name and page name.
BRAND_CACHE = timedelta(hours=24)
# A seller's legal record and rating counters (the site refreshes them a few times a day).
SELLER_CACHE = timedelta(hours=6)
# What the search box suggests follows the season, not the minute.
SUGGESTIONS_CACHE = timedelta(hours=6)
