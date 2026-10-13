#!/usr/bin/env python3
"""Compare the cheapest shipped copy of a book across several shops.

Searches JustBooks (GBP, ship to the US, all matches combined), Alibris.com
(non-digital, ship to the US, converted to GBP), Alibris.co.uk (non-digital,
GBP shipping), eBay.com (ship to the US, converted to GBP), eBay.co.uk
(GBP shipping), AwesomeBooks (GBP, free UK delivery) and ZVAB (EUR, shipping
shown on the listing, converted to GBP). Writes a local page and serves it.

Requires Google Chrome and Playwright:

    python3 -m pip install playwright
    python3 compare_books.py --author "J. R. R. Tolkien" --title "The Hobbit"
    python3 compare_books.py --author "J. R. R. Tolkien" --title "The Hobbit" --year 1937
    python3 compare_books.py --author Hengel --title "Die Evangelien" --language German
    python3 compare_books.py --title "Der kleine Hobbit" --language German
    python3 compare_books.py --isbn 978-0-8028-4344-9

Uses a persistent Chrome profile (~/.cache/bookcmp-chrome) so captcha clearance
survives between runs. On each run it opens JustBooks and Alibris in separate
tabs; solve any challenges there, then press Enter to search. Pass
--skip-warmup when clearance is still fresh. --isbn alone is enough, and so is
--title; --author is optional. Dashes and spaces in the ISBN are optional.

Written by Cursor, Auto model, late September / early October 2026.  Copyright
therefore unknown.  Please do not re-use.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_PROFILE = Path.home() / ".cache" / "bookcmp-chrome"
WARMUP_SITES = [
    ("JustBooks", "https://www.justbooks.co.uk/"),
    ("Alibris.com", "https://www.alibris.com/"),
    ("Alibris.co.uk", "https://www.alibris.co.uk/"),
]
CHALLENGE_WAIT_S = 300

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
]

DIGITAL_RE = re.compile(
    r"\b(e-?books?|kindle|audiobooks?|audio\s*books?|audible|mp3|pdf)\b",
    re.I,
)
PHYSICAL_RE = re.compile(
    r"\b(softcover|hardcover|hardback|paperback|mass[- ]market|trade paperback|board book|leather)\b",
    re.I,
)
NOT_A_BOOK_RE = re.compile(
    r"\b(dvd|blu-?ray|vhs|poster|soundtrack|vinyl|cassette|annual|calendar|colouring|coloring|storybook|magazine|journal|diary|boxed set|box set)\b",
    re.I,
)
MONEY_RE = re.compile(
    r"(?P<cur>£|\$|GBP|USD)\s*(?P<amt>[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?|[0-9]+(?:\.[0-9]{2})?)"
)
STOPWORDS = {"the", "and", "for", "with", "from", "that", "this", "into"}


@dataclass
class Match:
    label: str
    title: str = ""
    url: str = ""
    search_url: str = ""
    price_gbp: float | None = None
    price_text: str = ""
    detail: str = ""
    error: str = ""


def find_chrome() -> str:
    override = os.environ.get("CHROME_PATH")
    if override:
        return override
    for candidate in CHROME_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
        if Path(candidate).is_file():
            return candidate
    raise SystemExit("Google Chrome was not found. Set CHROME_PATH to the Chrome binary.")


def resolve_profile(path: str | None) -> Path:
    raw = path or os.environ.get("BOOKCMP_CHROME_PROFILE") or str(DEFAULT_PROFILE)
    profile = Path(raw).expanduser().resolve()
    profile.mkdir(parents=True, exist_ok=True)
    return profile


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def launch_chrome(port: int, profile: Path) -> subprocess.Popen:
    binary = find_chrome()
    proc = subprocess.Popen(
        [
            binary,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--window-size=1280,900",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as resp:
                if resp.status == 200:
                    return proc
        except Exception:
            if proc.poll() is not None:
                raise SystemExit("Chrome exited before remote debugging was ready.")
            time.sleep(0.25)
    proc.terminate()
    raise SystemExit("Chrome did not open a debugging port.")


def fetch_gbp_rate(source: str) -> tuple[float, str]:
    urls = [
        f"https://api.frankfurter.dev/v1/latest?from={source}&to=GBP",
        f"https://api.frankfurter.app/latest?from={source}&to=GBP",
    ]
    for url in urls:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "book-price-compare"})
            with urllib.request.urlopen(request, timeout=20) as resp:
                data = json.loads(resp.read().decode())
            rate = float(data["rates"]["GBP"])
            date = str(data.get("date") or "")
            return rate, date
        except Exception:
            continue
    raise RuntimeError(f"Could not fetch a {source} to GBP rate.")


def fetch_usd_gbp() -> tuple[float, str]:
    return fetch_gbp_rate("USD")


def parse_amount(text: str) -> tuple[float, str] | None:
    match = MONEY_RE.search(text.replace("\xa0", " "))
    if not match:
        return None
    raw = match.group("amt").replace(",", "")
    symbol = match.group("cur")
    currency = "GBP" if symbol in {"£", "GBP"} else "USD"
    return float(raw), currency


def significant_tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [word for word in words if len(word) > 2 and word not in STOPWORDS]


def gbp_of(amount: float, currency: str, usd_rate: float, eur_rate: float | None = None) -> float:
    if currency == "GBP":
        return amount
    if currency == "EUR":
        if eur_rate is None:
            raise RuntimeError("No EUR to GBP rate.")
        return amount * eur_rate
    return amount * usd_rate


def money_text(amount: float, currency: str) -> str:
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency, "")
    return f"{symbol}{amount:.2f}"


def challenge_title(title: str) -> bool:
    lowered = title.lower().strip()
    markers = (
        "just a moment",
        "attention required",
        "verify you are human",
        "security check",
        "captcha",
        "are you a human",
    )
    return lowered.startswith("checking") or any(marker in lowered for marker in markers)


def page_looks_challenged(page) -> bool:
    """True when a bot check / captcha is likely still on screen (title alone is not enough)."""
    try:
        if challenge_title(page.title()):
            return True
    except Exception:
        pass
    try:
        return bool(
            page.evaluate(
                """() => {
                  const text = ((document.title || '') + ' ' + (document.body?.innerText || '')).slice(0, 4000).toLowerCase();
                  if (/just a moment|verify you are (a )?human|attention required|checking your browser|enable javascript and cookies|cf-browser-verification|challenge-platform|press and hold|are you a human/.test(text))
                    return true;
                  return !!document.querySelector(
                    '#challenge-running, #challenge-stage, #cf-challenge-running, #px-captcha, .cf-turnstile, iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], iframe[src*="captcha"]'
                  );
                }"""
            )
        )
    except Exception:
        return False


def wait_out_challenge(page, timeout: float = CHALLENGE_WAIT_S) -> None:
    """Pause while Cloudflare / bot checks are showing so they can be solved in Chrome."""
    if not page_looks_challenged(page):
        return
    print("Challenge page open — solve it in Chrome if needed…", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if not page_looks_challenged(page):
                page.wait_for_timeout(500)
                return
        except Exception:
            page.wait_for_timeout(1000)
            continue
        page.wait_for_timeout(1000)
    raise TimeoutError("Challenge page did not clear in time.")


def wait_ready(page, predicate, timeout: float = 40) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            last = page.title()
        except Exception:
            last = ""
        if page_looks_challenged(page):
            wait_out_challenge(page)
            deadline = time.time() + timeout
            continue
        if predicate():
            return
        page.wait_for_timeout(400)
    raise TimeoutError(f"Page did not become ready (last title: {last!r}).")


def slug(text: str) -> str:
    cleaned = re.sub(r"[^\w\s.'-]", "", text, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", "-", cleaned.strip())
    return urllib.parse.quote(cleaned, safe=".-'")


def isbn_digits(raw: str) -> str:
    return re.sub(r"[^0-9Xx]", "", raw).upper()


def isbn10_check_digit(body9: str) -> str:
    total = sum((10 - i) * int(ch) for i, ch in enumerate(body9))
    remainder = total % 11
    check = (11 - remainder) % 11
    return "X" if check == 10 else str(check)


def isbn13_check_digit(body12: str) -> str:
    total = sum((1 if i % 2 == 0 else 3) * int(ch) for i, ch in enumerate(body12))
    return str((10 - (total % 10)) % 10)


def isbn10_to_isbn13(isbn10: str) -> str:
    body = "978" + isbn10[:9]
    return body + isbn13_check_digit(body)


def isbn13_to_isbn10(isbn13: str) -> str | None:
    if not isbn13.startswith("978"):
        return None
    body9 = isbn13[3:12]
    return body9 + isbn10_check_digit(body9)


def normalize_isbn(raw: str) -> str:
    """Return a compact ISBN-13 (or ISBN-10 when not convertible). Accepts dashes/spaces."""
    cleaned = isbn_digits(raw)
    if len(cleaned) == 10:
        if cleaned[:9].isdigit() and cleaned[9] in "0123456789X" and isbn10_check_digit(cleaned[:9]) == cleaned[9]:
            return isbn10_to_isbn13(cleaned)
        raise ValueError(f"Invalid ISBN-10 check digit: {raw}")
    if len(cleaned) == 13 and cleaned.isdigit():
        if isbn13_check_digit(cleaned[:12]) == cleaned[12]:
            return cleaned
        raise ValueError(f"Invalid ISBN-13 check digit: {raw}")
    raise ValueError(f"ISBN must be 10 or 13 digits (dashes/spaces optional): {raw}")


def isbn_variants(isbn: str | None) -> set[str]:
    if not isbn:
        return set()
    variants = {isbn, isbn_digits(isbn)}
    as10 = isbn13_to_isbn10(isbn) if len(isbn) == 13 else None
    if as10:
        variants.add(as10)
    if len(isbn) == 10:
        variants.add(isbn10_to_isbn13(isbn))
    return {item for item in variants if item}


def text_has_isbn(text: str, isbn: str | None) -> bool:
    if not isbn:
        return True
    compact = isbn_digits(text)
    return any(variant in compact for variant in isbn_variants(isbn))


def alibris_search_url(
    domain: str,
    author: str,
    title: str,
    year: int | None = None,
    isbn: str | None = None,
) -> str:
    if isbn:
        url = f"https://www.{domain}/search/books/isbn/{isbn}?qsort=p"
    elif author and title:
        url = f"https://www.{domain}/search/books/author/{slug(author)}/title/{slug(title)}?qsort=p"
    else:
        keyword = title or author
        url = f"https://www.{domain}/booksearch?mtype=B&keyword={urllib.parse.quote_plus(keyword)}&qsort=p"
    if year is not None:
        url += f"&yeargte={year}&yearlte={year}"
    return url


def text_has_year(text: str, year: int | None) -> bool:
    """True if year is unset, listing has no year, or listing mentions that year."""
    if year is None:
        return True
    years = {int(match) for match in re.findall(r"\b(?:1[0-9]{3}|20[0-9]{2})\b", text)}
    return not years or year in years


# JustBooks "books written in" codes: ANY, EN, DE, FR, ES, IT, NL.
LANGUAGES = {
    "en": ("EN", "English"),
    "english": ("EN", "English"),
    "de": ("DE", "German"),
    "ger": ("DE", "German"),
    "german": ("DE", "German"),
    "deutsch": ("DE", "German"),
    "fr": ("FR", "French"),
    "french": ("FR", "French"),
    "es": ("ES", "Spanish"),
    "spanish": ("ES", "Spanish"),
    "it": ("IT", "Italian"),
    "italian": ("IT", "Italian"),
    "nl": ("NL", "Dutch"),
    "dutch": ("NL", "Dutch"),
    "nederlands": ("NL", "Dutch"),
    "any": ("ANY", "any language"),
}
# ZVAB lang= values are ISO 639-2/T codes. Bibliographic codes (ger, fre, dut) are ignored.
ZVAB_LANG = {
    "EN": "eng",
    "DE": "deu",
    "FR": "fra",
    "ES": "spa",
    "IT": "ita",
    "NL": "nld",
}


def normalize_language(raw: str) -> tuple[str, str]:
    """Return (JustBooks code, display name). Accepts names or codes."""
    key = " ".join((raw or "").strip().lower().split())
    if key not in LANGUAGES:
        raise ValueError(
            f"Unknown language {raw!r}. "
            "Use English, German, French, Spanish, Italian, Dutch, or any "
            "(codes EN, DE, FR, ES, IT, NL, ANY)."
        )
    return LANGUAGES[key]


def display_heading(
    author: str,
    title: str,
    isbn: str | None,
    year: int | None = None,
    language_name: str | None = None,
) -> tuple[str, str]:
    heading = title or (f"ISBN {isbn}" if isbn else "Book")
    bits = [
        bit
        for bit in (
            author,
            f"ISBN {isbn}" if isbn else "",
            str(year) if year is not None else "",
            language_name or "",
        )
        if bit
    ]
    return heading, " · ".join(bits)


def goto(page, url: str) -> None:
    last_error = None
    for _ in range(3):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            wait_out_challenge(page)
            return
        except TimeoutError:
            raise
        except Exception as exc:
            last_error = exc
            if "interrupted" not in str(exc).lower():
                raise
            page.wait_for_timeout(1000)
    if last_error:
        raise last_error


def warmup(page) -> None:
    """Open each tricky site in its own tab so a slow JustBooks captcha is not replaced."""
    print("Warming up sites — each opens in its own tab so challenges are not replaced…", flush=True)
    context = page.context
    # Reuse the launch tab for the first site so Chrome does not keep an extra blank page.
    tabs = []
    extra_tabs = []
    for index, (name, url) in enumerate(WARMUP_SITES):
        print(f"  Opening {name}…", flush=True)
        tab = page if index == 0 else context.new_page()
        if index > 0:
            extra_tabs.append(tab)
        tabs.append((name, tab))
        try:
            tab.goto(url, wait_until="domcontentloaded", timeout=60000)
            tab.bring_to_front()
        except Exception as exc:
            print(f"  {name} failed to open: {exc}", flush=True)
    if tabs:
        try:
            tabs[0][1].bring_to_front()
        except Exception:
            pass
    print("Solve any captchas in those tabs (JustBooks is often slow).", flush=True)
    input("Press Enter when all challenges are cleared and you're ready to search… ")
    for tab in extra_tabs:
        try:
            tab.close()
        except Exception:
            pass
    try:
        page.bring_to_front()
    except Exception:
        pass


def set_alibris_currency(page, domain: str, code: str) -> None:
    # The search form remembers the last query. This portal action reruns it in the chosen currency.
    change = (
        f"https://www.{domain}/portals/alibrisPortal.portal?"
        "_nfpb=true&_windowLabel=booksearch"
        "&booksearch_actionOverride=%2Falibris%2Fjump%2FsearchResult%2FchangeCurrency"
        "&_pageLabel=alibrisPage_bookSearchResult"
        f"&currencyCode={code}"
    )
    goto(page, change)
    page.wait_for_timeout(1200)


def extract_alibris_works(page) -> list[dict]:
    return page.evaluate(
        """() => [...document.querySelectorAll('li')].filter(li => li.querySelector('h2 a') && /See All/.test(li.innerText)).map(li => {
          const link = li.querySelector('h2 a');
          const see = [...li.querySelectorAll('a')].find(a => /See All/.test(a.innerText));
          return {
            title: (link?.innerText || '').trim(),
            href: link?.getAttribute('href') || '',
            see: see?.getAttribute('href') || '',
            text: li.innerText.replace(/\\s+/g, ' ').slice(0, 500),
          };
        })"""
    )


def extract_alibris_copies(page) -> list[dict]:
    return page.evaluate(
        """() => [...document.querySelectorAll('li.product-container')].map(li => {
          const priceP = li.querySelector('td.price p');
          let itemText = '';
          if (priceP) {
            itemText = [...priceP.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ');
          }
          const ship = (li.querySelector('table.more-details') || li.querySelector('.toggle-table'))?.innerText || '';
          const button = li.querySelector('[id*="add-to-cart-"]');
          const idMatch = button?.id?.match(/(\\d+)$/);
          return {
            binding: (li.querySelector('td.product p')?.innerText || '').trim(),
            seller: (li.querySelector('a.seller-link')?.innerText || '').trim(),
            place: (li.querySelector('td.seller')?.innerText || '').replace(/\\s+/g, ' ').trim(),
            itemText,
            ship,
            text: li.innerText.replace(/\\s+/g, ' ').slice(0, 800),
            invid: idMatch ? idMatch[1] : '',
          };
        })"""
    )


def shipping_amount(ship_text: str) -> tuple[float, str] | None:
    if re.search(r"\bfree\s+shipping\b", ship_text, re.I):
        currency = "GBP" if "£" in ship_text else "USD"
        if "£" in ship_text:
            currency = "GBP"
        elif "$" in ship_text:
            currency = "USD"
        else:
            currency = ""
        return 0.0, currency
    amounts = []
    for line in ship_text.splitlines():
        if "shipping" not in line.lower():
            continue
        parsed = parse_amount(line)
        if parsed:
            amounts.append(parsed)
    if not amounts:
        parsed = parse_amount(ship_text)
        if parsed and "shipping" in ship_text.lower():
            amounts.append(parsed)
    if not amounts:
        return None
    return min(amounts, key=lambda item: item[0])


def alibris_match(
    page,
    domain: str,
    author: str,
    title: str,
    currency_code: str,
    rate: float,
    rate_note: str,
    year: int | None = None,
    isbn: str | None = None,
) -> Match:
    label = f"{domain} match"
    search_url = alibris_search_url(domain, author, title, year, isbn)
    try:
        goto(page, search_url)
        wait_ready(page, lambda: "alibris" in page.title().lower() or page.locator("h2 a").count() > 0)
        set_alibris_currency(page, domain, currency_code)
        goto(page, search_url)
        wait_ready(page, lambda: page.locator("h2 a").count() > 0 or "matching" in page.inner_text("body").lower())
        page.wait_for_timeout(800)
        body = page.inner_text("body")
        if currency_code == "USD" and "$" not in body:
            raise RuntimeError("Alibris.com stayed off US dollars.")
        if currency_code == "GBP" and "£" not in body:
            raise RuntimeError("Alibris.co.uk did not show British pounds.")
        works = extract_alibris_works(page)
        if not works and page.locator("li.product-container").count():
            # Author/title search often opens one book's copy list instead of a "See All" title list.
            heading = page.evaluate(
                """() => (document.querySelector('h1')?.innerText || document.title || '').split(':')[0].trim()"""
            )
            heading_text = page.evaluate("""() => (document.querySelector('h1')?.innerText || document.title || '')""")
            works = [{"title": heading or title, "href": page.url, "see": page.url, "text": heading_text or "paperback"}]
    except Exception as exc:
        return Match(label=label, search_url=search_url, error=str(exc))

    physical = []
    for work in works:
        text = work.get("text") or ""
        if DIGITAL_RE.search(text) and not PHYSICAL_RE.search(text):
            continue
        if not text_has_year(text, year):
            continue
        from_price = parse_amount(text[text.lower().find("see all"):] if "see all" in text.lower() else text)
        physical.append((from_price[0] if from_price else 10**9, work))
    physical.sort(key=lambda item: item[0])
    if not physical:
        return Match(label=label, search_url=search_url, error="No non-digital matches.")

    best: dict | None = None
    pages_capped = False
    for from_amount, work in physical[:8]:
        if best is not None and from_amount >= best["total"]:
            break
        href = work.get("see") or work.get("href") or ""
        copies_url = urllib.parse.urljoin(f"https://www.{domain}/", href)
        parts = urllib.parse.urlsplit(copies_url)
        query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        query["qsort"] = "p"
        if year is not None:
            query.setdefault("yeargte", str(year))
            query.setdefault("yearlte", str(year))
        copies_url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
        try:
            goto(page, copies_url)
            wait_ready(page, lambda: page.locator("li.product-container").count() > 0 or "copies" in page.inner_text("body").lower())
        except Exception:
            continue
        for _ in range(4):
            page.wait_for_timeout(600)
            copies = extract_alibris_copies(page)
            item_prices = []
            for copy in copies:
                if DIGITAL_RE.search(copy.get("binding") or ""):
                    continue
                if not text_has_year(copy.get("text") or "", year):
                    continue
                item = parse_amount(copy.get("itemText") or "")
                ship = shipping_amount(copy.get("ship") or "")
                if not item or ship is None:
                    continue
                ship_amount, ship_currency = ship
                currency = item[1]
                if ship_currency in {"USD", "GBP"}:
                    currency = ship_currency
                total = item[0] + ship_amount
                item_prices.append(item[0])
                if best is None or total < best["total"] - 1e-9:
                    invid = copy.get("invid") or ""
                    url = f"https://www.{domain}/booksearch.detail?invid={invid}" if invid else copies_url
                    best = {
                        "total": total,
                        "currency": currency,
                        "title": work.get("title") or title,
                        "url": url,
                        "binding": copy.get("binding") or "",
                        "seller": copy.get("seller") or "",
                        "place": copy.get("place") or "",
                        "item": item[0],
                        "ship": ship_amount,
                    }
            if not item_prices:
                break
            if best is not None and max(item_prices) >= best["total"] - 1e-9:
                break
            nxt = page.locator("a.prev-next", has_text="Next")
            if nxt.count() == 0:
                break
            before = page.locator("a.seller-link").first.inner_text() if page.locator("a.seller-link").count() else ""
            nxt.first.click()
            page.wait_for_timeout(1200)
            after = page.locator("a.seller-link").first.inner_text() if page.locator("a.seller-link").count() else ""
            if after == before:
                pages_capped = True
                break
        else:
            pages_capped = True

    if best is None:
        return Match(label=label, search_url=search_url, error="No priced non-digital copy with shipping was listed.")

    native = money_text(best["total"], best["currency"])
    gbp = gbp_of(best["total"], best["currency"], rate)
    if best["currency"] == "USD":
        price_text = f"£{gbp:.2f} ({native} at {rate:.4f} GBP per USD{', ' + rate_note if rate_note else ''})"
    else:
        price_text = f"£{gbp:.2f}"
    detail = (
        f"{best['binding']}; {best['seller']}; item {money_text(best['item'], best['currency'])}"
        f" + standard shipping {money_text(best['ship'], best['currency'])}"
    )
    if pages_capped:
        detail += ". Stopped after four copy-list pages; a later page could be cheaper if shipping drops to zero."
    if year is not None:
        detail += f" Publication year {year}."
    if isbn:
        detail += f" ISBN {isbn}."
    return Match(
        label=label,
        title=best["title"],
        url=best["url"],
        search_url=search_url,
        price_gbp=gbp,
        price_text=price_text,
        detail=detail.strip(),
    )


def justbooks_match(
    page,
    author: str,
    title: str,
    year: int | None = None,
    isbn: str | None = None,
    language: str = "EN",
) -> Match:
    label = "justbooks match"
    language_name = next((name for code, name in LANGUAGES.values() if code == language), language)
    params = {
        "author": author,
        "title": title,
        "language": language,
        "condition": "ANY",
        "binding": "ANY",
        "currency": "GBP",
        "destination": "US",
        "viewAll": "true",
        "mode": "BASIC",
        "firstEdition": "false",
        "signed": "false",
        "noPrintOnDemand": "false",
        "noIsbn": "false",
    }
    if isbn:
        params["isbn"] = isbn
    if year is not None:
        params["publicationMinYear"] = str(year)
        params["publicationMaxYear"] = str(year)
    search_url = "https://www.justbooks.co.uk/search?" + urllib.parse.urlencode(params)
    try:
        goto(page, search_url)
        offers = []
        deadline = time.time() + 45
        while time.time() < deadline:
            if page_looks_challenged(page):
                wait_out_challenge(page)
                deadline = time.time() + 45
                continue
            combined = page.locator("a", has_text="View all matches combined")
            if combined.count() and page.locator("[data-test-id^='search-offer-card']").count() == 0:
                try:
                    combined.first.click(timeout=2000)
                    page.wait_for_timeout(800)
                    if page_looks_challenged(page):
                        wait_out_challenge(page)
                        deadline = time.time() + 45
                        continue
                except Exception:
                    pass
            offers = page.evaluate(
                """() => [...document.querySelectorAll('[data-test-id^="search-offer-card"]')].map(card => {
                  const id = card.getAttribute('data-test-id') || '';
                  const buy = [...card.querySelectorAll('a[href]')].find(a => /^https?:/i.test(a.href) && !a.href.includes('justbooks.co.uk'));
                  const ship = (card.innerText.match(/Includes shipping:\\s*[£$][0-9,.]+/i) || [''])[0];
                  return {
                    id,
                    title: card.getAttribute('data-csa-c-title') || '',
                    authors: card.getAttribute('data-csa-c-authors') || '',
                    seller: card.getAttribute('data-csa-c-seller') || '',
                    condition: card.getAttribute('data-csa-c-condition') || '',
                    binding: card.getAttribute('data-csa-c-binding') || '',
                    isbn: card.getAttribute('data-csa-c-isbn') || '',
                    href: buy ? buy.href : '',
                    ship,
                    text: card.innerText.slice(0, 500),
                  };
                })"""
            )
            if any(re.search(r"£\s*\d", offer.get("text") or "") for offer in offers):
                break
            page.wait_for_timeout(400)
    except Exception as exc:
        return Match(label=label, search_url=search_url, error=str(exc))

    title_tokens = significant_tokens(title)
    author_tokens = significant_tokens(author)
    best = None
    for offer in offers:
        test_id = offer.get("id") or ""
        if "RENTAL" in test_id and "NON-RENTAL" not in test_id:
            continue
        offer_title = offer.get("title") or ""
        offer_authors = offer.get("authors") or ""
        blob = " ".join([offer_title, offer_authors, offer.get("text") or ""])
        if DIGITAL_RE.search(blob):
            continue
        if not text_has_year(blob, year):
            continue
        if isbn:
            offer_isbn = offer.get("isbn") or ""
            if offer_isbn and not text_has_isbn(offer_isbn, isbn):
                continue
        else:
            title_hay = offer_title or blob
            author_hay = offer_authors or blob
            if title_tokens and not all(token in title_hay.lower() for token in title_tokens):
                continue
            if author_tokens and not any(token in author_hay.lower() for token in author_tokens):
                continue
        # The first pound amount is the total. "Includes shipping" is a later, smaller figure.
        parsed = parse_amount(offer.get("text") or "")
        if not parsed or parsed[1] != "GBP":
            continue
        total = parsed[0]
        if best is None or total < best["total"]:
            best = {"total": total, **offer}
    if best is None:
        return Match(label=label, search_url=search_url, error="No GBP offers were listed.")
    ship = best.get("ship") or "shipping included in the total"
    extra = ""
    if year is not None:
        extra += f" Publication year {year}."
    if isbn:
        extra += f" ISBN {isbn}."
    extra += f" Books written in {language_name}."
    binding = best.get("binding") or ""
    who = best.get("authors") or "seller"
    detail_bits = [best.get("condition") or "Any"]
    if binding:
        detail_bits.append(binding)
    detail_bits.append(best.get("seller") or who)
    detail_bits.append(ship)
    return Match(
        label=label,
        title=best.get("title") or title or (f"ISBN {isbn}" if isbn else ""),
        url=best.get("href") or search_url,
        search_url=search_url,
        price_gbp=best["total"],
        price_text=f"£{best['total']:.2f}",
        detail=(
            f"{'; '.join(detail_bits)}. "
            f"GBP, standard shipping to the United States, all matches combined.{extra}"
        ),
    )


def ebay_cards(page) -> list[dict]:
    return page.evaluate(
        """() => [...document.querySelectorAll('li.s-card')].map(card => {
          const link = [...card.querySelectorAll('a.s-card__link')].find(a => (a.href || '').includes('/itm/'));
          const title = (card.querySelector('.s-card__title')?.innerText || '').split('\\n')[0].trim();
          const price = card.querySelector('.s-card__price')?.innerText || '';
          const rows = [...card.querySelectorAll('.s-card__attribute-row, .s-card__subtitle, .s-card__separator')].map(e => e.innerText.trim());
          return {title, price, href: link ? link.href : '', rows, text: card.innerText.slice(0, 700)};
        })"""
    )


def ebay_shipping(text: str) -> tuple[float, str] | None:
    if re.search(r"does not ship|shipping not specified|postage not specified", text, re.I):
        return None
    if re.search(r"\bfree\b[^.\n]{0,40}\b(delivery|postage|shipping)\b", text, re.I):
        return 0.0, "GBP" if "£" in text else "USD"
    match = re.search(
        r"\+\s*(?P<cur>£|\$)\s*(?P<amt>[0-9,.]+)\s*(delivery|postage|shipping)",
        text,
        re.I,
    )
    if not match:
        return None
    amount = float(match.group("amt").replace(",", ""))
    currency = "GBP" if match.group("cur") == "£" else "USD"
    return amount, currency


def ebay_match(
    page,
    domain: str,
    author: str,
    title: str,
    fcid: str,
    postal: str,
    rate: float,
    rate_note: str,
    year: int | None = None,
    isbn: str | None = None,
) -> Match:
    label = f"{domain} match"
    if isbn:
        query = isbn
    else:
        query = f"{title} {author}".strip()
        if year is not None:
            query = f"{query} {year}"
    search_url = (
        f"https://www.{domain}/sch/i.html?"
        + urllib.parse.urlencode(
            {
                "_nkw": query,
                "_sop": "15",
                "LH_BIN": "1",
                "_sacat": "267",
                "_ipg": "60",
                "_fcid": fcid,
                "_stpos": postal,
            }
        )
    )
    tokens = significant_tokens(title) or ([] if isbn else significant_tokens(query))
    try:
        goto(page, f"https://www.{domain}/")
        page.wait_for_timeout(600)
        goto(page, search_url)
        wait_ready(page, lambda: page.locator("li.s-card").count() > 0 or "ebay" in page.title().lower())
        page.wait_for_timeout(1200)
        if "Shipping to" not in page.inner_text("body"):
            goto(page, search_url)
            page.wait_for_timeout(1500)
        cards = ebay_cards(page)
    except Exception as exc:
        return Match(label=label, search_url=search_url, error=str(exc))

    best = None
    for card in cards:
        listing_title = card.get("title") or ""
        if not listing_title or listing_title.lower() == "shop on ebay":
            continue
        blob = listing_title + " " + (card.get("text") or "")
        lowered = listing_title.lower()
        if not isbn:
            author_tokens = significant_tokens(author)
            if not all(token in lowered for token in tokens):
                continue
            if author_tokens and not any(token in lowered for token in author_tokens):
                continue
            query_blob = f"{title} {author}".lower()
            if any(word.lower() not in query_blob for word in NOT_A_BOOK_RE.findall(listing_title)):
                continue
        if DIGITAL_RE.search(blob):
            continue
        if not text_has_year(blob, year):
            continue
        price = parse_amount(card.get("price") or "")
        if not price:
            continue
        ship = ebay_shipping(card.get("text") or "")
        if ship is None:
            continue
        currency = price[1]
        total = price[0] + ship[0]
        if best is None or total < best["total"]:
            best = {
                "total": total,
                "currency": currency,
                "title": listing_title,
                "url": card.get("href") or search_url,
                "item": price[0],
                "ship": ship[0],
            }
    if best is None:
        return Match(label=label, search_url=search_url, error="No buy-it-now book with a shipping price matched the title.")
    native = money_text(best["total"], best["currency"])
    gbp = gbp_of(best["total"], best["currency"], rate)
    if best["currency"] == "USD":
        price_text = f"£{gbp:.2f} ({native} at {rate:.4f} GBP per USD{', ' + rate_note if rate_note else ''})"
    else:
        price_text = f"£{gbp:.2f}"
    where = "United States" if domain == "ebay.com" else "United Kingdom"
    extra = ""
    if year is not None:
        extra += f" Publication year {year}."
    if isbn:
        extra += f" ISBN {isbn}."
    return Match(
        label=label,
        title=best["title"],
        url=best["url"],
        search_url=search_url,
        price_gbp=gbp,
        price_text=price_text,
        detail=(
            f"Buy It Now; item {money_text(best['item'], best['currency'])}"
            f" + shipping {money_text(best['ship'], best['currency'])} to {where}.{extra}"
        ),
    )


def awesomebooks_match(
    page,
    author: str,
    title: str,
    year: int | None = None,
    isbn: str | None = None,
) -> Match:
    label = "awesomebooks.com match"
    if isbn:
        query = isbn
    else:
        query = f"{author} {title}".strip()
        if year is not None:
            query = f"{query} {year}"
    search_url = "https://www.awesomebooks.com/search/advanced?" + urllib.parse.urlencode(
        {"q": query, "sortBy": "price_asc"}
    )
    tokens = significant_tokens(title) or ([] if isbn else significant_tokens(query))
    author_tokens = significant_tokens(author)
    try:
        goto(page, search_url)
        wait_ready(
            page,
            lambda: page.locator("li.ais-Hits-item").count() > 0 or "result" in page.title().lower(),
            timeout=40,
        )
        page.wait_for_timeout(800)
        if "£" not in page.inner_text("body"):
            raise RuntimeError("AwesomeBooks did not show British pounds.")
    except Exception as exc:
        return Match(label=label, search_url=search_url, error=str(exc))

    best = None
    seen_urls = set()
    for _ in range(5):
        payload = page.evaluate(
            """() => {
              const items = [...document.querySelectorAll('li.ais-Hits-item')].map(li => ({
                title: (li.querySelector('.product-item__title')?.innerText || '').trim(),
                href: li.querySelector('a[href*="/book/"]')?.href || '',
                text: li.innerText.replace(/\\s+/g, ' ').trim(),
              }));
              const pages = [...document.querySelectorAll('a')].map(a => ({
                text: a.innerText.trim(),
                href: a.href || '',
              })).filter(a => /^\\d+$/.test(a.text) && a.href);
              return {items, pages};
            }"""
        )
        for card in payload.get("items") or []:
            listing = card.get("title") or ""
            blob = f"{listing} {card.get('text') or ''}"
            lowered = blob.lower()
            if not isbn:
                if tokens and not all(token in lowered for token in tokens):
                    continue
                if author_tokens and not any(token in lowered for token in author_tokens):
                    continue
                query_blob = f"{title} {author}".lower()
                if any(word.lower() not in query_blob for word in NOT_A_BOOK_RE.findall(listing)):
                    continue
            if DIGITAL_RE.search(blob):
                continue
            if not text_has_year(blob, year):
                continue
            amounts = []
            for raw in re.findall(r"£\s*[0-9][0-9,]*(?:\.[0-9]{2})?", blob):
                parsed = parse_amount(raw)
                if parsed and parsed[1] == "GBP":
                    amounts.append(parsed[0])
            if not amounts:
                continue
            price = min(amounts)
            if best is None or price < best["price"]:
                condition = "Used" if re.search(r"\bused\b", blob, re.I) else "New" if re.search(r"\bnew\b", blob, re.I) else ""
                best = {
                    "price": price,
                    "title": listing or title or (f"ISBN {isbn}" if isbn else ""),
                    "url": card.get("href") or search_url,
                    "condition": condition,
                }
        if best is not None:
            break
        current = page.url.rstrip("/")
        next_href = ""
        numbered = []
        for link in payload.get("pages") or []:
            href = (link.get("href") or "").rstrip("/")
            text = link.get("text") or ""
            if href and text.isdigit():
                numbered.append((int(text), href))
        for _, href in sorted(numbered):
            if href not in seen_urls and href != current:
                next_href = href
                break
        if not next_href:
            break
        seen_urls.add(current)
        try:
            goto(page, next_href)
            page.wait_for_timeout(800)
        except Exception:
            break

    if best is None:
        return Match(label=label, search_url=search_url, error="No GBP copy matched the title.")
    extra = ""
    if year is not None:
        extra += f" Publication year {year}."
    if isbn:
        extra += f" ISBN {isbn}."
    return Match(
        label=label,
        title=best["title"],
        url=best["url"],
        search_url=search_url,
        price_gbp=best["price"],
        price_text=f"£{best['price']:.2f}",
        detail=f"{best['condition']}; item £{best['price']:.2f} + free UK delivery.{extra}",
    )


def zvab_search_url(
    author: str,
    title: str,
    year: int | None = None,
    isbn: str | None = None,
    language: str = "EN",
) -> str:
    params = {"sortby": "17", "rollup": "off", "dym": "off"}
    if isbn:
        params["isbn"] = isbn
    else:
        if title:
            params["tn"] = title
        if author:
            params["an"] = author
    if year is not None:
        params["yrl"] = str(year)
        params["yrh"] = str(year)
    zvab_lang = ZVAB_LANG.get(language)
    if zvab_lang:
        params["lang"] = zvab_lang
    return "https://www.zvab.com/servlet/SearchResults?" + urllib.parse.urlencode(params)


def zvab_listings(page) -> list[dict]:
    return page.evaluate(
        """() => [...document.querySelectorAll('[data-srp-item-role="listing"]')].map(li => {
          const basket = li.querySelector('[data-test-id^="add-to-basket"]');
          const cost = basket?.getAttribute('data-csa-c-cost');
          const ship = basket?.getAttribute('data-csa-c-shipping-cost');
          const note = [...li.querySelectorAll('.VersoVisuallyHidden')]
            .map(el => (el.textContent || '').replace(/\\s+/g, ' ').trim())
            .find(text => text.startsWith('Versand')) || '';
          return {
            title: (li.querySelector('[data-test-id="listing-title"]')?.innerText || '').trim(),
            author: (li.querySelector('[data-test-id="listing-author"]')?.innerText || '').trim(),
            href: li.querySelector('[data-test-id="listing-title-link"]')?.href || '',
            condition: (li.querySelector('[data-test-id="listing-condition"]')?.innerText || '').trim(),
            seller: (li.querySelector('[data-test-id="listing-seller-link"]')?.innerText || '').trim(),
            isbn: (li.querySelector('[data-test-id^="isbn-"]')?.innerText || '').trim(),
            item: cost === null || cost === '' ? null : Number(cost),
            ship: ship === null || ship === '' ? null : Number(ship),
            currency: basket?.getAttribute('data-csa-c-purchase-currency') || '',
            note,
            text: (li.innerText || '').replace(/\\s+/g, ' ').slice(0, 900),
          };
        })"""
    )


def zvab_match(
    page,
    author: str,
    title: str,
    usd_rate: float,
    eur_rate: float,
    rate_note: str,
    year: int | None = None,
    isbn: str | None = None,
    language: str = "EN",
    language_name: str = "English",
) -> Match:
    label = "zvab.com match"
    search_url = zvab_search_url(author, title, year, isbn, language)
    tokens = significant_tokens(title)
    author_tokens = significant_tokens(author)
    best = None
    try:
        goto(page, search_url)
        for _ in range(4):
            wait_ready(
                page,
                lambda: page.locator('[data-srp-item-role="listing"]').count() > 0
                or "ergebnis" in page.inner_text("body").lower(),
                timeout=40,
            )
            page.wait_for_timeout(600)
            for card in zvab_listings(page):
                listing = card.get("title") or ""
                if not listing:
                    continue
                blob = " ".join(
                    part
                    for part in (listing, card.get("author") or "", card.get("isbn") or "", card.get("text") or "")
                    if part
                )
                if not isbn:
                    hay = listing.lower()
                    if tokens and not all(token in hay for token in tokens):
                        continue
                    if author_tokens and not any(token in blob.lower() for token in author_tokens):
                        continue
                    query_blob = f"{title} {author}".lower()
                    if any(word.lower() not in query_blob for word in NOT_A_BOOK_RE.findall(listing)):
                        continue
                else:
                    card_isbn = card.get("isbn") or ""
                    if card_isbn and not text_has_isbn(card_isbn, isbn):
                        continue
                if DIGITAL_RE.search(blob):
                    continue
                if not text_has_year(blob, year):
                    continue
                item = card.get("item")
                ship = card.get("ship")
                currency = card.get("currency") or ""
                if item is None or ship is None or currency not in {"EUR", "GBP", "USD"}:
                    continue
                if item != item or ship != ship:
                    continue
                total = float(item) + float(ship)
                gbp = gbp_of(total, currency, usd_rate, eur_rate)
                if best is None or gbp < best["gbp"]:
                    best = {
                        "gbp": gbp,
                        "total": total,
                        "currency": currency,
                        "item": float(item),
                        "ship": float(ship),
                        "title": listing,
                        "url": card.get("href") or search_url,
                        "condition": card.get("condition") or "",
                        "seller": card.get("seller") or "",
                        "note": card.get("note") or "",
                    }
            if best is not None:
                break
            next_href = page.evaluate(
                """() => document.querySelector('[data-test-id="next-page"]')?.href || ''"""
            )
            if not next_href or next_href == page.url:
                break
            goto(page, next_href)
    except Exception as exc:
        return Match(label=label, search_url=search_url, error=str(exc))

    if best is None:
        return Match(label=label, search_url=search_url, error="No priced copy matched the title.")
    native = money_text(best["total"], best["currency"])
    if best["currency"] == "EUR":
        price_text = (
            f"£{best['gbp']:.2f} ({native} at {eur_rate:.4f} GBP per EUR"
            f"{', ' + rate_note if rate_note else ''})"
        )
    elif best["currency"] == "USD":
        price_text = (
            f"£{best['gbp']:.2f} ({native} at {usd_rate:.4f} GBP per USD"
            f"{', ' + rate_note if rate_note else ''})"
        )
    else:
        price_text = f"£{best['gbp']:.2f}"
    ship_text = "free shipping" if best["ship"] == 0 else f"shipping {money_text(best['ship'], best['currency'])}"
    extra = ""
    if best.get("note"):
        extra += f" {best['note']}."
    if year is not None:
        extra += f" Publication year {year}."
    if isbn:
        extra += f" ISBN {isbn}."
    extra += f" Books written in {language_name}."
    bits = [bit for bit in (best["condition"], best["seller"]) if bit]
    item_bit = f"item {money_text(best['item'], best['currency'])} + {ship_text}."
    lead = "; ".join(bits)
    detail = f"{lead}; {item_bit}{extra}" if lead else f"{item_bit}{extra}"
    return Match(
        label=label,
        title=best["title"],
        url=best["url"],
        search_url=search_url,
        price_gbp=best["gbp"],
        price_text=price_text,
        detail=detail.strip(),
    )


def render_page(
    author: str,
    title: str,
    matches: list[Match],
    rate: float,
    rate_note: str,
    year: int | None = None,
    isbn: str | None = None,
    language_name: str = "English",
    eur_rate: float | None = None,
    eur_note: str = "",
) -> str:
    priced = [item for item in matches if item.price_gbp is not None]
    cheapest = min(priced, key=lambda item: item.price_gbp) if priced else None
    rows = []
    for item in matches:
        is_best = cheapest is not None and item is cheapest
        price = html.escape(item.price_text or "—")
        if item.error:
            body = f"<p class='error'>{html.escape(item.error)}</p>"
        else:
            body = (
                f"<p class='listing'>{html.escape(item.title)}</p>"
                f"<p class='price'>{price}</p>"
                f"<p class='detail'>{html.escape(item.detail)}</p>"
                f"<p class='links'><a href='{html.escape(item.url, quote=True)}'>Open this listing</a>"
                f" · <a href='{html.escape(item.search_url, quote=True)}'>Open the search</a></p>"
            )
        badge = "<span class='badge'>Cheapest</span>" if is_best else ""
        rows.append(
            f"<article class='card{' best' if is_best else ''}'>"
            f"<h2>{html.escape(item.label)} {badge}</h2>{body}</article>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — book prices</title>
<style>
  body {{ margin: 0; font: 16px/1.45 "Iowan Old Style", Palatino, Georgia, serif; background: #f4f0e6; color: #1c1915; }}
  main {{ max-width: 820px; margin: 0 auto; padding: 32px 20px 64px; }}
  h1 {{ font-size: 1.8rem; margin-bottom: 0.2rem; }}
  .query {{ color: #5c564c; margin-top: 0; }}
  .card {{ background: #fffdf8; border: 1px solid #ddd4c4; border-radius: 12px; padding: 16px 18px; margin: 14px 0; }}
  .card.best {{ border-color: #2f6f4e; box-shadow: inset 4px 0 0 #2f6f4e; }}
  h2 {{ font-size: 1.05rem; margin: 0 0 8px; }}
  .badge {{ display: inline-block; margin-left: 8px; background: #2f6f4e; color: white; border-radius: 999px; padding: 2px 8px; font: 12px/1.4 sans-serif; vertical-align: 2px; }}
  .price {{ font-size: 1.35rem; margin: 6px 0; }}
  .detail, .links, .error {{ margin: 6px 0; }}
  .detail {{ color: #3f3a33; }}
  a {{ color: #1d4e89; }}
  .error {{ color: #8a2b2b; }}
  footer {{ color: #5c564c; font-size: 0.92rem; }}
</style>
</head>
<body>
<main>
  <h1>{html.escape(title)}</h1>
  <p class="query">{html.escape(author)}</p>
  {''.join(rows)}
  <footer>
    <p>USD prices are converted at {rate:.5f} GBP per USD{(' (' + html.escape(rate_note) + ')') if rate_note else ''}.
    {f'EUR prices are converted at {eur_rate:.5f} GBP per EUR' + ((' (' + html.escape(eur_note) + ')') if eur_note else '') + '. ' if eur_rate is not None else ''}
    JustBooks and ZVAB search books written in {html.escape(language_name)}.
    Alibris, eBay, and AwesomeBooks do not filter by language.
    Alibris totals add the standard shipping shown on the copy. Digital formats are skipped.
    eBay is the cheapest Buy It Now in Books &amp; Magazines whose title contains the author and the title, including delivery to the United States (ebay.com) or the United Kingdom (ebay.co.uk).
    AwesomeBooks is British pounds with free UK delivery.
    ZVAB is the cheapest listing by total price, in euros, including the shipping shown on the listing.
    {f'Publication year filter: {year}. ' if year is not None else ''}{f'ISBN filter: {isbn}.' if isbn else ''}</p>
  </footer>
</main>
</body>
</html>
"""


def serve(directory: Path, port: int) -> None:
    handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(*args, directory=str(directory), **kwargs)
    last_error = None
    server = None
    for candidate in range(port, port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), handler)
            port = candidate
            break
        except OSError as exc:
            last_error = exc
    if server is None:
        raise SystemExit(f"Could not listen near port {port}: {last_error}")
    url = f"http://127.0.0.1:{port}/"
    print(f"Serving {url}", flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.", flush=True)
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Find the cheapest shipped copy of a book and show it locally.")
    parser.add_argument("--author", default="", help="Author (optional).")
    parser.add_argument("--title", default="", help="Title. Required unless --isbn is set.")
    parser.add_argument(
        "--isbn",
        default=None,
        help="ISBN-10 or ISBN-13; dashes/spaces optional. Can be used alone, e.g. 978-0-8028-4344-9.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Publication year to prefer (passed into shop searches where supported).",
    )
    parser.add_argument(
        "--language",
        default="English",
        help="Language of the book on JustBooks and ZVAB (default: English). "
        "English, German, French, Spanish, Italian, Dutch, or any "
        "(codes EN, DE, FR, ES, IT, NL, ANY). Alibris, eBay, and AwesomeBooks do not filter by language.",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--profile",
        default=None,
        help=f"Chrome user-data-dir that keeps captcha clearance (default: {DEFAULT_PROFILE})",
    )
    parser.add_argument(
        "-s",
        "--skip-warmup",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Skip opening JustBooks/Alibris before searching (use when clearance is still fresh). "
        "Use --no-skip-warmup to force the warmup tabs (default).",
    )
    args = parser.parse_args()
    isbn = None
    if args.isbn:
        try:
            isbn = normalize_isbn(args.isbn)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    author = (args.author or "").strip()
    title = (args.title or "").strip()
    if not isbn and not title:
        raise SystemExit("Provide --isbn or --title. --author is optional.")
    if args.year is not None and not 1000 <= args.year <= 2100:
        raise SystemExit("--year must be between 1000 and 2100.")
    try:
        language, language_name = normalize_language(args.language)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("Install Playwright first: python3 -m pip install playwright")

    print("Fetching USD and EUR to GBP rates…", flush=True)
    rate, rate_date = fetch_usd_gbp()
    eur_rate, eur_date = fetch_gbp_rate("EUR")
    rate_note = rate_date

    profile = resolve_profile(args.profile)
    print(f"Chrome profile: {profile}", flush=True)
    debug_port = free_port()
    chrome = launch_chrome(debug_port, profile)
    out_dir = Path(tempfile.mkdtemp(prefix="bookcmp-page-"))
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            if not args.skip_warmup:
                warmup(page)
            year = args.year
            if isbn:
                print(f"ISBN: {isbn}", flush=True)
            if year is not None:
                print(f"Publication year: {year}", flush=True)
            print(f"Book language: {language_name}", flush=True)
            print("Searching JustBooks…", flush=True)
            justbooks = justbooks_match(page, author, title, year, isbn, language)
            print("Searching Alibris.com…", flush=True)
            alibris_us = alibris_match(page, "alibris.com", author, title, "USD", rate, rate_note, year, isbn)
            print("Searching Alibris.co.uk…", flush=True)
            alibris_uk = alibris_match(page, "alibris.co.uk", author, title, "GBP", rate, rate_note, year, isbn)
            print("Searching eBay.com…", flush=True)
            ebay_us = ebay_match(page, "ebay.com", author, title, "1", "10001", rate, rate_note, year, isbn)
            print("Searching eBay.co.uk…", flush=True)
            ebay_uk = ebay_match(page, "ebay.co.uk", author, title, "3", "SW1A1AA", rate, rate_note, year, isbn)
            print("Searching AwesomeBooks…", flush=True)
            awesome = awesomebooks_match(page, author, title, year, isbn)
            print("Searching ZVAB…", flush=True)
            zvab = zvab_match(
                page, author, title, rate, eur_rate, eur_date or rate_note, year, isbn, language, language_name
            )
        matches = [justbooks, alibris_us, alibris_uk, ebay_us, ebay_uk, awesome, zvab]
        for item in matches:
            if item.error:
                print(f"{item.label}: {item.error}", flush=True)
            else:
                print(f"{item.label}: {item.price_text} — {item.title}", flush=True)
        heading, query = display_heading(author, title, isbn, year, language_name)
        if not title:
            for item in matches:
                if item.title and not item.error:
                    heading = item.title
                    break
        page_html = render_page(
            query, heading, matches, rate, rate_note, year, isbn, language_name, eur_rate, eur_date
        )
        (out_dir / "index.html").write_text(page_html, encoding="utf-8")
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chrome.kill()

    serve(out_dir, args.port)


if __name__ == "__main__":
    main()
