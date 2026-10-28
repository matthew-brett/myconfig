#!/usr/bin/env python3
"""Compare the cheapest shipped copy of a book across several shops.

Searches JustBooks (GBP, all matches combined, priced to both the UK and the US
with the cheaper kept; --ship-to GB or US forces one, with booklooker.de offers
priced at the seller's own shipping rate), Alibris.com
(non-digital, ship to the US, converted to GBP), Alibris.co.uk (non-digital,
GBP shipping), eBay.com (ship to the US, converted to GBP), eBay.co.uk
(GBP shipping), AwesomeBooks (GBP, free UK delivery) and ZVAB (EUR, shipping
to the United Kingdom, converted to GBP). Writes a local page and serves it.

Requires Google Chrome and Playwright:

    python3 -m pip install playwright
    python3 compare_books.py --author "J. R. R. Tolkien" --title "The Hobbit"
    python3 compare_books.py --author "J. R. R. Tolkien" --title "The Hobbit" --year 1937
    python3 compare_books.py --author Hengel --title "Die Evangelien" --language German
    python3 compare_books.py --title "Der kleine Hobbit" --language German
    python3 compare_books.py --isbn 978-0-8028-4344-9
    python3 compare_books.py --serve        # local page; search from the browser

Uses a persistent Chrome profile (~/.cache/bookcmp-chrome) so captcha clearance
survives between runs. On each run it opens the search page for JustBooks, both
Alibris sites and AwesomeBooks in separate tabs, plus a warm-up tab listing each
site with its state; solve any challenges there and press "Search all shops" on
that tab (no console needed). With --serve the warm-up and the results live on a
local page instead. Pass --skip-warmup when clearance is still fresh. --isbn
alone is enough, and so is --title; --author is optional. Dashes and spaces in
the ISBN are optional.

Written by Cursor, Auto model, late September / early October 2026.  Copyright
therefore unknown.  Please do not re-use.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_PROFILE = Path.home() / ".cache" / "bookcmp-chrome"
WARMUP_SITES = [
    ("JustBooks", "https://www.justbooks.co.uk/"),
    ("Alibris.com", "https://www.alibris.com/"),
    ("Alibris.co.uk", "https://www.alibris.co.uk/"),
    ("AwesomeBooks", "https://www.awesomebooks.com/"),
]
# Sites behind Cloudflare, where no check on screen can still mean no clearance cookie.
CLOUDFLARE_SITES = {"Alibris.com", "Alibris.co.uk", "AwesomeBooks"}
CHALLENGE_WAIT_S = 300
CONTROL_POLL_S = 0.5
# Counts bot checks cleared during a run, so a step that a check interrupted can start again.
CHALLENGES_SOLVED = 0
# Set by the --serve app so progress can be forwarded to the local page.
REPORTER = None


def set_reporter(reporter) -> None:
    global REPORTER
    REPORTER = reporter


def report(kind: str, **fields) -> None:
    """Send a progress event to the local page, if one is watching."""
    reporter = REPORTER
    if reporter is None:
        return
    try:
        reporter(kind, fields)
    except Exception:
        pass

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


CHALLENGE_TEXT_RE = re.compile(
    r"just a moment|checking your browser|verifying you are human|verify you are (a )?human"
    r"|attention required|enable javascript and cookies|are you a human|press and hold"
    r"|cf-browser-verification|captcha|security check",
    re.I,
)


def challenge_text(text: str) -> bool:
    """True for a challenge *title* (page text is matched separately, more narrowly)."""
    return bool(CHALLENGE_TEXT_RE.search(text or ""))


def page_looks_challenged(page) -> bool:
    """True when a bot check / captcha is likely still on screen (title alone is not enough)."""
    try:
        if challenge_text(page.title()):
            return True
    except Exception:
        pass
    try:
        return bool(
            page.evaluate(
                """() => {
                  if (window._cf_chl_opt) return true;
                  if (document.querySelector(
                    '#challenge-form, #challenge-running, #challenge-stage, #cf-challenge-running, #px-captcha'
                  )) return true;
                  const text = ((document.title || '') + ' ' + (document.body?.innerText || '')).slice(0, 4000);
                  if (/just a moment|checking your browser|verifying you are human|verify you are (a )?human|attention required|enable javascript and cookies|are you a human|press and hold/i.test(text))
                    return true;
                  // A captcha widget on an otherwise short page is a check; the same widget on a
                  // full shop page is just a form and must not block the run.
                  const weak = !!document.querySelector(
                    'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], iframe[src*="captcha"], .cf-turnstile'
                  );
                  return weak && (document.body?.innerText || '').trim().length < 1500;
                }"""
            )
        )
    except Exception:
        return False


def wait_out_challenge(page, timeout: float = CHALLENGE_WAIT_S) -> None:
    """Pause while Cloudflare / bot checks are showing so they can be solved in Chrome.

    The tab is brought to the front first: a check that lands during the search
    would otherwise sit in the background, unseen, until it timed out.
    """
    global CHALLENGES_SOLVED
    if not page_looks_challenged(page):
        return
    CHALLENGES_SOLVED += 1
    try:
        page.bring_to_front()
    except Exception:
        pass
    host = page_host(page.url) or "the site"
    print(
        f"Bot check on {host} — solve it in Chrome; waiting up to {int(timeout)}s…",
        flush=True,
    )
    report("challenge", host=host, timeout=int(timeout))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if not page_looks_challenged(page):
                page.wait_for_timeout(500)
                report("challenge-clear", host=host)
                return
        except Exception:
            page.wait_for_timeout(1000)
            continue
        page.wait_for_timeout(1000)
    raise TimeoutError(f"Bot check on {host} did not clear in time.")


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
    raise TimeoutError(f"Page did not become ready (last title: {last!r}, url: {page.url}).")


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


def page_host(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")


def goto(page, url: str) -> None:
    """Open url, and retry when the current site cancels that navigation.

    Awesome Books aborts the next load (net::ERR_ABORTED) and stays on its own
    results. The following search then times out and reports the Awesome Books
    title. A blank page in between lets the next site load.

    A bot check replaces the page wholesale, which makes the pending navigation
    fail too. That is not an error: the check is left on screen for the person
    to solve, and the navigation is repeated afterwards.
    """
    want = page_host(url)
    last_error = None
    for attempt in range(3):
        try:
            if attempt:
                page.goto("about:blank", wait_until="domcontentloaded", timeout=15000)
            before = page_host(page.url)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                if not page_looks_challenged(page):
                    raise
                last_error = exc
            wait_out_challenge(page)
            # A redirect to another host is fine. Still being on the previous
            # site means that site cancelled the load.
            got = page_host(page.url)
            if want and got != want and (not got or got == before):
                raise RuntimeError(f"Browser stayed on {page.url} instead of opening {url}")
            return
        except Exception as exc:
            if page_looks_challenged(page):
                wait_out_challenge(page)
                if not want or page_host(page.url) == want:
                    return
            last_error = exc
            message = str(exc).lower()
            retryable = any(
                token in message
                for token in ("interrupted", "err_aborted", "stayed on", "frame was detached")
            )
            if not retryable or attempt == 2:
                raise
            page.wait_for_timeout(400)
    if last_error:
        raise last_error


CONTROL_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Book compare — warm up</title>
<style>
  body { margin: 0; font: 16px/1.45 "Iowan Old Style", Palatino, Georgia, serif; background: #f4f0e6; color: #1c1915; }
  main { max-width: 680px; margin: 0 auto; padding: 40px 22px 64px; }
  h1 { font-size: 1.6rem; margin: 0 0 6px; }
  .lede { color: #5c564c; margin-top: 0; }
  ul { list-style: none; margin: 22px 0; padding: 0; }
  li { display: flex; align-items: center; gap: 10px; background: #fffdf8; border: 1px solid #ddd4c4; border-radius: 10px; padding: 10px 14px; margin: 8px 0; }
  li .name { font-weight: 600; }
  li .note { color: #5c564c; font-size: 0.85rem; flex: 1; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: #c9c0ad; flex: none; }
  .dot.check { background: #b8791f; }
  .dot.ready { background: #2f6f4e; }
  .dot.loading { background: #9a9a9a; }
  .dot.failed { background: #8a2b2b; }
  .dot.closed { background: #6b6257; }
  button { font: inherit; border-radius: 999px; border: 1px solid #2f6f4e; background: #2f6f4e; color: #fffdf8; padding: 10px 22px; cursor: pointer; }
  button:disabled { opacity: 0.45; cursor: not-allowed; }
  button.secondary { background: transparent; color: #2f6f4e; border-color: #b9c9bd; margin-left: 10px; font-size: 0.88rem; padding: 8px 16px; }
  .status { margin: 18px 0 10px; font-weight: 600; }
  .hint { color: #5c564c; font-size: 0.88rem; }
  body.started ul, body.started .status { opacity: 0.5; }
  body.started button { pointer-events: none; }
</style>
</head>
<body>
<main>
  <h1>Warm-up</h1>
  <p class="lede">Solve any bot checks in the other tabs. Start the search from this page — no console needed.</p>
  <ul id="sites"></ul>
  <p class="status" id="status">Checking…</p>
  <button id="go" disabled>Search all shops</button>
  <button id="force" class="secondary">Search anyway</button>
  <p class="hint">These buttons send nothing over the network; they only tell the waiting script to carry on.</p>
</main>
<script>
window.__go = false;
window.__focus = "";
const LABELS = {check: "bot check showing", loading: "loading…", ready: "ready", failed: "did not load", closed: "tab closed"};
function render(state) {
  const sites = state.sites || [];
  const list = document.getElementById("sites");
  list.innerHTML = "";
  for (const site of sites) {
    const li = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = "dot " + site.state;
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = site.name;
    const note = document.createElement("span");
    note.className = "note";
    note.textContent = site.note || LABELS[site.state] || site.state;
    li.append(dot, name, note);
    if (site.state !== "ready") {
      const show = document.createElement("button");
      show.className = "secondary";
      show.textContent = "Show tab";
      show.onclick = () => { window.__focus = site.name; };
      li.append(show);
    }
    list.append(li);
  }
  const waiting = sites.filter(site => site.state !== "ready").map(site => site.name);
  const ready = sites.length > 0 && waiting.length === 0;
  document.getElementById("go").disabled = !ready;
  document.getElementById("status").textContent = ready
    ? "Everything looks clear."
    : "Waiting for: " + (waiting.join(", ") || "the sites to load");
}
window.__update = render;
document.getElementById("go").onclick = () => {
  window.__go = true;
  document.body.classList.add("started");
};
document.getElementById("force").onclick = () => {
  window.__go = true;
  document.body.classList.add("started");
};
</script>
</body>
</html>
"""


def has_clearance_cookie(context, url: str) -> bool:
    """True when Cloudflare's clearance cookie is already stored for url's host."""
    try:
        return any(cookie.get("name") == "cf_clearance" for cookie in context.cookies([url]))
    except Exception:
        return False


def warmup_state(tab, clearance: bool | None = None) -> tuple[str, str]:
    """Return (state, note) for one warm-up tab: ready, check, loading, failed or closed."""
    try:
        if tab.is_closed():
            return "closed", ""
        title = tab.title() or ""
    except Exception:
        return "closed", ""
    if page_looks_challenged(tab):
        return "check", ""
    if not title:
        return "loading", ""
    try:
        if tab.evaluate("() => !!document.querySelector('#main-frame-error, .error-code')"):
            return "failed", "Chrome could not load it"
    except Exception:
        pass
    if clearance is False:
        return "ready", "no cf_clearance cookie yet — its search may still be checked"
    return "ready", ""


def control_update(control, sites: list[dict]) -> None:
    try:
        control.evaluate("(state) => window.__update(state)", {"sites": sites})
    except Exception:
        pass


def warmup_status(context, tabs, probes: dict[str, str] | None = None) -> list[dict]:
    """Per-site warm-up state, as shown in the browser (CLI) or the local page (--serve)."""
    probes = probes or {}
    site_urls = dict(WARMUP_SITES)
    sites = []
    for name, tab in tabs:
        url = probes.get(name) or site_urls.get(name, "")
        clearance = has_clearance_cookie(context, url) if name in CLOUDFLARE_SITES else None
        state, note = warmup_state(tab, clearance)
        sites.append({"name": name, "state": state, "note": note})
    return sites


def confirm_in_browser(context):
    """Ask for the all-clear on an injected page inside Chrome; used by the command line."""

    def confirm(tabs, probes) -> list[dict]:
        control = None
        try:
            control = context.new_page()
            control.set_content(CONTROL_PAGE_HTML)
            control.bring_to_front()
        except Exception as exc:
            print(f"Could not open the warm-up page in Chrome ({exc}); using the console instead.", flush=True)
            if control is not None:
                try:
                    control.close()
                except Exception:
                    pass
            control = None

        if control is None:
            input("Press Enter when all challenges are cleared and you're ready to search… ")
            return warmup_status(context, tabs, probes)

        print('Solve any challenges in Chrome, then press "Search all shops" on the warm-up tab.', flush=True)
        sites: list[dict] = []
        while True:
            sites = warmup_status(context, tabs, probes)
            control_update(control, sites)
            try:
                flags = control.evaluate("() => ({go: !!window.__go, focus: window.__focus || ''})")
            except Exception:
                raise SystemExit("The warm-up tab was closed — nothing has been searched. Run again to start over.")
            wanted = flags.get("focus") or ""
            if wanted:
                for name, tab in tabs:
                    if name == wanted:
                        try:
                            tab.bring_to_front()
                        except Exception:
                            pass
                try:
                    control.evaluate("() => { window.__focus = ''; }")
                except Exception:
                    pass
            if flags.get("go"):
                break
            if all(site["state"] == "closed" for site in sites):
                raise SystemExit("All warm-up tabs were closed — nothing has been searched.")
            time.sleep(CONTROL_POLL_S)
        waiting = [site["name"] for site in sites if site["state"] != "ready"]
        if waiting:
            print(f"Starting with {', '.join(waiting)} not confirmed clear.", flush=True)
        try:
            control.close()
        except Exception:
            pass
        return sites

    return confirm


def warmup(page, probes: dict[str, str] | None = None, confirm=None) -> list[dict]:
    """Open each tricky site in its own tab and wait for the all-clear.

    Each tab loads the URL the search will really use (probes), not just the
    home page: Cloudflare clears one URL at a time, so a home page that is free
    of checks proves nothing about the search page that follows.

    confirm(tabs, probes) decides when to go on: the injected Chrome page on the
    command line, the local web page under --serve.
    """
    probes = probes or {}
    print("Warming up sites — each opens in its own tab so challenges are not replaced…", flush=True)
    context = page.context
    tabs: list[tuple[str, object]] = []
    for index, (name, url) in enumerate(WARMUP_SITES):
        target = probes.get(name) or url
        tab = page if index == 0 else context.new_page()
        tabs.append((name, tab))
        print(f"  Opening {name}…", flush=True)
        try:
            tab.goto(target, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            print(f"  {name} failed to open: {exc}", flush=True)

    confirm = confirm_in_browser(context) if confirm is None else confirm
    sites = confirm(tabs, probes)

    for _, tab in tabs:
        if tab is not page:
            try:
                tab.close()
            except Exception:
                pass
    try:
        page.bring_to_front()
    except Exception:
        pass
    return sites


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


def alibris_open_search(page, domain: str, search_url: str, currency_code: str) -> None:
    """Open an Alibris search in the wanted currency, restarting if a bot check cuts in.

    The currency change is a separate portal navigation. A check that lands
    between the two requests leaves the pair half done (search page gone, or
    currency reverted), so start both again once the check has been solved.
    """
    for attempt in range(3):
        before = CHALLENGES_SOLVED
        goto(page, search_url)
        wait_ready(page, lambda: "alibris" in page.title().lower() or page.locator("h2 a").count() > 0)
        set_alibris_currency(page, domain, currency_code)
        goto(page, search_url)
        wait_ready(page, lambda: page.locator("h2 a").count() > 0 or "matching" in page.inner_text("body").lower())
        if CHALLENGES_SOLVED == before:
            return
        print(f"  Bot check cleared on {domain}; repeating the search.", flush=True)
    raise RuntimeError("Alibris kept interrupting with bot checks.")


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
        alibris_open_search(page, domain, search_url, currency_code)
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


def justbooks_search_url(
    author: str,
    title: str,
    year: int | None = None,
    isbn: str | None = None,
    language: str = "ANY",
    destination: str = "GB",
) -> str:
    params = {
        "author": author,
        "title": title,
        "language": language,
        "condition": "ANY",
        "binding": "ANY",
        "currency": "GBP",
        "destination": destination,
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
    return "https://www.justbooks.co.uk/search?" + urllib.parse.urlencode(params)


BOOKLOOKER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
# Booklooker sellers quote shipping in three columns: Deutschland, EU, Welt. JustBooks
# always reports the German domestic rate for these offers, whatever destination was
# asked for, so the seller's own table has to be read instead.
BOOKLOOKER_EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "GR", "HU", "IE",
    "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}
# Median "Welt" rate for a book up to 1 kg in a 16-seller sample (range EUR 8.95-19.50),
# used only where a seller publishes no table at all.
BOOKLOOKER_FALLBACK_EUR = 19.50
MAX_BOOKLOOKER_LOOKUPS = 6
_booklooker_rates: dict[tuple[str, str], tuple[float | None, str, bool]] = {}


def booklooker_item_id(url: str) -> str | None:
    """The seller's item id from a booklooker offer link, or None for aggregate pages."""
    if "resultnew.php" in url:
        return None
    match = re.search(r"[?&]id=([A-Za-z0-9]+)", url)
    return match.group(1) if match else None


def booklooker_columns(country: str) -> tuple[str, ...]:
    """Shipping columns to try, best first, for a delivery country (ISO 3166-1 alpha-2)."""
    if country == "DE":
        return ("Deutschland",)
    if country in BOOKLOOKER_EU_COUNTRIES:
        return ("EU", "Europa", "Welt")
    if country == "GB":
        return ("Großbritannien", "Vereinigtes Königreich", "UK", "Welt", "weltweit")
    return ("Welt", "weltweit")


def _booklooker_cell_amount(cell: str) -> float | None:
    """EUR amount from a table cell; '—' means the seller does not offer that rate."""
    if not cell or "—" in cell or "–" in cell:
        return None
    match = re.search(r"([0-9]+(?:[.,][0-9]{1,2})?)", cell)
    return float(match.group(1).replace(",", ".")) if match else None


def _booklooker_shipping_table(markup: str) -> tuple[list[str] | None, list[list[str]]]:
    table = re.search(r'<table class="shippingTable2".*?</table>', markup, re.S)
    if not table:
        return None, []
    rows = []
    for row in re.findall(r"<tr.*?</tr>", table.group(0), re.S):
        cells = [
            re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", cell))).strip()
            for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        ]
        if cells:
            rows.append(cells)
    header = None
    for row in rows:
        if any(cell in ("Gewicht", "Anzahl", "Land") for cell in row):
            header = row
    data = [row for row in rows if row is not header and any("€" in cell or "—" in cell for cell in row)]
    return header, data


def booklooker_shipping(url: str, country: str) -> tuple[float | None, str, bool]:
    """(EUR shipping to country, note, ships) for one booklooker offer link.

    (None, note, True) means the rate is unknown; (None, note, False) means the
    seller does not ship there at all.
    """
    if country == "DE":
        return None, "German delivery; JustBooks' figure is the domestic rate", True
    item = booklooker_item_id(url)
    if not item:
        return None, "aggregated new-book page; booklooker quotes German delivery only", True
    key = (item, country)
    if key in _booklooker_rates:
        return _booklooker_rates[key]
    result: tuple[float | None, str, bool]
    try:
        request = urllib.request.Request(
            f"https://www.booklooker.de/app/detail.php?id={item}",
            headers={"User-Agent": BOOKLOOKER_UA, "Accept-Language": "de-DE,de;q=0.9,en;q=0.5"},
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            markup = response.read().decode("utf-8", "replace")
    except Exception as exc:
        result = (None, f"booklooker page could not be read ({exc.__class__.__name__})", True)
        _booklooker_rates[key] = result
        return result
    header, data = _booklooker_shipping_table(markup)
    if not header or not data:
        result = (None, "seller publishes no shipping table", True)
    else:
        index = None
        for name in booklooker_columns(country):
            for position, cell in enumerate(header):
                if cell == name or (name == "Welt" and cell.startswith("Welt")):
                    index = position
        if index is None:
            result = (None, "seller's table has no rate for this destination", False)
        else:
            amount = _booklooker_cell_amount(data[0][index]) if index < len(data[0]) else None
            if amount is None:
                result = (None, f"no {header[index]} rate ({data[0][0]} tier)", False)
            else:
                result = (amount, f"{header[index]}, {data[0][0]}", True)
    _booklooker_rates[key] = result
    return result


def justbooks_offer_total(
    offer: dict,
    total_gbp: float,
    country: str,
    eur_rate: float | None,
    lookups: list[int],
) -> tuple[float | None, str]:
    """Correct a booklooker offer's total with the seller's own shipping rate.

    JustBooks quotes booklooker's German domestic shipping (often EUR 2.90) for
    every destination, and nothing at all for the aggregated "neu" pages, so the
    total has to be rebuilt from the seller's table. Returns (total, note), with
    total None when the seller does not ship to country.
    """
    url = offer.get("href") or ""
    quote = parse_amount(offer.get("ship") or "")
    quoted = quote[0] if quote and quote[1] == "GBP" else 0.0
    base = total_gbp - quoted
    if country == "DE":
        return total_gbp, ""
    if len(lookups) >= MAX_BOOKLOOKER_LOOKUPS:
        amount, note = BOOKLOOKER_FALLBACK_EUR, "too many booklooker offers to check them all"
    else:
        lookups.append(1)
        amount, note, ships = booklooker_shipping(url, country)
        if not ships:
            return None, f"booklooker seller ships within Germany only ({note})"
        if amount is None:
            amount = BOOKLOOKER_FALLBACK_EUR
            note = f"estimated; {note}"
    if eur_rate is None:
        return total_gbp, f"shipping {money_text(amount, 'EUR')} (no EUR rate to convert it)"
    corrected = base + amount * eur_rate
    quoted_text = f", not the {money_text(quoted, 'GBP')} JustBooks showed" if quoted else ""
    return corrected, f"booklooker shipping {money_text(amount, 'EUR')} ({note}){quoted_text}"


def justbooks_match(
    page,
    author: str,
    title: str,
    year: int | None = None,
    isbn: str | None = None,
    language: str = "ANY",
    destination: str = "GB",
    eur_rate: float | None = None,
) -> Match:
    label = "justbooks match"
    language_name = next((name for code, name in LANGUAGES.values() if code == language), language)
    search_url = justbooks_search_url(author, title, year, isbn, language, destination)
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
                    affiliate: card.getAttribute('data-csa-c-affiliate') || '',
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
    candidates: list[tuple[float, dict]] = []
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
        candidates.append((parsed[0], offer))

    best = None
    skipped: list[str] = []
    lookups: list[int] = []
    candidates.sort(key=lambda item: item[0])
    # An offer that is not from booklooker needs no correction, so the cheapest of
    # those is a hard floor: booklooker totals only ever rise, and nothing at or
    # above the floor can win. That also keeps the number of page fetches small.
    for total, offer in candidates:
        if offer.get("affiliate") == "BOOKLOOKER" or "booklooker.de" in (offer.get("href") or ""):
            continue
        best = {"total": total, **offer, "shipping_note": ""}
        break
    floor = best["total"] if best is not None else None
    for total, offer in candidates:
        if floor is not None and total >= floor:
            break
        note = ""
        if offer.get("affiliate") == "BOOKLOOKER" or "booklooker.de" in (offer.get("href") or ""):
            total, note = justbooks_offer_total(offer, total, destination, eur_rate, lookups)
            if total is None:
                skipped.append(offer.get("title") or "offer")
                continue
        if best is None or total < best["total"]:
            best = {"total": total, **offer, "shipping_note": note}

    if best is None:
        detail = "No GBP offers were listed."
        if skipped:
            detail = "No booklooker offer ships to the destination; no other GBP offer was listed."
        return Match(label=label, search_url=search_url, error=detail)
    ship = best.get("shipping_note") or best.get("ship") or "shipping included in the total"
    extra = ""
    if skipped:
        extra += f" {len(skipped)} booklooker offer(s) left out: those sellers do not ship to the destination."
    if year is not None:
        extra += f" Publication year {year}."
    if isbn:
        extra += f" ISBN {isbn}."
    extra += f" Books written in {language_name}."
    destination_name = {"GB": "the United Kingdom", "US": "the United States"}.get(destination, destination)
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
            f"GBP, shipping to {destination_name}, all matches combined.{extra}"
        ),
    )


def justbooks_quote(
    page,
    author: str,
    title: str,
    year: int | None = None,
    isbn: str | None = None,
    language: str = "ANY",
    destination: str = "BOTH",
    eur_rate: float | None = None,
) -> Match:
    """JustBooks priced to the UK and to the US, with the cheaper of the two kept.

    The offer sets differ by destination (sellers appear or drop out), and so do
    the booklooker shipping rates, so both searches have to be run to know which
    route is cheaper.
    """
    destination = (destination or "BOTH").upper()
    if destination != "BOTH":
        return justbooks_match(page, author, title, year, isbn, language, destination, eur_rate)

    quotes = []
    for country in ("GB", "US"):
        print(f"  JustBooks, shipping to {country}…", flush=True)
        quotes.append(justbooks_match(page, author, title, year, isbn, language, country, eur_rate))

    priced = [quote for quote in quotes if quote.price_gbp is not None]
    summary = []
    for country, quote in zip(("GB", "US"), quotes):
        name = {"GB": "the United Kingdom", "US": "the United States"}[country]
        if quote.price_gbp is None:
            reason = (quote.error or "no price").rstrip(".")
            summary.append(f"nothing to {name} ({reason})")
        else:
            summary.append(f"£{quote.price_gbp:.2f} to {name}")
    both = "; ".join(summary)

    if not priced:
        return Match(
            label="justbooks match",
            search_url=quotes[0].search_url,
            error=f"No JustBooks offer for either destination ({both}).",
        )
    best = min(priced, key=lambda quote: quote.price_gbp)
    best.detail = f"{best.detail} Both destinations quoted: {both}."
    return best


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


def awesomebooks_search_url(
    author: str,
    title: str,
    year: int | None = None,
    isbn: str | None = None,
) -> str:
    if isbn:
        query = isbn
    else:
        query = f"{author} {title}".strip()
        if year is not None:
            query = f"{query} {year}"
    return "https://www.awesomebooks.com/search/advanced?" + urllib.parse.urlencode(
        {"q": query, "sortBy": "price_asc"}
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
    search_url = awesomebooks_search_url(author, title, year, isbn)
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
    language: str = "ANY",
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


ZVAB_UK_PREFS = '{"modified":true,"curr":"EUR","shipdest":"GBR"}'
ZVAB_UK_SHIP_RE = re.compile(
    r"vereinigtes\s+k[oö]nigreich|united\s+kingdom|gro[sß]britannien|great\s+britain",
    re.I,
)
ZVAB_NO_SHIP_RE = re.compile(
    r"nicht\s+nach|wird\s+nicht|versand\s+nicht|does\s+not\s+ship|doesn'?t\s+ship|not\s+shipped",
    re.I,
)


def zvab_set_uk_destination(page) -> None:
    """Ask ZVAB to price shipping to the United Kingdom (GBR)."""
    page.context.add_cookies(
        [
            {"name": "AbeShipTo", "value": "GBR", "domain": "www.zvab.com", "path": "/"},
            {"name": "abe_prefs", "value": ZVAB_UK_PREFS, "domain": "www.zvab.com", "path": "/"},
        ]
    )


def zvab_ships_to_uk(note: str) -> bool:
    """True when the listing's shipping line is for delivery to the UK."""
    if not note or ZVAB_NO_SHIP_RE.search(note):
        return False
    return ZVAB_UK_SHIP_RE.search(note) is not None


def parse_zvab_amount(text: str) -> tuple[float, str] | None:
    """Parse an EUR/GBP/USD amount. ZVAB writes German figures such as 'EUR 11,60'."""
    cleaned = text.replace("\xa0", " ").replace("\u202f", " ")
    match = re.search(
        r"(?P<cur>EUR|GBP|USD|€|£|\$)\s*(?P<amt>[0-9]{1,3}(?:[.\s][0-9]{3})*(?:[.,][0-9]{2})|[0-9]+(?:[.,][0-9]{2})?)",
        cleaned,
        re.I,
    )
    if not match:
        return None
    raw = match.group("amt").replace(" ", "")
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif raw.count(",") == 1 and len(raw.split(",")[-1]) == 2:
        raw = raw.replace(",", ".")
    value = float(raw)
    symbol = match.group("cur")
    currency = {"€": "EUR", "£": "GBP", "$": "USD"}.get(symbol, symbol.upper())
    if currency not in {"EUR", "GBP", "USD"}:
        return None
    return value, currency


def zvab_listings(page) -> list[dict]:
    return page.evaluate(
        """() => {
          const pageText = document.documentElement.outerHTML;
          const ukDest = /shipdest[^A-Z]{0,12}GBR/.test(pageText)
            || /vereinigtes\\s+k[oö]nigreich|united\\s+kingdom/i.test(document.body?.innerText || '');
          const read = (li, closest) => {
            const basket = li.querySelector('[data-test-id^="add-to-basket"]');
            const cost = basket ? basket.getAttribute('data-csa-c-cost') : null;
            const ship = basket ? basket.getAttribute('data-csa-c-shipping-cost') : null;
            const hidden = [...li.querySelectorAll('.VersoVisuallyHidden')]
              .map(el => (el.textContent || '').replace(/\\s+/g, ' ').trim())
              .find(text => text.startsWith('Versand')) || '';
            const label = li.querySelector('a[aria-label]')?.getAttribute('aria-label') || '';
            const sellerMatch = label.match(/(?:zum Verkauf durch|sold by)\\s+(.+)$/i);
            const sellerLink = (li.querySelector('[data-test-id="listing-seller-link"]')?.innerText || '').trim();
            return {
              title: (li.querySelector('[data-test-id="listing-title"]')?.innerText || '').trim(),
              author: (li.querySelector('[data-test-id="listing-author"]')?.innerText || '').trim(),
              href: li.querySelector('a[href*="/bd"]')?.href || li.querySelector('[data-test-id="listing-title-link"]')?.href || '',
              condition: (li.querySelector('[data-test-id="listing-condition"]')?.innerText || li.querySelector('[aria-label="Gebraucht"], [aria-label="Neu"]')?.getAttribute('aria-label') || '').trim(),
              seller: sellerLink || (sellerMatch ? sellerMatch[1].trim() : ''),
              isbn: (li.querySelector('[data-test-id^="isbn-"]')?.innerText || '').trim(),
              item: cost === null || cost === '' ? null : Number(cost),
              ship: ship === null || ship === '' ? null : Number(ship),
              currency: basket?.getAttribute('data-csa-c-purchase-currency') || '',
              priceText: (li.querySelector('[data-test-id="listing-price"]')?.innerText || '').replace(/\\s+/g, ' ').trim(),
              shipText: (li.querySelector('[data-test-id="listing-shipping"], [data-test-id^="item-shipping-price"]')?.innerText || '').replace(/\\s+/g, ' ').trim(),
              note: hidden || (closest && ukDest ? 'Versandziel: Vereinigtes Königreich' : ''),
              closest,
              text: (li.innerText || '').replace(/\\s+/g, ' ').slice(0, 900),
            };
          };
          const full = [...document.querySelectorAll('[data-srp-item-role="listing"]')].map(li => read(li, false));
          const close = [...document.querySelectorAll('[data-test-id="closest-match-item"]')].map(li => read(li, true));
          return full.concat(close);
        }"""
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
    language: str = "ANY",
    language_name: str = "any language",
) -> Match:
    label = "zvab.com match"
    search_url = zvab_search_url(author, title, year, isbn, language)
    tokens = significant_tokens(title)
    author_tokens = significant_tokens(author)
    best = None
    try:
        zvab_set_uk_destination(page)
        goto(page, search_url)
        for _ in range(4):
            wait_ready(
                page,
                lambda: page.locator(
                    '[data-srp-item-role="listing"], [data-test-id="closest-match-item"]'
                ).count()
                > 0
                or page.locator("text=/Keine genauen Treffer|Keine Ergebnisse/i").count() > 0,
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
                    parsed_item = parse_zvab_amount(card.get("priceText") or "")
                    ship_line = card.get("shipText") or ""
                    if parsed_item is None:
                        continue
                    item, currency = parsed_item
                    if re.search(r"gratis|kostenlos|free", ship_line, re.I):
                        ship = 0.0
                    else:
                        parsed_ship = parse_zvab_amount(ship_line)
                        if parsed_ship is None or parsed_ship[1] != currency:
                            continue
                        ship = parsed_ship[0]
                if item is None or ship is None or currency not in {"EUR", "GBP", "USD"}:
                    continue
                if item != item or ship != ship:
                    continue
                if not zvab_ships_to_uk(card.get("note") or ""):
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
                        "closest": bool(card.get("closest")),
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
        return Match(
            label=label,
            search_url=search_url,
            error="No priced copy that ships to the United Kingdom matched the title.",
        )
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
    if best["ship"] == 0:
        ship_text = "free shipping to the United Kingdom"
    else:
        ship_text = f"shipping {money_text(best['ship'], best['currency'])} to the United Kingdom"
    extra = ""
    if best.get("closest"):
        extra += " Closest match; ZVAB had no exact hit for this search."
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
    language_name: str = "any language",
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
    Booklooker.de offers on JustBooks are priced with the seller's own shipping rate;
    JustBooks itself quotes the German domestic rate for those offers.
    Alibris totals add the standard shipping shown on the copy. Digital formats are skipped.
    eBay is the cheapest Buy It Now in Books &amp; Magazines whose title contains the author and the title, including delivery to the United States (ebay.com) or the United Kingdom (ebay.co.uk).
    AwesomeBooks is British pounds with free UK delivery.
    ZVAB is the cheapest listing by total price that ships to the United Kingdom, in euros, including that shipping.
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


WEB_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Book prices</title>
<style>
  body { margin: 0; font: 16px/1.45 "Iowan Old Style", Palatino, Georgia, serif; background: #f4f0e6; color: #1c1915; }
  main { max-width: 820px; margin: 0 auto; padding: 32px 20px 64px; }
  h1 { font-size: 1.8rem; margin: 0 0 2px; }
  h2 { font-size: 1.05rem; margin: 26px 0 8px; }
  .lede { color: #5c564c; margin: 0 0 20px; }
  form { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px 14px; background: #fffdf8; border: 1px solid #ddd4c4; border-radius: 12px; padding: 16px 18px; }
  label { display: flex; flex-direction: column; gap: 4px; font-size: 0.85rem; color: #5c564c; }
  input, select { font: inherit; font-size: 0.95rem; padding: 7px 9px; border: 1px solid #cfc4b0; border-radius: 8px; background: #fff; color: #1c1915; }
  label.check { flex-direction: row; align-items: center; gap: 6px; font-size: 0.9rem; }
  form .actions { display: flex; align-items: end; gap: 10px; }
  button { font: inherit; border-radius: 999px; border: 1px solid #2f6f4e; background: #2f6f4e; color: #fffdf8; padding: 9px 20px; cursor: pointer; }
  button:disabled { opacity: 0.45; cursor: not-allowed; }
  button.secondary { background: transparent; color: #2f6f4e; border-color: #b9c9bd; font-size: 0.88rem; padding: 7px 14px; }
  .notice { margin: 14px 0 0; padding: 10px 14px; border-radius: 10px; background: #f7e8c8; border: 1px solid #e2ca95; }
  .notice.error { background: #f7dede; border-color: #e5b6b6; }
  ul.sites, ul.shops { list-style: none; margin: 8px 0 0; padding: 0; }
  ul.sites li, ul.shops li { display: flex; align-items: center; gap: 10px; background: #fffdf8; border: 1px solid #ddd4c4; border-radius: 10px; padding: 9px 14px; margin: 8px 0; }
  .name { font-weight: 600; }
  .note { color: #5c564c; font-size: 0.85rem; flex: 1; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: #c9c0ad; flex: none; }
  .dot.check { background: #b8791f; }
  .dot.warn { background: #b8791f; }
  .dot.ready, .dot.done { background: #2f6f4e; }
  .dot.loading, .dot.running { background: #9a9a9a; }
  .dot.failed, .dot.error { background: #8a2b2b; }
  .dot.closed { background: #6b6257; }
  .card { background: #fffdf8; border: 1px solid #ddd4c4; border-radius: 12px; padding: 16px 18px; margin: 14px 0; }
  .card.best { border-color: #2f6f4e; box-shadow: inset 4px 0 0 #2f6f4e; }
  .card h2 { margin: 0 0 8px; font-size: 1.05rem; }
  .badge { display: inline-block; margin-left: 8px; background: #2f6f4e; color: white; border-radius: 999px; padding: 2px 8px; font: 12px/1.4 sans-serif; vertical-align: 2px; }
  .price { font-size: 1.35rem; margin: 6px 0; }
  .detail, .links, .error { margin: 6px 0; }
  .detail { color: #3f3a33; }
  .error { color: #8a2b2b; }
  a { color: #1d4e89; }
  footer { color: #5c564c; font-size: 0.9rem; margin-top: 40px; }
  .hidden { display: none; }
</style>
</head>
<body>
<main>
  <h1>Book prices</h1>
  <p class="lede">Cheapest shipped copy across JustBooks, Alibris (US and UK), eBay (US and UK), AwesomeBooks and ZVAB. Searches run in the Chrome window this page opened with; solve any bot checks there.</p>

  <form id="form" autocomplete="off">
    <label>Title <input name="title"></label>
    <label>Author <input name="author"></label>
    <label>ISBN <input name="isbn" placeholder="978-0-8028-4344-9"></label>
    <label>Year <input name="year" type="number" min="1000" max="2100"></label>
    <label>Language
      <select name="language">
        <option value="any">Any</option>
        <option value="EN">English</option>
        <option value="DE">German</option>
        <option value="FR">French</option>
        <option value="ES">Spanish</option>
        <option value="IT">Italian</option>
        <option value="NL">Dutch</option>
      </select>
    </label>
    <label>JustBooks ships to
      <select name="shipTo">
        <option value="both">Cheapest of UK or US</option>
        <option value="GB">United Kingdom</option>
        <option value="US">United States</option>
      </select>
    </label>
    <label class="check"><input type="checkbox" name="skipWarmup"> Skip warm-up</label>
    <div class="actions"><button type="submit" id="search">Search</button></div>
  </form>

  <p class="notice hidden" id="notice"></p>

  <section id="warmup" class="hidden">
    <h2>Warm-up</h2>
    <ul class="sites" id="sites"></ul>
    <button id="go" disabled>Search all shops</button>
    <button id="force" class="secondary">Search anyway</button>
  </section>

  <section id="shops" class="hidden">
    <h2>Shops</h2>
    <ul class="shops" id="shoplist"></ul>
  </section>

  <section id="results" class="hidden">
    <h2 id="heading">Results</h2>
    <div id="cards"></div>
  </section>

  <footer>
    <p id="rates"></p>
    <p><a href="#" id="quit">Stop server</a></p>
  </footer>
</main>
<script>
const TOKEN = "__TOKEN__";
const PREFILL = __PREFILL__;
const $ = (selector) => document.querySelector(selector);
const SITE_LABELS = {check: "bot check showing", loading: "loading…", ready: "ready", failed: "did not load", closed: "tab closed"};
let source = null;
let jobId = "";
let lastSeq = 0;

function notice(text, isError) {
  const box = $("#notice");
  box.textContent = text || "";
  box.className = "notice" + (text ? "" : " hidden") + (isError ? " error" : "");
}

async function post(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Bookcmp-Token": TOKEN},
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function dot(state) {
  const span = document.createElement("span");
  span.className = "dot " + state;
  return span;
}

function link(href, text) {
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.textContent = text;
  anchor.target = "_blank";
  anchor.rel = "noreferrer";
  return anchor;
}

function resetPanels() {
  lastSeq = 0;
  $("#warmup").classList.add("hidden");
  $("#shops").classList.add("hidden");
  $("#results").classList.add("hidden");
  $("#cards").replaceChildren();
  $("#sites").replaceChildren();
  $("#shoplist").replaceChildren();
  notice("");
}

function renderSites(sites) {
  const list = $("#sites");
  list.replaceChildren();
  for (const site of sites) {
    const row = document.createElement("li");
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = site.name;
    const note = document.createElement("span");
    note.className = "note";
    note.textContent = site.note || SITE_LABELS[site.state] || site.state;
    row.append(dot(site.state === "ready" && site.note ? "warn" : site.state), name, note);
    if (site.state !== "ready") {
      const show = document.createElement("button");
      show.className = "secondary";
      show.textContent = "Show tab";
      show.onclick = () => post("/api/focus", {job: jobId, site: site.name}).catch(() => {});
      row.append(show);
    }
    list.append(row);
  }
  const ready = sites.length > 0 && sites.every((site) => site.state === "ready");
  $("#go").disabled = !ready;
  $("#go").textContent = ready ? "Search all shops" : "Waiting for " + sites.filter((site) => site.state !== "ready").map((site) => site.name).join(", ");
}

function shopRow(shop) {
  $("#shops").classList.remove("hidden");
  const row = document.createElement("li");
  row.dataset.shop = shop;
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = shop;
  const note = document.createElement("span");
  note.className = "note";
  note.textContent = "searching…";
  row.append(dot("running"), name, note);
  $("#shoplist").append(row);
  return row;
}

function fillShop(shop, match) {
  let row = $("#shoplist").querySelector('li[data-shop="' + CSS.escape(shop) + '"]');
  if (!row) row = shopRow(shop);
  row.replaceChildren(dot(match.error ? "error" : "done"));
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = shop;
  const note = document.createElement("span");
  note.className = "note";
  note.textContent = match.error || match.price_text || "—";
  row.append(name, note);
}

function card(match, best) {
  const article = document.createElement("article");
  article.className = "card" + (best ? " best" : "");
  const heading = document.createElement("h2");
  heading.textContent = match.label;
  if (best) {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = "Cheapest";
    heading.append(badge);
  }
  article.append(heading);
  if (match.error) {
    const error = document.createElement("p");
    error.className = "error";
    error.textContent = match.error;
    article.append(error);
    return article;
  }
  const title = document.createElement("p");
  title.className = "listing";
  title.textContent = match.title;
  const price = document.createElement("p");
  price.className = "price";
  price.textContent = match.price_text || "—";
  const detail = document.createElement("p");
  detail.className = "detail";
  detail.textContent = match.detail;
  const links = document.createElement("p");
  links.className = "links";
  if (match.url) links.append(link(match.url, "Open this listing"), " · ");
  if (match.search_url) links.append(link(match.search_url, "Open the search"));
  article.append(title, price, detail, links);
  return article;
}

function renderCards(list) {
  const priced = list.filter((item) => item.price_gbp !== null && item.price_gbp !== undefined);
  let best = null;
  for (const item of priced) if (best === null || item.price_gbp < best.price_gbp) best = item;
  const cards = $("#cards");
  cards.replaceChildren();
  for (const item of list) cards.append(card(item, item === best));
}

function handle(event) {
  switch (event.kind) {
    case "warmup":
      $("#warmup").classList.remove("hidden");
      renderSites(event.sites || []);
      break;
    case "shop-start":
      shopRow(event.shop);
      break;
    case "match":
      fillShop(event.shop, event.match);
      break;
    case "challenge":
      notice("Bot check on " + event.host + " — solve it in the Chrome window; waiting. If it is in a background tab, click its tab in Chrome.");
      break;
    case "challenge-clear":
      notice("");
      break;
    case "done": {
      $("#warmup").classList.add("hidden");
      $("#results").classList.remove("hidden");
      $("#heading").textContent = event.heading || "Results";
      renderCards(event.matches || []);
      const bits = [];
      if (event.rate) bits.push("USD converted at " + Number(event.rate).toFixed(5) + " GBP per USD" + (event.rate_note ? " (" + event.rate_note + ")" : "") + ".");
      if (event.eur_rate) bits.push("EUR converted at " + Number(event.eur_rate).toFixed(5) + " GBP per EUR.");
      bits.push("JustBooks and ZVAB search books written in " + event.language_name + ".");
      $("#rates").textContent = bits.join(" ");
      finish("Search finished.");
      break;
    }
    case "failed":
      finish(event.error || "Search failed.", true);
      break;
  }
}

function finish(message, isError) {
  notice(message, isError);
  $("#search").disabled = false;
  if (source) {
    source.close();
    source = null;
  }
}

function listen(id) {
  if (source) source.close();
  source = new EventSource("/api/events?job=" + encodeURIComponent(id) + "&k=" + encodeURIComponent(TOKEN));
  source.onmessage = (message) => {
    const event = JSON.parse(message.data);
    // EventSource reconnects and replays, so ignore anything already handled.
    if (event.seq && event.seq <= lastSeq) return;
    lastSeq = event.seq || lastSeq;
    handle(event);
  };
  source.onerror = () => {
    if (source && source.readyState === EventSource.CLOSED) finish("Lost the progress stream; the search may still be running.", true);
  };
}

$("#form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = {
    title: (form.get("title") || "").trim(),
    author: (form.get("author") || "").trim(),
    isbn: (form.get("isbn") || "").trim(),
    year: (form.get("year") || "").trim(),
    language: form.get("language") || "any",
    shipTo: form.get("shipTo") || "both",
    skipWarmup: form.get("skipWarmup") === "on",
  };
  resetPanels();
  $("#search").disabled = true;
  notice("Starting…");
  try {
    const started = await post("/api/search", payload);
    jobId = started.job;
    listen(jobId);
  } catch (error) {
    finish(error.message, true);
  }
});

$("#go").onclick = () => post("/api/go", {job: jobId}).catch((error) => notice(error.message, true));
$("#force").onclick = () => post("/api/go", {job: jobId}).catch((error) => notice(error.message, true));
$("#quit").onclick = async (event) => {
  event.preventDefault();
  await post("/api/quit", {}).catch(() => {});
  document.body.replaceChildren(document.createTextNode("Server stopped. Close this tab."));
};

if (PREFILL.title) $("#form").elements.title.value = PREFILL.title;
if (PREFILL.author) $("#form").elements.author.value = PREFILL.author;
if (PREFILL.isbn) $("#form").elements.isbn.value = PREFILL.isbn;
if (PREFILL.year) $("#form").elements.year.value = PREFILL.year;
if (PREFILL.language) $("#form").elements.language.value = PREFILL.language;
if (PREFILL.shipTo) $("#form").elements.shipTo.value = PREFILL.shipTo;
</script>
</body>
</html>
"""


@dataclass
class Job:
    id: str
    query: dict
    events: list = field(default_factory=list)
    cond: threading.Condition = field(default_factory=threading.Condition)
    go: threading.Event = field(default_factory=threading.Event)
    focus: str = ""
    finished: bool = False

    def emit(self, kind: str, **fields) -> None:
        with self.cond:
            payload = {"seq": len(self.events) + 1, "kind": kind}
            payload.update(fields)
            self.events.append(payload)
            self.cond.notify_all()

    def last_seq(self) -> int:
        with self.cond:
            return len(self.events)

    def wait_since(self, after: int, timeout: float = 15.0) -> list:
        with self.cond:
            if len(self.events) <= after and not self.finished:
                self.cond.wait(timeout)
            return self.events[after:]

    def finish(self, error: str = "") -> None:
        # Emit before marking finished: the event stream stops as soon as it sees
        # finished, and the failure would otherwise race ahead of the close.
        if error:
            self.emit("failed", error=error)
        with self.cond:
            self.finished = True
            self.cond.notify_all()


class Searcher:
    """Owns Chrome and Playwright on one thread, and runs searches one at a time."""

    def __init__(self, profile: Path):
        self.profile = profile
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.queue: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None
        self.stopping = threading.Event()
        self.dead = ""
        self.rate: float | None = None
        self.rate_note = ""
        self.eur_rate: float | None = None
        self.eur_note = ""

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="searcher", daemon=True)
        self.thread.start()

    def stop(self, timeout: float = 15.0) -> None:
        """Ask the worker to finish, so it can shut Chrome down cleanly."""
        self.stopping.set()
        self.queue.put(None)
        if self.thread is not None:
            self.thread.join(timeout)

    def submit(self, query: dict) -> Job | str:
        if self.dead:
            return self.dead
        with self.lock:
            if any(not job.finished for job in self.jobs.values()):
                return "A search is already running; wait for it to finish."
            # Keep the last few finished jobs for anyone still reading their events.
            finished = [job_id for job_id, job in self.jobs.items() if job.finished]
            for job_id in finished[:-10]:
                self.jobs.pop(job_id, None)
        job = Job(id=uuid.uuid4().hex[:12], query=query)
        with self.lock:
            self.jobs[job.id] = job
        self.queue.put(job)
        return job

    def job(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    # -- worker thread -----------------------------------------------------
    def _run(self) -> None:
        from playwright.sync_api import sync_playwright

        try:
            port = free_port()
            chrome = launch_chrome(port, self.profile)
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                    context = browser.contexts[0]
                    page = context.pages[0] if context.pages else context.new_page()
                    while True:
                        job = self.queue.get()
                        if job is None or self.stopping.is_set():
                            break
                        self._search(job, context, page)
            finally:
                chrome.terminate()
                try:
                    chrome.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    chrome.kill()
        except BaseException as exc:  # Chrome died, Playwright is missing, …
            print(f"\nSearch worker stopped: {exc}", flush=True)
            self.dead = f"Search worker stopped: {exc}"
            with self.lock:
                pending = [job for job in self.jobs.values() if not job.finished]
            for job in pending:
                job.finish(self.dead)

    def _confirm(self, job: Job):
        """Warm-up gate for the local page: wait for its button, report site state."""

        def confirm(tabs, probes) -> list[dict]:
            context = tabs[0][1].context
            deadline = time.time() + 1800
            sites: list[dict] = []
            while True:
                sites = warmup_status(context, tabs, probes)
                job.emit("warmup", sites=sites)
                if job.go.is_set():
                    break
                if self.stopping.is_set():
                    raise RuntimeError("Server stopped during warm-up.")
                if job.focus:
                    for name, tab in tabs:
                        if name == job.focus:
                            try:
                                tab.bring_to_front()
                            except Exception:
                                pass
                    job.focus = ""
                if all(site["state"] == "closed" for site in sites):
                    raise RuntimeError("All warm-up tabs were closed.")
                if time.time() > deadline:
                    raise RuntimeError("Warm-up was not confirmed within 30 minutes.")
                time.sleep(CONTROL_POLL_S)
            waiting = [site["name"] for site in sites if site["state"] != "ready"]
            if waiting:
                print(f"Starting with {', '.join(waiting)} not confirmed clear.", flush=True)
            return sites

        return confirm

    def _search(self, job: Job, context, page) -> None:
        query = job.query
        author, title = query["author"], query["title"]
        isbn, year, language = query["isbn"], query["year"], query["language"]
        language_name = query["language_name"]
        set_reporter(job.emit)
        job.emit("job-start", query={key: value for key, value in query.items() if key != "language_name"})
        print(f"\nSearching for {title or isbn}…", flush=True)
        try:
            if self.rate is None:
                self.rate, self.rate_note = fetch_usd_gbp()
                self.eur_rate, self.eur_note = fetch_gbp_rate("EUR")
            rate = self.rate or 0.0
            rate_note = self.rate_note
            eur_rate = self.eur_rate or rate
            eur_note = self.eur_note or rate_note
            if not query.get("skip_warmup"):
                ship_to = str(query.get("ship_to") or "BOTH").upper()
                warmup(
                    page,
                    {
                        "JustBooks": justbooks_search_url(
                            author, title, year, isbn, language, "GB" if ship_to == "BOTH" else ship_to
                        ),
                        "Alibris.com": alibris_search_url("alibris.com", author, title, year, isbn),
                        "Alibris.co.uk": alibris_search_url("alibris.co.uk", author, title, year, isbn),
                        "AwesomeBooks": awesomebooks_search_url(author, title, year, isbn),
                    },
                    confirm=self._confirm(job),
                )
            shops = [
                ("JustBooks", lambda: justbooks_quote(
                    page, author, title, year, isbn, language, query.get("ship_to") or "BOTH", eur_rate
                )),
                (
                    "Alibris.com",
                    lambda: alibris_match(page, "alibris.com", author, title, "USD", rate, rate_note, year, isbn),
                ),
                (
                    "Alibris.co.uk",
                    lambda: alibris_match(page, "alibris.co.uk", author, title, "GBP", rate, rate_note, year, isbn),
                ),
                (
                    "eBay.com",
                    lambda: ebay_match(page, "ebay.com", author, title, "1", "10001", rate, rate_note, year, isbn),
                ),
                (
                    "eBay.co.uk",
                    lambda: ebay_match(page, "ebay.co.uk", author, title, "3", "SW1A1AA", rate, rate_note, year, isbn),
                ),
                ("AwesomeBooks", lambda: awesomebooks_match(page, author, title, year, isbn)),
                (
                    "ZVAB",
                    lambda: zvab_match(
                        page, author, title, rate, eur_rate, eur_note, year, isbn, language, language_name
                    ),
                ),
            ]
            found = []
            for name, run in shops:
                print(f"Searching {name}…", flush=True)
                job.emit("shop-start", shop=name)
                match = run()
                found.append(match)
                if match.error:
                    print(f"{name}: {match.error}", flush=True)
                else:
                    print(f"{name}: {match.price_text} — {match.title}", flush=True)
                job.emit("match", shop=name, match=asdict(match))
            heading, _ = display_heading(author, title, isbn, year, language_name)
            if not title:
                heading = next((m.title for m in found if m.title and not m.error), heading)
            job.emit(
                "done",
                heading=heading,
                matches=[asdict(match) for match in found],
                rate=rate,
                rate_note=rate_note,
                eur_rate=eur_rate,
                eur_note=eur_note,
                language_name=language_name,
            )
        except Exception as exc:
            print(f"Search failed: {exc}", flush=True)
            job.finish(str(exc))
            return
        finally:
            set_reporter(None)
        job.finish()


class App:
    """State the HTTP handler needs: the worker, the access token, the form prefill."""

    def __init__(self, searcher: Searcher, prefill: dict):
        self.searcher = searcher
        self.token = uuid.uuid4().hex[:16]
        self.prefill = prefill

    def token_ok(self, token: str | None) -> bool:
        return bool(token) and token == self.token

    def page(self) -> bytes:
        prefill = json.dumps(self.prefill).replace("</", "<\\/")
        return WEB_PAGE.replace("__TOKEN__", self.token).replace("__PREFILL__", prefill).encode()


class AppHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args) -> None:  # keep the console for search progress
        pass

    @property
    def app(self) -> App:
        return self.server.app

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, "application/json", json.dumps(payload).encode())

    def do_GET(self) -> None:
        parts = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(parts.query)
        if parts.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", self.app.page())
            return
        if parts.path == "/api/events":
            self._events(params)
            return
        if parts.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        parts = urllib.parse.urlsplit(self.path)
        if not self.app.token_ok(self.headers.get("X-Bookcmp-Token")):
            self._json(403, {"error": "bad or missing token"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            self._json(400, {"error": "bad JSON"})
            return
        if parts.path == "/api/search":
            self._search(data)
        elif parts.path in ("/api/go", "/api/focus"):
            job = self.app.searcher.job(str(data.get("job") or ""))
            if job is None:
                self._json(404, {"error": "no such job"})
                return
            if parts.path == "/api/go":
                job.go.set()
            else:
                job.focus = str(data.get("site") or "")
            self._json(200, {"ok": True})
        elif parts.path == "/api/quit":
            self._json(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._json(404, {"error": "not found"})

    def _events(self, params: dict) -> None:
        if not self.app.token_ok((params.get("k") or [""])[0]):
            self._json(403, {"error": "bad or missing token"})
            return
        job = self.app.searcher.job((params.get("job") or [""])[0])
        if job is None:
            self._json(404, {"error": "no such job"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        after = 0
        try:
            while True:
                events = job.wait_since(after, timeout=10.0)
                for event in events:
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                    after = event["seq"]
                if not events and not job.finished:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                if job.finished and after >= job.last_seq():
                    break
        except (BrokenPipeError, ConnectionResetError):
            return

    def _search(self, data: dict) -> None:
        try:
            isbn = normalize_isbn(str(data["isbn"])) if data.get("isbn") else None
            language, language_name = normalize_language(str(data.get("language") or "any"))
            year = int(data["year"]) if data.get("year") else None
            if year is not None and not 1000 <= year <= 2100:
                raise ValueError("Year must be between 1000 and 2100.")
        except (KeyError, ValueError) as exc:
            self._json(400, {"error": str(exc)})
            return
        author = str(data.get("author") or "").strip()
        title = str(data.get("title") or "").strip()
        if not isbn and not title:
            self._json(400, {"error": "Give a title or an ISBN."})
            return
        ship_to = str(data.get("shipTo") or "both").upper()
        if ship_to not in {"BOTH", "GB", "US"}:
            self._json(400, {"error": "Ship-to must be both, GB or US."})
            return
        result = self.app.searcher.submit(
            {
                "author": author,
                "title": title,
                "isbn": isbn,
                "year": year,
                "language": language,
                "language_name": language_name,
                "ship_to": ship_to,
                "skip_warmup": bool(data.get("skipWarmup")),
            }
        )
        if isinstance(result, str):
            self._json(409, {"error": result})
            return
        self._json(200, {"job": result.id})


def serve_app(app: App, port: int) -> None:
    """Serve the local search page, and keep serving until Ctrl-C or the page's Stop button."""
    server = None
    last_error = None
    for candidate in range(port, port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), AppHandler)
            port = candidate
            break
        except OSError as exc:
            last_error = exc
    if server is None:
        raise SystemExit(f"Could not listen near port {port}: {last_error}")
    server.app = app  # type: ignore[attr-defined]
    server.daemon_threads = True
    url = f"http://127.0.0.1:{port}/?k={app.token}"
    print(f"Open {url}", flush=True)
    print("Ctrl-C here, or “Stop server” on the page, to quit.", flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.", flush=True)
    finally:
        server.server_close()


def run_app(args, author: str, title: str, isbn: str | None, year: int | None, language: str, language_name: str) -> None:
    profile = resolve_profile(args.profile)
    print(f"Chrome profile: {profile}", flush=True)
    searcher = Searcher(profile)
    print("Fetching USD and EUR to GBP rates…", flush=True)
    try:
        searcher.rate, searcher.rate_note = fetch_usd_gbp()
        searcher.eur_rate, searcher.eur_note = fetch_gbp_rate("EUR")
    except Exception as exc:
        print(f"Could not fetch rates yet ({exc}); will try again with the first search.", flush=True)
    searcher.start()
    app = App(
        searcher,
        prefill={
            "author": author,
            "title": title,
            "isbn": isbn or "",
            "year": year or "",
            "language": language if language != "ANY" else "any",
            "shipTo": args.ship_to,
        },
    )
    try:
        serve_app(app, args.port)
    finally:
        searcher.stop()


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
        default="any",
        help="Language of the book on JustBooks and ZVAB (default: any). "
        "English, German, French, Spanish, Italian, Dutch, or any "
        "(codes EN, DE, FR, ES, IT, NL, ANY). Alibris, eBay, and AwesomeBooks do not filter by language.",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--ship-to",
        default="both",
        choices=("both", "GB", "US"),
        help="JustBooks destination (default: both). With both, the search runs for the "
        "United Kingdom and the United States and the cheaper total is kept, with both "
        "quoted. Booklooker offers are priced at the seller's own rate for the country; "
        "GB and US both fall in booklooker's non-EU 'Welt' column.",
    )
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
        help="Skip opening JustBooks/Alibris/AwesomeBooks before searching (use when clearance is still fresh). "
        "Use --no-skip-warmup to force the warmup tabs (default).",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve a local page and search from there instead of the command line. "
        "Title/author/ISBN/year/language given here only prefill the form.",
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
    if not args.serve and not isbn and not title:
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

    if args.serve:
        run_app(args, author, title, isbn, args.year, language, language_name)
        return

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
            year = args.year
            if not args.skip_warmup:
                # Warm up the URLs the search will really use: Cloudflare clears one
                # URL at a time, so a home page without a check proves nothing.
                warmup(
                    page,
                    {
                        "JustBooks": justbooks_search_url(
                            author, title, year, isbn, language, "GB" if args.ship_to == "both" else args.ship_to
                        ),
                        "Alibris.com": alibris_search_url("alibris.com", author, title, year, isbn),
                        "Alibris.co.uk": alibris_search_url("alibris.co.uk", author, title, year, isbn),
                        "AwesomeBooks": awesomebooks_search_url(author, title, year, isbn),
                    },
                )
            if isbn:
                print(f"ISBN: {isbn}", flush=True)
            if year is not None:
                print(f"Publication year: {year}", flush=True)
            print(f"Book language: {language_name}", flush=True)
            print("Searching JustBooks…", flush=True)
            justbooks = justbooks_quote(
                page, author, title, year, isbn, language, args.ship_to, eur_rate
            )
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
