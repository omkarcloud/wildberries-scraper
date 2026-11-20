"""Offline tests for the Wildberries transport: what each answer of the
site turns into, and when the shared token is replaced. No network, no
browser box: the session and the mint are faked.

    python -m pytest wildberries/test_fetch.py -q
"""
import gzip
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import identity_pool  # noqa: E402
from wildberries import fetch  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def raw_fixture(name):
    path = os.path.join(FX, name)
    if os.path.exists(path + ".gz"):
        with gzip.open(path + ".gz", "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        return f.read()


class Answer:
    def __init__(self, status=200, body=b""):
        self.status_code = status
        self.content = body if isinstance(body, bytes) else json.dumps(body).encode()

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")


@pytest.fixture
def site(monkeypatch):
    """A fake site: `site.answers` is the queue of answers, `site.sent` what
    was sent, `site.mints` how many tokens were minted."""
    class Site:
        answers, sent, mints = [], [], 0

    def send(url, headers, timeout):
        Site.sent.append((url, headers))
        return Site.answers.pop(0)

    def mint(key, hint):
        Site.mints += 1
        return identity_pool.Identity({"cookie": f"x_wbaas_token=token{Site.mints}; _wbauid=1231795087996",
                                       "headers": {"user-agent": "Box Chrome"},
                                       "device_id": "site_abc", "visitor": "1231795087996"})

    Site.answers, Site.sent, Site.mints = [], [], 0
    monkeypatch.setattr(fetch, "_send", send)
    monkeypatch.setattr(fetch, "_tokens", identity_pool.Pool("wildberries-test", mint))
    monkeypatch.setattr(fetch, "_drop_session", lambda: None)
    monkeypatch.setattr(fetch.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(fetch, "_next_list_call", 0.0)
    fetch._memo.clear()
    return Site


CHALLENGE = Answer(498, raw_fixture("challenge_page.html"))
CARD = Answer(200, raw_fixture("card_90858341.json"))


def test_card_call_goes_out_as_the_page_sends_it(site):
    site.answers = [CARD]
    raw = fetch.fetch_cards(["90858341", "12801489"], 1259570991, "RUB")
    assert raw["products"][0]["id"] == 90858341 and site.mints == 1
    url, headers = site.sent[0]
    assert url == ("https://www.wildberries.ru/__internal/u-card/cards/v4/detail?appType=1&curr=rub&dest=1259570991"
                   "&spp=30&hide_vflags=4294967296&mtype=257&lang=ru&ab_testing=false&nm=90858341;12801489")
    assert headers["cookie"] == "x_wbaas_token=token1; _wbauid=1231795087996"
    assert headers["deviceid"] == "site_abc" and headers["user-agent"] == "Box Chrome"
    assert headers["referer"] == "https://www.wildberries.ru/catalog/90858341/detail.aspx"
    assert headers["x-requested-with"] == "XMLHttpRequest" and headers["sec-fetch-site"] == "same-origin"
    assert headers["x-spa-version"] and "x-queryid" not in headers and "x-userid" not in headers


def test_a_refused_token_is_replaced_once(site):
    site.answers = [CHALLENGE, CARD, CARD]
    assert fetch.fetch_cards(["90858341"], 1259570991, "RUB")["products"]
    assert site.mints == 2
    assert site.sent[0][1]["cookie"].startswith("x_wbaas_token=token1;")
    assert site.sent[1][1]["cookie"].startswith("x_wbaas_token=token2;")
    fetch.fetch_cards(["90858341"], 1259570991, "RUB")          # the next call rides the new token: no mint
    assert site.mints == 2


def test_a_token_refused_on_every_try_is_a_block(site):
    site.answers = [CHALLENGE, Answer(403, b""), CHALLENGE]
    with pytest.raises(fetch.WildberriesBlocked):
        fetch.fetch_cards(["90858341"], 1259570991, "RUB")
    assert len(site.sent) == fetch.config.MAX_RETRIES


def test_a_refused_search_gets_the_tries_of_any_other_call(site):
    site.answers = [CHALLENGE for _ in range(fetch.config.MAX_RETRIES ** 2)]
    with pytest.raises(fetch.WildberriesBlocked):
        fetch.fetch_search("кофе", page=1, sort="popular", destination=1259570991, currency="RUB")
    assert len(site.sent) == fetch.config.MAX_RETRIES and site.mints == fetch.config.MAX_RETRIES


def test_a_failed_mint_is_not_followed_by_a_second_one(site, monkeypatch):
    mints = []

    def down(key, hint):
        mints.append(key)
        raise fetch.WildberriesBlocked("token mint failed: no box")

    monkeypatch.setattr(fetch, "_tokens", identity_pool.Pool("wildberries-test", down))
    with pytest.raises(fetch.WildberriesBlocked, match="token mint failed"):
        fetch.fetch_cards(["90858341"], 1259570991, "RUB")
    assert len(mints) == fetch.config.MAX_RETRIES and site.sent == []      # one mint a try, nothing sent


def test_rate_limit_waits_and_keeps_the_token(site):
    site.answers = [Answer(429, b""), Answer(200, raw_fixture("seller_products_843763.json"))]
    raw = fetch.fetch_seller_products("843763", page=1, sort="popular", destination=1259570991, currency="RUB")
    assert raw["total"] == 81 and site.mints == 1
    assert site.sent[0][1]["cookie"] == site.sent[1][1]["cookie"]


def test_list_page_past_the_end_is_none(site):
    site.answers = [Answer(200, b"")]
    assert fetch.fetch_brand_products(14447, "barista", page=101, sort="popular", destination=1259570991,
                                      currency="RUB") is None
    assert "&page=101&" in site.sent[0][0] and site.sent[0][1]["referer"] == "https://www.wildberries.ru/brands/barista"


def test_search_call_and_its_stand_in_page(site):
    site.answers = [Answer(200, raw_fixture("search_stand_in.json")), Answer(200, raw_fixture("search_kofe.json"))]
    raw = fetch.fetch_search("кофе", page=2, sort="priceup", destination=1259570991, currency="KZT",
                             filters={"fbrand": "14447;24007"}, min_price=500, max_price=None)
    assert len(raw["products"]) == 100 and len(site.sent) == 2 and site.mints == 1
    url, headers = site.sent[1]
    assert url == ("https://www.wildberries.ru/__internal/u-search/exactmatch/ru/common/v18/search?ab_testing=false"
                   "&appType=1&curr=kzt&dest=1259570991&fbrand=14447%3B24007&hide_vflags=4294967296&inheritFilters=true"
                   "&lang=ru&locale=ru&page=2&priceU=50000%3B99999999900&query=%D0%BA%D0%BE%D1%84%D0%B5"
                   "&resultset=catalog&sort=priceup&spp=30&suppressSpellcheck=false")
    assert headers["x-userid"] == "0" and headers["x-queryid"].startswith("qid1231795087996")
    assert headers["referer"] == "https://www.wildberries.ru/catalog/0/search.aspx?search=%D0%BA%D0%BE%D1%84%D0%B5"


def test_search_first_page_matches_the_captured_call(site):
    site.answers = [Answer(200, raw_fixture("search_no_results.json"))]
    raw = fetch.fetch_search("кофе", page=1, sort="popular", destination=1259570991, currency="RUB")
    assert "products" not in raw                                  # no result: the caller answers an empty page
    # samples/calls/p5-11-www_v18_search.request.json, 2026-11-19
    assert site.sent[0][0] == ("https://www.wildberries.ru/__internal/u-search/exactmatch/ru/common/v18/search"
                               "?ab_testing=false&appType=1&curr=rub&dest=1259570991&hide_vflags=4294967296"
                               "&inheritFilters=true&lang=ru&locale=ru&query=%D0%BA%D0%BE%D1%84%D0%B5&resultset=catalog"
                               "&sort=popular&spp=30&suppressSpellcheck=false")


def test_category_search_carries_no_inherit_filters(site):
    site.answers = [Answer(200, raw_fixture("category_9515_kofe.json"))]
    fetch.fetch_search("menu_v3_9463 смартфон", page=1, sort="popular", destination=1259570991, currency="RUB",
                       referer="https://www.wildberries.ru/catalog/elektronika/smartfony-i-telefony/vse-smartfony",
                       inherit_filters=False)
    # samples/calls/p7-15-www_v18_search.request.json, 2026-11-19
    assert site.sent[0][0].endswith("?ab_testing=false&appType=1&curr=rub&dest=1259570991&hide_vflags=4294967296&lang=ru"
                                    "&locale=ru&query=menu_v3_9463+%D1%81%D0%BC%D0%B0%D1%80%D1%82%D1%84%D0%BE%D0%BD"
                                    "&resultset=catalog&sort=popular&spp=30&suppressSpellcheck=false")


def test_search_error_body_is_a_bad_request(site):
    site.answers = [Answer(200, raw_fixture("search_page_past_end.json"))]
    with pytest.raises(fetch.WildberriesBadRequest, match="page param malformed"):
        fetch.fetch_search("кофе", page=61, sort="popular", destination=1259570991, currency="RUB")
    assert len(site.sent) == 1


def test_stand_in_page_on_every_try_is_an_upstream_error(site):
    site.answers = [Answer(200, raw_fixture("search_stand_in.json")) for _ in range(fetch.config.MAX_RETRIES)]
    with pytest.raises(fetch.WildberriesUpstreamError, match="stand-in"):
        fetch.fetch_search("кофе", page=1, sort="popular", destination=1259570991, currency="RUB")


def test_free_calls_need_no_token(site):
    site.answers = [Answer(200, raw_fixture("basket_hosts.json")), Answer(200, raw_fixture("static_card_90858341.json")),
                    Answer(404, raw_fixture("static_card_not_found.html")),
                    Answer(404, b"Not found"), Answer(200, raw_fixture("questions_70662956.json")),
                    Answer(400, raw_fixture("questions_bad_request.json"))]
    assert fetch.fetch_static_card("90858341")["imt_id"] == 70662956
    assert site.sent[1][0] == "https://basket-05.wbbasket.ru/vol908/part90858/90858341/info/ru/card.json"
    assert fetch.fetch_price_history("90858341") == []           # a product without the file
    assert fetch.fetch_reviews(4526613009, "2280175570") is None  # a card nobody reviewed
    assert site.sent[3][0] == "https://feedback01.wbbasket.ru/vol50/part5013/5013009/reviews/v1/ru/ru/imt/list/date/4526613009.json"
    assert fetch.fetch_questions(70662956, "90858341", 30, 0)["count"] == 240
    assert site.sent[4][0] == "https://questions.wildberries.ru/api/v1/questions?imtId=70662956&take=30&skip=0"
    with pytest.raises(fetch.WildberriesBadRequest):
        fetch.fetch_questions(70662956, "90858341", 31, 0)
    assert site.mints == 0
    assert all("cookie" not in headers and "deviceid" not in headers for _, headers in site.sent)
    assert site.sent[1][1]["origin"] == "https://www.wildberries.ru" and site.sent[1][1]["sec-fetch-site"] == "cross-site"


def test_unknown_article_and_brand_are_not_found(site):
    site.answers = [Answer(200, raw_fixture("basket_hosts.json")), Answer(404, raw_fixture("static_card_not_found.html")),
                    Answer(404, b"")]
    with pytest.raises(fetch.WildberriesNotFound):
        fetch.fetch_static_card("2880000001")
    with pytest.raises(fetch.WildberriesNotFound):
        fetch.fetch_static_card("99999999999")                    # no basket host holds this volume: no call at all
    with pytest.raises(fetch.WildberriesNotFound):
        fetch.fetch_brand("no-such-brand")
    assert site.sent[-1][0] == "https://static-basket-01.wbbasket.ru/vol0/data/brands/no-such-brand.json"


def test_a_missing_reference_file_is_the_sites_failure(site):
    # the host table or the menu answering 404 / 400 says nothing about the caller's product or category
    site.answers = [Answer(404, b""), Answer(404, b""), Answer(400, b"")]
    with pytest.raises(fetch.WildberriesUpstreamError, match="basket host table"):
        fetch.fetch_static_card("90858341")
    with pytest.raises(fetch.WildberriesUpstreamError, match="menu"):
        fetch.fetch_menu()
    with pytest.raises(fetch.WildberriesUpstreamError, match="menu"):
        fetch.fetch_menu()
    assert len(site.sent) == 3                                    # a 404 / 400 is not retried, and nothing is kept


def test_seller_files(site):
    site.answers = [Answer(404, b""), Answer(200, raw_fixture("seller_stats_not_found.json")),
                    Answer(200, raw_fixture("seller_legal_843763.json"))]
    assert fetch.fetch_seller_legal("999999999") is None
    assert fetch.fetch_seller_stats("999999999", "RUB")["registrationDate"] is None
    assert site.sent[1][0] == "https://suppliers-shipment-2.wildberries.ru/api/v1/suppliers/999999999?curr=RUB"
    assert site.sent[1][1]["x-client-name"] == "site"
    assert fetch.fetch_seller_legal("843763")["inn"] == "6732230927"


def test_box_failure_is_a_block(monkeypatch):
    from browser_client import BoxUnavailable

    def down(site, proxy=None, variant=""):
        raise BoxUnavailable("no box")

    monkeypatch.setattr(fetch.browser_client, "mint", down)
    with pytest.raises(fetch.WildberriesBlocked, match="token mint failed"):
        fetch._mint("", None)


def test_mint_builds_the_identity(monkeypatch):
    monkeypatch.setattr(fetch.browser_client, "mint", lambda site, proxy=None, variant="": {
        "cookies": [{"name": "x_wbaas_token", "value": "abc"}], "tokens": {"x_wbaas_token": "abc"},
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/156.0.0.0", "accept_language": fetch.egress.accept_language(),
        "client_hints": {"brands": [{"brand": "Google Chrome", "version": "156"}], "mobile": False, "platform": "Linux"},
        "expires_at": 1795400000.0})
    ident = fetch._mint("", None)
    value = ident.value
    assert value["cookie"].startswith("x_wbaas_token=abc; _wbauid=") and value["device_id"].startswith("site_")
    assert len(value["device_id"]) == len("site_") + 32 and value["visitor"].isdigit()
    assert value["headers"]["user-agent"].endswith("Chrome/156.0.0.0") and value["headers"]["sec-ch-ua-platform"] == '"Linux"'
    assert value["headers"]["accept-language"] == fetch.egress.accept_language()      # the minting browser's own
    assert ident.expires_at == 1795400000.0 and ident.exit is None
