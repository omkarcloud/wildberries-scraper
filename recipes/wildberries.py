"""Wildberries (www.wildberries.ru): the site's own anti-bot ("wbaas", HTTP
498) stands in front of every www.wildberries.ru/__internal/* JSON call. A
request without the `x_wbaas_token` cookie gets a 1 KB challenge page whose
script (/__wbaas/challenges/antibot/) runs a browser check, posts
create-token and reloads the same link, which then answers its JSON.

The seed is /robots.txt: a navigation to it gets the challenge page like
any page of the site, and once the challenge clears the reload shows the
plain robots file, so no storefront, script bundle or image is loaded. (A
navigation straight to an /__internal/ call is refused with an empty 403:
those answer the challenge page only to the page's own XHR.)

A hidden (headless) Chrome never clears it: the cookie is set all the same,
but the page stays on the challenge ("Get token tries exceeded", Mac
2026-11-19), so `passed()` wants the robots file on the page, not only the cookie.
A visible Chrome clears it by itself, with no interaction.

The identity is the cookie plus the browser's UA. wildberries/fetch.py
replays it with curl_cffi (chrome profile) from the pod's own address: the
token is honoured from another address (pod probe 2026-11-19), but a replay
under a Safari profile, or from many addresses within a minute, gets it
revoked about two minutes later."""
from browser_worker.types import CookieMint

SEED = "https://www.wildberries.ru/robots.txt"
COOKIE = "x_wbaas_token"
CHALLENGE_MARKERS = ("/__wbaas/challenges/antibot/",)
PASSED_MARKER = "disallow"            # the robots file, shown once the challenge reloaded into it


class Wildberries(CookieMint):
    name = "wildberries"
    headless = False
    variants = {"": SEED}
    wait_for_cookie = COOKIE
    challenge_markers = CHALLENGE_MARKERS
    block_resources = ("image", "font", "media")
    require_challenge = False     # passed() decides: the cookie exists before the challenge clears
    nav_settle = False            # poll from domcontentloaded: the challenge script starts on load
    timeout = 45
    poll = 1.0
    referer = "https://www.wildberries.ru/"
    ttl_seconds = 12 * 3600       # the token names a 72 h expiry; GKE replaces it on the first 498 anyway

    def passed(self, cookies, driver):
        """True once the seed shows the robots file with the cookie set. The
        cookie alone is not enough: a browser that fails the check holds one too."""
        if COOKIE not in cookies:
            return False
        try:
            html = (driver.call(lambda page: page.content()) or "")[:20000]
        except Exception:
            return False          # mid-reload after the challenge
        if any(marker in html for marker in CHALLENGE_MARKERS):
            return False
        return PASSED_MARKER in html.lower()

    def tokens(self, cookies, driver):
        return {COOKIE: cookies[COOKIE]}


RECIPE = Wildberries
