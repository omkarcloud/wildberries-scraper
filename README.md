# 🚀 Wildberries Scraper

Wildberries Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Wildberries data for free.

## ✨ What Can I Get?

- 🛍️ **Full product cards from the marketplace 79M+ shoppers buy from** — price, discount, stock per warehouse, every photo, specs, variants & weekly price history
- 🔍 **Search the store behind 20M+ orders a day** — by keyword, category, brand or seller, with sort, price, delivery & spec filters
- ⭐ **Up to 1,000 newest reviews per product** — rating, text, pros & cons, photos, seller replies, star split & buyer Q&A
- 🏪 **Profiles of 1M+ sellers** — legal name, tax IDs, address, rating, reviews, items sold & the products they sell

## 🛒 Example: A Full Wildberries Product

```json
{
  "id": 534219106,
  "name": "Чокер на шею сердце из алмазного стекла бижутерия",
  "link": "https://www.wildberries.ru/catalog/534219106/detail.aspx",
  "brand": { "id": 3085396, "name": "ANSHEL" },
  "seller": { "id": 522927, "name": "ANSHEL", "link": "https://www.wildberries.ru/seller/522927", "rating": 4.9 },
  "subject": { "id": 1689, "name": "Чокеры", "parent_id": 200, "parent_name": "Бижутерия" },
  "description": "Чокер из сверкающего алмазного стекла это трендовое женское украшение для современной девушки…",
  "characteristics": [
    { "group": "Дополнительная информация", "name": "Состав бижутерии", "value": "алмазное стекло" },
    { "group": "Габариты", "name": "Длина предмета", "value": "36 см" }
  ],
  "images": ["https://basket-28.wbbasket.ru/vol5342/part534219/534219106/images/big/1.webp"],
  "images_count": 16,
  "price": 708,
  "original_price": 2300,
  "discount_percent": 69,
  "currency": "RUB",
  "rating": 4.9,
  "reviews_count": 40050,
  "quantity": 41,
  "delivery_hours": 57,
  "sizes": [{ "name": "36-41", "price": 708, "quantity": 41, "warehouses": [{ "id": 211730, "quantity": 41, "delivery_hours": 57 }] }],
  "variants": [{ "id": 77831313, "link": "https://www.wildberries.ru/catalog/77831313/detail.aspx" }],
  "price_history": [
    { "date": "2026-07-05", "price": 634.3, "currency": "RUB" },
    { "date": "2026-07-12", "price": 655.01, "currency": "RUB" }
  ]
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Wildberries Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/wildberries-scraper
cd wildberries-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

Wildberries answers its data only to a real browser, so the first request opens Chrome for a few seconds to earn its cookie. Every request after that is plain HTTP.

Your own connection is all it needs. If Wildberries refuses your IP, set one datacenter proxy, `WILDBERRIES_PROXY=http://user:pass@host:port`, and keep going.

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/products/details?product=534219106"
```

```json
{
  "id": 534219106,
  "name": "Чокер на шею сердце из алмазного стекла бижутерия",
  "link": "https://www.wildberries.ru/catalog/534219106/detail.aspx",
  "brand": { "id": 3085396, "name": "ANSHEL" },
  "seller": { "id": 522927, "name": "ANSHEL", "link": "https://www.wildberries.ru/seller/522927", "rating": 4.9 },
  "subject": { "id": 1689, "name": "Чокеры", "parent_id": 200, "parent_name": "Бижутерия" },
  "images_count": 16,
  "price": 708,
  "original_price": 2300,
  "discount_percent": 69,
  "currency": "RUB",
  "destination": { "id": 1259570991, "city": "moscow" },
  "rating": 4.9,
  "reviews_count": 40059,
  "quantity": 53,
  "is_in_stock": true,
  "delivery_hours": 56,
  "price_history": [{ "date": "2026-07-05", "price": 634.3, "currency": "RUB" }]
}
```

All 12 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

12 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Product Details | `/products/details` | The whole product card in one call, price history included |
| Product Reviews / Questions | `/products/reviews`, `/products/questions` | Up to 1,000 newest reviews plus buyer questions with seller answers |
| Bulk Product Lookup | `/products/batch` | Live price, stock and rating for 100 products per call |
| Search Suggestions | `/search/suggestions` | What Wildberries suggests as shoppers type, with search links |
| Search Products | `/products/search` | Any search, 100 products per page, with sort and spec filters |
| Search Filters | `/products/filters` | Every brand, seller, type and spec filter a search offers |
| Categories / Category Products | `/categories/list`, `/categories/products` | The full category menu and any category's products |
| Brand Products | `/brands/products` | A brand's products, 100 per page, sorted and filtered your way |
| Seller Details / Products | `/sellers/details`, `/sellers/products` | A seller's legal profile, rating, sales and storefront products |


## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-wildberries-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-wildberries-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-wildberries-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/products/details",
    params={"product": "534219106"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Wildberries Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/wildberries-scraper-github-whatsapp)

[![Ask Us by Email about Wildberries Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Wildberries%20Scraper%20API&body=I%20need%20help%20using%20the%20Wildberries%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/wildberries-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/wildberries-scraper)
