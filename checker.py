"""
Tracker ID Checker — core engine.

For each site:
  1. Opens a fresh browser profile (no leftover cookies).
  2. Goes to Google, types the brand name, and clicks the site's organic result.
  3. Waits for the landing page (and its tags) to load, accepting the cookie banner if asked.
  4. Reads every cookie in the browser (like DevTools > Application > Cookies) and
     looks for the cookie named "trackerID" (name is configurable).
  5. Compares the value with the expected ID and records MATCH / MISMATCH / NOT_FOUND etc.

Can be used from the web UI (app.py) or the command line:
    python checker.py sites.csv --out results.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, Optional
from urllib.parse import quote_plus, unquote, urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from query_builder import DEFAULT_DIRECTORY_TERMS, describe_url

# --------------------------------------------------------------------------- #
# Data models
# --------------------------------------------------------------------------- #

@dataclass
class Site:
    url: str
    expected_id: str
    search_query: str = ""          # optional override; generated from the URL when blank
    brand: str = ""                 # generated from the URL when blank
    directory_terms: dict = field(default_factory=lambda: dict(DEFAULT_DIRECTORY_TERMS), repr=False)

    def __post_init__(self):
        info = describe_url(self.url, self.directory_terms)
        self.brand = self.brand.strip() or info["brand"] or self.domain
        self.search_query = self.search_query.strip() or info["query"] or self.brand

    @property
    def domain(self) -> str:
        return normalise_domain(self.url)

    @property
    def query(self) -> str:
        return self.search_query


@dataclass
class Settings:
    cookie_name: str = "trackerID"
    wait_seconds: int = 8           # how long to keep polling for the cookie after landing
    headless: bool = False          # visible browser is far less likely to hit Google CAPTCHA
    use_installed_chrome: bool = True
    accept_cookie_banner: bool = True
    fallback_direct: bool = True    # if site isn't clickable in Google, open it directly (Google referrer)
    captcha_wait_seconds: int = 90  # time you get to solve a Google CAPTCHA in the visible browser
    google_domain: str = "https://www.google.com"
    google_params: str = "hl=en&gl=ca"
    screenshots_dir: str = "screenshots"
    case_sensitive_match: bool = True
    check_http: bool = True         # record the URL's HTTP status / redirects


@dataclass
class Result:
    brand: str
    url: str
    expected_id: str
    search_query: str = ""
    status: str = "PENDING"         # MATCH | MISMATCH | NOT_FOUND | NOT_IN_SERP | CAPTCHA | ERROR
    actual_id: str = ""
    cookie_domain: str = ""
    other_values: str = ""          # other cookies/storage entries with the same name
    journey: str = ""               # google-click | direct-fallback
    serp_position: str = ""
    landing_url: str = ""
    http_status: str = ""           # status of the URL as entered (e.g. 200, 301)
    redirect_to: str = ""           # final URL if it redirected
    http_chain: str = ""            # e.g. "301 https://a → 200 https://b"
    note: str = ""
    screenshot: str = ""
    checked_at: str = ""


# --------------------------------------------------------------------------- #
# Input parsing
# --------------------------------------------------------------------------- #

HEADER_ALIASES = {
    "brand": ["brand", "brand name", "name", "site name", "site", "keyword"],
    "url": ["url", "website", "domain", "site url", "homepage", "link"],
    "expected_id": ["expected_id", "expected id", "expected", "tracker id", "trackerid",
                    "tracker_id", "correct id", "correct_id", "id", "tracking id"],
    "search_query": ["search_query", "search query", "query", "search term", "google query"],
}


def normalise_domain(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    host = urlparse(url).hostname or ""
    return host.lower().removeprefix("www.")


def _map_headers(headers: list[str]) -> dict[str, int]:
    found = {}
    clean = [h.strip().lower().replace("﻿", "") for h in headers]
    for key, aliases in HEADER_ALIASES.items():
        for i, h in enumerate(clean):
            if h in aliases and i not in found.values():
                found[key] = i
                break
    return found


def _looks_like_url(v: str) -> bool:
    v = v.strip()
    return bool(v) and " " not in v and ("." in v) and not v.replace(".", "").isdigit()


def parse_sites(text: str, directory_terms: dict | None = None) -> list[Site]:
    """Accepts CSV text (with or without a header row) or pasted lines.
    Without a header the column order is: url, expected_id[, search_query]
    (the older brand, url, expected_id[, search_query] order is still understood).
    Commas, tabs (pasted from Excel/Sheets) and semicolons are all accepted."""
    text = text.strip()
    if not text:
        return []
    rows = []
    for line in text.splitlines():           # each line may use its own separator (tab, comma or ;)
        if not line.strip():
            continue
        delim = "\t" if "\t" in line else (";" if line.count(";") > line.count(",") else ",")
        row = next(csv.reader([line], delimiter=delim), [])
        if any(c.strip() for c in row):
            rows.append(row)
    if not rows:
        return []

    mapping = _map_headers(rows[0])
    if {"url", "expected_id"} <= mapping.keys():
        body = rows[1:]
    else:
        if _looks_like_url(rows[0][0]):
            mapping = {"url": 0, "expected_id": 1, "search_query": 2}
        else:
            mapping = {"brand": 0, "url": 1, "expected_id": 2, "search_query": 3}
        body = rows

    def cell(row, key):
        i = mapping.get(key)
        return row[i].strip() if i is not None and i < len(row) else ""

    sites = []
    for row in body:
        url, expected = cell(row, "url"), cell(row, "expected_id")
        if not _looks_like_url(url):
            continue
        sites.append(Site(url=url, expected_id=expected, brand=cell(row, "brand"),
                          search_query=cell(row, "search_query"),
                          directory_terms=dict(directory_terms or DEFAULT_DIRECTORY_TERMS)))
    return sites


# --------------------------------------------------------------------------- #
# Browser helpers
# --------------------------------------------------------------------------- #

GOOGLE_CONSENT_BUTTONS = [
    "button:has-text('Accept all')", "button:has-text('I agree')",
    "button:has-text('Tout accepter')", "#L2AGLb",
]

SITE_CONSENT_BUTTONS = [
    "#onetrust-accept-btn-handler",                      # OneTrust
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",  # Cookiebot
    "#CybotCookiebotDialogBodyButtonAccept",
    "button#didomi-notice-agree-button",                 # Didomi
    ".cc-allow", ".cky-btn-accept", "#truste-consent-button",
    "button:has-text('Accept all')", "button:has-text('Accept All')",
    "button:has-text('Accept cookies')", "button:has-text('Allow all')",
    "button:has-text('I agree')", "button:has-text('I accept')",
    "button:has-text('Accept')", "button:has-text('Agree')",
    "button:has-text('Got it')", "a:has-text('Accept')",
]


def _click_first_visible(page, selectors, timeout=1500) -> Optional[str]:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=timeout if sel == selectors[0] else 300):
                loc.click(timeout=3000)
                return sel
        except Exception:
            continue
    # also look inside iframes (some CMPs render there)
    for frame in page.frames[1:]:
        for sel in selectors[:8]:
            try:
                loc = frame.locator(sel).first
                if loc.is_visible(timeout=200):
                    loc.click(timeout=3000)
                    return f"iframe:{sel}"
            except Exception:
                continue
    return None


def _is_captcha(page) -> bool:
    u = page.url
    if "/sorry/" in u or "recaptcha" in u:
        return True
    try:
        return page.locator("form#captcha-form, iframe[src*='recaptcha']").count() > 0
    except Exception:
        return False


def _host_matches(href_host: str, domain: str) -> bool:
    h = (href_host or "").lower().removeprefix("www.")
    return h == domain or h.endswith("." + domain)


def _real_target(href: str) -> str:
    """Google sometimes wraps results in /url?q=… — unwrap to the real target."""
    p = urlparse(href)
    if p.path == "/url":
        m = re.search(r"[?&](?:q|url)=([^&]+)", href)
        if m:
            return unquote(m.group(1))
    return href


def _find_serp_result(page, domain: str):
    """Returns (locator, position, href) of the first organic result pointing at domain."""
    links = page.locator("#search a:has(h3), #rso a:has(h3)")
    count = links.count()
    for i in range(count):
        a = links.nth(i)
        try:
            href = _real_target(a.get_attribute("href") or "")
        except Exception:
            continue
        if _host_matches(urlparse(href).hostname, domain):
            return a, i + 1, href
    # Fallback: any link on the results page that points at the domain (e.g. sitelinks)
    anylinks = page.locator("#search a[href], #rso a[href]")
    for i in range(anylinks.count()):
        a = anylinks.nth(i)
        try:
            href = _real_target(a.get_attribute("href") or "")
        except Exception:
            continue
        if _host_matches(urlparse(href).hostname, domain) and a.is_visible():
            return a, None, href
    return None, None, None


def _collect_tracker_values(context, page, cookie_name: str) -> list[dict]:
    """Everything named cookie_name: cookies on any domain + localStorage/sessionStorage."""
    target = cookie_name.lower()
    found = []
    for c in context.cookies():
        if c["name"].lower() == target:
            found.append({"source": "cookie", "domain": c["domain"], "value": c["value"],
                          "exact_name": c["name"]})
    try:
        storage = page.evaluate(
            """(n) => { const out = [];
                for (const [label, s] of [['localStorage', localStorage], ['sessionStorage', sessionStorage]]) {
                  try { for (let i = 0; i < s.length; i++) { const k = s.key(i);
                        if (k.toLowerCase() === n) out.push({source: label, key: k, value: s.getItem(k)}); } }
                  catch (e) {} }
                return out; }""", target)
        for s in storage:
            found.append({"source": s["source"], "domain": urlparse(page.url).hostname,
                          "value": s["value"], "exact_name": s["key"]})
    except Exception:
        pass
    return found


def _norm_value(v: str, case_sensitive: bool) -> str:
    v = unquote(v or "").strip().strip('"').strip("'")
    return v if case_sensitive else v.lower()


CHROME_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def _http_check(api, url: str) -> tuple[str, str, str]:
    """Follows redirects one by one. Returns (first status, final url if redirected, chain)."""
    from urllib.parse import urljoin
    cur = url if re.match(r"^https?://", url, re.I) else "https://" + url
    chain, first = [], ""
    for _ in range(10):
        resp = api.get(cur, max_redirects=0, timeout=20000, fail_on_status_code=False)
        status = resp.status
        first = first or str(status)
        chain.append(f"{status} {cur}")
        loc = resp.headers.get("location")
        resp.dispose()
        if 300 <= status < 400 and loc:
            cur = urljoin(cur, loc)
            continue
        break
    start = url if re.match(r"^https?://", url, re.I) else "https://" + url
    final = cur if cur.rstrip("/") != start.rstrip("/") else ""
    return first, final, " → ".join(chain)


# --------------------------------------------------------------------------- #
# Main check
# --------------------------------------------------------------------------- #

def check_site(browser, site: Site, s: Settings, log: Callable[[str], None] = print, api=None) -> Result:
    r = Result(brand=site.brand, url=site.url, expected_id=site.expected_id, search_query=site.query,
               checked_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    domain = site.domain
    if api is not None and s.check_http:
        try:
            r.http_status, r.redirect_to, r.http_chain = _http_check(api, site.url)
            log(f"[{site.brand}] URL answered {r.http_status}" + (f", redirects to {r.redirect_to}" if r.redirect_to else ""))
        except Exception as e:
            r.http_status, r.http_chain = "—", f"{type(e).__name__}: {str(e).splitlines()[0][:120]}"
    context = browser.new_context(
        locale="en-CA", viewport={"width": 1366, "height": 860},
        user_agent=None,  # keep the real browser UA
    )
    page = context.new_page()
    try:
        # ---- 1. Google search ------------------------------------------------
        log(f"[{site.brand}] Searching Google for “{site.query}”")
        landed_via_google = False
        try:
            page.goto(f"{s.google_domain}/?{s.google_params}", wait_until="domcontentloaded", timeout=30000)
            _click_first_visible(page, GOOGLE_CONSENT_BUTTONS)
            box = page.locator("textarea[name=q], input[name=q]").first
            box.click(timeout=10000)
            box.type(site.query, delay=60)
            box.press("Enter")
            page.wait_for_url(lambda u: "/search" in u or "/sorry/" in u, timeout=15000)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception as e:
            log(f"[{site.brand}] Search box route failed ({type(e).__name__}); using search URL")
            page.goto(f"{s.google_domain}/search?q={quote_plus(site.query)}&{s.google_params}",
                      wait_until="domcontentloaded", timeout=30000)
            _click_first_visible(page, GOOGLE_CONSENT_BUTTONS)

        if _is_captcha(page):
            if not s.headless and s.captcha_wait_seconds > 0:
                log(f"[{site.brand}] Google CAPTCHA shown — solve it in the browser window "
                    f"(waiting up to {s.captcha_wait_seconds}s)")
                deadline = time.time() + s.captcha_wait_seconds
                while time.time() < deadline and _is_captcha(page):
                    page.wait_for_timeout(1000)
            if _is_captcha(page):
                r.status, r.note = "CAPTCHA", "Google blocked the search with a CAPTCHA."

        if r.status != "CAPTCHA":
            try:
                page.wait_for_selector("#search, #rso", timeout=15000)
            except PWTimeout:
                pass
            link, pos, href = _find_serp_result(page, domain)
            if link:
                r.serp_position = str(pos) if pos else "sitelink/other"
                log(f"[{site.brand}] Found {domain} in results (position {r.serp_position}); clicking")
                link.scroll_into_view_if_needed(timeout=5000)
                try:
                    with context.expect_page(timeout=4000) as new_page_info:
                        link.click()
                    page = new_page_info.value  # result opened in a new tab
                except PWTimeout:
                    pass  # opened in the same tab — normal case
                try:
                    page.wait_for_url(lambda u: _host_matches(urlparse(u).hostname, domain), timeout=30000)
                except PWTimeout:
                    pass
                landed_via_google = _host_matches(urlparse(page.url).hostname, domain)
                r.journey = "google-click"
                if not landed_via_google:
                    r.note = f"Clicked the Google result but ended up on {page.url}."
            else:
                r.status = "NOT_IN_SERP"
                r.note = f"{domain} not found on page 1 of Google for “{site.query}”."
                log(f"[{site.brand}] {r.note}")

        # ---- 2. Fallback: open directly, telling the site we came from Google -------
        if not landed_via_google:
            if not s.fallback_direct:
                return r
            url = site.url if re.match(r"^https?://", site.url, re.I) else "https://" + site.url
            log(f"[{site.brand}] Opening {url} directly with a Google referrer (fallback)")
            page = context.new_page()
            page.goto(url, referer=f"{s.google_domain}/", wait_until="domcontentloaded", timeout=45000)
            r.journey = "direct-fallback"

        # ---- 3. Let the site settle, accept cookie banner --------------------------
        try:
            page.wait_for_load_state("load", timeout=30000)
        except PWTimeout:
            pass
        if s.accept_cookie_banner:
            page.wait_for_timeout(1500)
            clicked = _click_first_visible(page, SITE_CONSENT_BUTTONS)
            if clicked:
                log(f"[{site.brand}] Accepted cookie banner ({clicked})")
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PWTimeout:
            pass
        r.landing_url = page.url

        # ---- 4. Poll for the tracker cookie ---------------------------------------
        found = []
        deadline = time.time() + max(1, s.wait_seconds)
        while True:
            found = _collect_tracker_values(context, page, s.cookie_name)
            if found or time.time() >= deadline:
                break
            page.wait_for_timeout(1000)

        # ---- 5. Compare ----------------------------------------------------------
        prev_status = r.status
        if not found:
            r.status = "NOT_FOUND"
            r.note = (r.note + " " if r.note else "") + f"No “{s.cookie_name}” cookie or storage entry found."
        else:
            exp = _norm_value(site.expected_id, s.case_sensitive_match)
            # prefer a cookie on the site's own domain
            found.sort(key=lambda f: (f["source"] != "cookie",
                                      not _host_matches(f["domain"].lstrip("."), domain)))
            match = next((f for f in found if _norm_value(f["value"], s.case_sensitive_match) == exp), None)
            best = match or found[0]
            r.actual_id = unquote(best["value"])
            r.cookie_domain = f'{best["domain"]} ({best["source"]})'
            others = [f'{f["source"]}@{f["domain"]}={unquote(f["value"])}' for f in found if f is not best]
            r.other_values = "; ".join(others)
            r.status = "MATCH" if match else "MISMATCH"
            if not site.expected_id:
                r.status, r.note = "NO_EXPECTED_ID", "Found a value but no expected ID was given."
        if prev_status == "CAPTCHA":
            r.note = "Google CAPTCHA – checked via direct fallback. " + r.note
        elif prev_status == "NOT_IN_SERP":
            r.note = r.note + " Checked via direct fallback."
        r.note = r.note.strip()
        log(f"[{site.brand}] {r.status}  expected={site.expected_id!r} actual={r.actual_id!r}")

    except Exception as e:
        r.status = "ERROR"
        r.note = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
        log(f"[{site.brand}] ERROR {r.note}")
    finally:
        try:
            os.makedirs(s.screenshots_dir, exist_ok=True)
            fn = re.sub(r"[^a-z0-9]+", "-", f"{domain}-{urlparse(site.url if '://' in site.url else 'https://' + site.url).path}".lower()).strip("-") + ".png"
            path = os.path.join(s.screenshots_dir, fn)
            page.screenshot(path=path)
            r.screenshot = path
        except Exception:
            pass
        context.close()
    return r


def launch_browser(p, s: Settings):
    args = ["--disable-blink-features=AutomationControlled"]
    if s.use_installed_chrome:
        try:
            return p.chromium.launch(channel="chrome", headless=s.headless, args=args)
        except Exception:
            pass  # Chrome not installed — use Playwright's Chromium
    return p.chromium.launch(headless=s.headless, args=args)


def run_checks(sites: list[Site], s: Settings, log: Callable[[str], None] = print,
               on_result: Callable[[Result], None] = lambda r: None,
               should_stop: Callable[[], bool] = lambda: False) -> list[Result]:
    results = []
    with sync_playwright() as p:
        browser = launch_browser(p, s)
        api = p.request.new_context(user_agent=CHROME_UA,
                                    extra_http_headers={"Accept-Language": "en-CA,en;q=0.9"})
        try:
            for i, site in enumerate(sites, 1):
                if should_stop():
                    log("Stopped by user.")
                    break
                log(f"--- {i}/{len(sites)}: {site.brand} ({site.domain}) ---")
                res = check_site(browser, site, s, log, api=api)
                results.append(res)
                on_result(res)
                time.sleep(2)  # be gentle with Google between searches
        finally:
            api.dispose()
            browser.close()
    return results


RESULT_COLUMNS = list(Result.__dataclass_fields__.keys())


def results_to_csv(results: list[Result]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=RESULT_COLUMNS)
    w.writeheader()
    for r in results:
        w.writerow(asdict(r))
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description="Check trackerID cookies after a Google → site journey.")
    ap.add_argument("csv", help="CSV with columns: url, expected_id[, search_query]")
    ap.add_argument("--out", default=f"results_{datetime.now():%Y%m%d_%H%M}.csv")
    ap.add_argument("--cookie-name", default="trackerID")
    ap.add_argument("--wait", type=int, default=8, help="seconds to wait for the cookie after landing")
    ap.add_argument("--headless", action="store_true", help="hide the browser (more Google CAPTCHAs)")
    ap.add_argument("--no-fallback", action="store_true", help="don't open the site directly if Google fails")
    ap.add_argument("--no-banner", action="store_true", help="don't auto-accept the site's cookie banner")
    ap.add_argument("--google", default="https://www.google.com", help="e.g. https://www.google.ca")
    a = ap.parse_args()

    with open(a.csv, encoding="utf-8-sig") as f:
        sites = parse_sites(f.read())
    if not sites:
        raise SystemExit("No sites found in the CSV.")
    s = Settings(cookie_name=a.cookie_name, wait_seconds=a.wait, headless=a.headless,
                 fallback_direct=not a.no_fallback, accept_cookie_banner=not a.no_banner,
                 google_domain=a.google.rstrip("/"))
    results = run_checks(sites, s)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        f.write(results_to_csv(results))
    counts = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    print("\nSummary:", ", ".join(f"{k}: {v}" for k, v in counts.items()))
    print("Saved:", a.out)


if __name__ == "__main__":
    main()
