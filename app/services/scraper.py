"""
Scraper service for extracting phone numbers and associated business names from
Google local search results. This implementation uses Playwright to drive a
headless browser, applies a number of heuristics to avoid bot detection,
resiliently extracts information across changing page structures, and yields
results as dictionaries containing both the phone number and the business
name. It also exposes hooks for graceful shutdown and logs progress using
a centralized logger.
"""

import asyncio
from asyncio import CancelledError
import random
import urllib.parse
import base64
import unicodedata
from typing import AsyncGenerator, List, Set, Optional, Dict, Tuple, Any

try:
    # Import Playwright lazily.  In some environments Playwright may
    # not be installed (e.g. during unit tests or limited runtimes).
    from playwright.async_api import (
        async_playwright,
        TimeoutError as PWTimeoutError,
        Error as PWError,
    )
except ImportError:  # pragma: no cover -- allow import when Playwright missing
    async_playwright = None  # type: ignore
    # Define dummy exceptions to satisfy references in the code.  All
    # Playwright interactions will raise ImportError at runtime if
    # async_playwright is None.
    class _DummyPlaywrightError(Exception):
        pass

    PWTimeoutError = _DummyPlaywrightError  # type: ignore
    PWError = _DummyPlaywrightError  # type: ignore

from ..config import settings
from ..utils.phone import extract_phones_from_text, normalize_br
from ..utils.logs import setup_logger


# Initialise a module‑level logger. Using a single logger ensures
# consistent formatting and avoids reattaching handlers on each import.
log = setup_logger("scraper")

# Base search URL for Google Local results. The `tbm=lcl` query parameter
# restricts results to local business listings. The `uule` parameter is
# computed per city to localize the search.
SEARCH_FMT = (
    "https://www.google.com/search?tbm=lcl&hl=pt-BR&gl=BR&q={query}&start={start}{uule}"
)

# A secondary search format that falls back to the generic Google search
# without the local ("tbm=lcl") restriction.  This is used when local
# searches return few or no leads for a given niche/city combination.
# Note: the `uule` parameter is not appended for general searches as it
# appears to have no effect outside of local results.  See
# docs from Google for more information.
SEARCH_FMT_GENERAL = (
    "https://www.google.com/search?hl=pt-BR&gl=BR&q={query}&start={start}"
)

# CSS selectors for high‑level result containers on Google local search
RESULT_CONTAINERS = [
    ".rlfl__tls",
    ".VkpGBb",
    ".rllt__details",
    ".rllt__wrapped",
    "div[role='article']",
    "#search",
    "div[role='main']",
    "#rhs",
    ".kp-wholepage",
]

# CSS selectors for links to individual business listings (cards). These
# selectors capture both the newer Maps URLs and legacy local result URLs.
LISTING_LINK_SELECTORS = [
    "a[href*='/local/place']",
    "a[href*='://www.google.com/local/place']",
    "a[href*='://www.google.com/maps/place']",
    "a[href^='https://www.google.com/maps/place']",
    "a[href*='ludocid=']",
    "a[href*='/search?'][href*='ludocid']",
    "a[href*='/search?'][href*='lrd=']",
]

# Labels of consent buttons that Google may present. Different languages and
# A/B tests use different labels; covering multiple variants improves our
# chance of dismissing the consent dialog.
CONSENT_BUTTONS = [
    "button#L2AGLb",
    "button:has-text('Aceitar tudo')",
    "button:has-text('Concordo')",
    "button:has-text('Aceitar')",
    "button:has-text('Aceitar cookies')",
    "button:has-text('Aceitar todos')",
    "button:has-text('I agree')",
    "button:has-text('Accept all')",
    "button:has-text('Accept cookies')",
]

# Candidate selectors for extracting business names from a card or page.
# These are evaluated when attempting to find a name near a phone number.
NAME_CANDIDATES = [
    ".DUwDvf",  # heading in Google Maps (ficha)
    "h1[role='heading'] span",
    "h1[role='heading']",
    "h1",
    "h2",
    "h3",
    ".dbg0pd",
    ".rllt__details > div:first-child",
    "div[role='heading'] span",
    ".qrShPb span",
    ".SPZz6b span",
    ".qBF1Pd",
    ".fontHeadlineSmall",
    ".OSrXXb",
]

# Selectors com prioridade para o NOME EXATO do card (na ficha)
PRIMARY_NAME_SELECTORS = [
    ".DUwDvf",                         # título principal da ficha
    "h1[role='heading'] span",
    "h1[role='heading']",
    "meta[itemprop='name']::attr(content)",  # atributo content
    ".qrShPb span",
    ".SPZz6b span",
]

# Pool of user agent strings to randomize between requests. Rotating
# user agents helps reduce the likelihood of bot detection.
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 13; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
]


def _norm_ascii(s: str) -> str:
    """Remove accents and diacritics, returning a normalized ASCII string."""
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", s or "")
        if not unicodedata.combining(ch)
    )


def _clean_query(s: str) -> str:
    """Collapse whitespace and strip leading/trailing spaces."""
    s = (s or "").strip()
    return " ".join(s.split())


def _quoted_variants(q: str) -> List[str]:
    """
    Return a list of query variants including quoted and singular forms. If
    the query contains spaces it will produce a quoted version, and if it
    ends with 's' it will produce a singular version.
    """
    out = [q]
    if " " in q:
        out.append(f'"{q}"')
    if q.endswith("s"):
        out.append(q[:-1])
    # Deduplicate while preserving order
    return list(dict.fromkeys(out))


def _niche_variants(q: str) -> List[str]:
    """
    Generate variants of the niche search term. Expands synonyms for known
    niches and applies quoting logic via `_quoted_variants`.
    """
    q = _clean_query(q)
    base = [q]
    synonyms = {
        "restaurantes veganos": ["restaurante vegano", "comida vegana", "vegano"],
        "distribuidores de alimentos": [
            "distribuidora de alimentos",
            "atacadista de alimentos",
            "atacado de alimentos",
        ],
        "médico": ["médicos", "consultório médico", "clínica"],
    }
    for k, alts in synonyms.items():
        if k in q.lower():
            base += alts
    out: List[str] = []
    for b in base:
        out += _quoted_variants(b)
    return list(dict.fromkeys([_clean_query(x) for x in out if x.strip()]))


def _city_alias(city: str) -> str:
    """
    Normalize common city abbreviations to their full names. Allows users
    to specify shorthand like 'bh' or 'sp' and still search correctly.
    """
    c = (city or "").strip()
    lower = c.lower()
    aliases = {
        "bh": "Belo Horizonte, MG",
        "belo horizonte": "Belo Horizonte, MG",
        "sp": "São Paulo, SP",
        "rj": "Rio de Janeiro, RJ",
        "poa": "Porto Alegre, RS",
        "sampa": "São Paulo, SP",
    }
    return aliases.get(lower, c)


def _uule_for_city(city: str) -> str:
    """
    Compute the uule parameter for a given city. The uule parameter is a
    base64‑encoded representation of the location used by Google to
    localize search results. This function ensures that even if the city
    is not provided in the expected 'City, State' format, a fallback is
    used by appending ',Brazil'.
    """
    c = _city_alias(city)
    if not c:
        return ""
    if "," not in c:
        c = f"{c},Brazil"
    b64 = base64.b64encode(c.encode("utf-8")).decode("ascii")
    return "&uule=" + urllib.parse.quote("w+CAIQICI" + b64, safe="")


async def _try_accept_consent(page) -> None:
    """
    Attempt to click any visible consent buttons on the page. Ignores
    exceptions if elements are not found. This is a best‑effort approach
    since consent dialogs vary by region and A/B test.
    """
    try:
        for sel in CONSENT_BUTTONS:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                await loc.first.click()
                await page.wait_for_timeout(250)
                break
    except Exception:
        pass


async def _humanize(page) -> None:
    """
    Perform simple, random user‑like interactions on the page. Moving the
    mouse and scrolling reduces the chance of bot detection by mimicking
    human behavior. Failures are ignored.
    """
    try:
        await page.mouse.move(
            random.randint(40, 420), random.randint(60, 320), steps=random.randint(6, 14)
        )
        await page.evaluate(
            "() => { window.scrollBy(0, Math.floor(180 + Math.random()*280)); }"
        )
        await page.wait_for_timeout(random.randint(260, 520))
    except Exception:
        pass


async def _primary_business_name(page) -> Optional[str]:
    """
    Return the main business name when on the listing detail page (Google Maps card).
    Prioritises the exact card title and safe fallbacks.
    """
    try:
        # meta[itemprop='name'] requires attribute access, handle separately
        meta = await page.locator("meta[itemprop='name']").count()
        if meta > 0:
            content = await page.locator("meta[itemprop='name']").first.get_attribute("content")
            if content and content.strip():
                return content.strip()

        for sel in [s for s in PRIMARY_NAME_SELECTORS if "::attr" not in s and "meta" not in s]:
            loc = page.locator(sel)
            if await loc.count() > 0:
                text = await loc.first.text_content()
                if text:
                    t = text.strip()
                    if t:
                        return t

        # As a very last resort, try <title> and strip suffixes " - Google Maps"/" – Google Maps"
        title_loc = page.locator("title")
        if await title_loc.count() > 0:
            t = (await title_loc.first.text_content()) or ""
            t = t.replace(" - Google Maps", "").replace(" – Google Maps", "")
            t = t.replace(" - Pesquisa Google", "").replace(" – Pesquisa Google", "")
            t = t.strip()
            if t:
                return t
    except Exception:
        pass
    return None


async def _closest_name_for(page, element) -> Optional[str]:
    """
    Given a DOM element (typically a phone link), find the closest
    reasonable business name. Walks up the DOM to search for elements
    matching NAME_CANDIDATES selectors. Returns the first non‑empty
    text found or None.
    """
    try:
        # Evaluate in the page context: search upwards for a container and
        # query candidate selectors within that container. If nothing found,
        # try aria-label of the anchor to the listing.
        return await page.evaluate(
            f"""(el) => {{
                let node = el.closest('.VkpGBb,.dbg0pd,[role="article"],.rllt__details,.rlfl__tls,#search,.kp-wholepage') || el.parentElement;
                const sels = {NAME_CANDIDATES!r};
                while (node) {{
                  for (const s of sels) {{
                    const cand = node.querySelector(s);
                    if (cand && cand.textContent) {{
                      const t = cand.textContent.trim();
                      if (t) return t;
                    }}
                  }}
                  // tenta via aria-label do link de card
                  const a = node.querySelector('a[href*="/maps/place"],a[href*="/local/place"]');
                  if (a) {{
                      const al = (a.getAttribute('aria-label') || a.textContent || '').trim();
                      if (al) return al;
                  }}
                  node = node.parentElement;
                }}
                return null;
            }}""",
            element,
        )
    except Exception:
        return None


async def _extract_phones_from_page(page, default_name: Optional[str] = None) -> List[Dict[str, Optional[str]]]:
    """
    Extract phone numbers and corresponding business names from the current
    page. The return value is a list of dictionaries with 'phone' and
    'name' keys. Phone numbers are normalized to include the country
    prefix. Names may be None if no name could be determined.

    The function performs extraction in multiple passes:
    1. Clickable tel: links are processed, and a nearby name is
       attempted (or the primary card name if available).
    2. Known result container blocks are scanned; any phone numbers
       found within them are associated with a heading or title found
       inside the same block (fallback to primary name if present).
    3. As a fallback, the entire page's inner text is scanned for phone
       numbers; if a primary name exists, it is used.
    """
    leads: Dict[str, Dict[str, Optional[str]]] = {}
    try:
        # Determine whether we are on a listing (business details) page.  Only
        # compute a primary business name when inside a Google Maps card
        # (URL containing "/maps/place" or "/local/place").  On search
        # result pages, avoid setting a fallback name to prevent all
        # extracted numbers from inheriting the same business name.  When
        # default_name is explicitly provided (e.g. when called from
        # _open_and_extract_from_listing), honour it.
        primary: Optional[str] = None
        if default_name:
            primary = default_name
        else:
            try:
                url: str = page.url or ""
            except Exception:
                url = ""
            if "/maps/place" in url or "/local/place" in url:
                primary = await _primary_business_name(page)

        # Passo 1: <a href="tel:"> anchors e seu texto
        anchors = await page.query_selector_all("a[href^='tel:']")
        for a in anchors or []:
            try:
                href = (await a.get_attribute("href")) or ""
                text = (await a.inner_text()) or (await a.text_content()) or ""
                phone = normalize_br(href.replace("tel:", "")) or normalize_br(text)
                if not phone:
                    continue
                name = primary or await _closest_name_for(page, a)
                if phone not in leads:
                    leads[phone] = {"phone": phone, "name": (name or None)}
            except Exception:
                continue

        # Passo 2: Varre blocos de resultados
        for sel in RESULT_CONTAINERS:
            try:
                blocks = await page.query_selector_all(sel)
                for block in blocks or []:
                    try:
                        txt = (await block.inner_text()) or ""
                    except Exception:
                        txt = ""
                    if not txt:
                        continue

                    extracted = extract_phones_from_text(txt)
                    if not extracted:
                        continue

                    # Tenta achar um nome dentro do bloco; se nada for
                    # encontrado e estivermos em uma ficha (primary definido),
                    # use-o como fallback.  Nas páginas de resultados
                    # (primary é None), não atribua nenhum nome; isso evita
                    # replicar o mesmo nome para múltiplos telefones.
                    try:
                        name_in_block = await page.evaluate(
                            f"""(el) => {{
                                const sels = {NAME_CANDIDATES!r};
                                for (const s of sels) {{
                                   const c = el.querySelector(s);
                                   if (c && c.textContent) {{
                                       const t = c.textContent.trim();
                                       if (t) return t;
                                   }}
                                }}
                                // fallback: aria-label do link para a ficha
                                const a = el.querySelector('a[href*="/maps/place"],a[href*="/local/place"]');
                                if (a) {{
                                    const al = (a.getAttribute('aria-label') || a.textContent || '').trim();
                                    if (al) return al;
                                }}
                                return null;
                            }}""",
                            block,
                        )
                    except Exception:
                        name_in_block = None

                    # Se nada encontrado, só use o 'primary' se estiver definido
                    if not name_in_block and primary:
                        name_in_block = primary

                    for ph in extracted:
                        if ph not in leads:
                            leads[ph] = {"phone": ph, "name": (name_in_block or None)}
            except Exception:
                continue

        # Passo 3: Fallback geral no corpo
        if not leads:
            try:
                body_text = await page.evaluate(
                    "() => document.body ? (document.body.innerText || '') : ''"
                )
            except Exception:
                body_text = ""
            for ph in extract_phones_from_text(body_text or ""):
                if ph not in leads:
                    leads[ph] = {"phone": ph, "name": (primary or None)}

    except Exception:
        pass

    return list(leads.values())


def _city_variants(city: str) -> List[str]:
    """
    Produce variations of the city string to broaden search queries. It
    returns combinations with and without the state abbreviation and with
    optional 'em ' prefix. Accent‑stripped variants are also included.
    """
    c = _city_alias(city)
    base = [c, f"{c} MG", f"{c}, MG"]
    no_acc = list({_norm_ascii(x) for x in base})
    variants = base + [f"em {x}" for x in base] + no_acc + [f"em {x}" for x in no_acc]
    return list(dict.fromkeys(variants))


async def _is_captcha_or_sorry(page) -> bool:
    """
    Detect whether the current page is a CAPTCHA or unusual traffic page. It
    scans the page content for specific keywords and checks for recaptcha
    forms. Extensible by adding further checks for additional languages.
    """
    try:
        txt = (await page.content())[:120000].lower()
        if (
            "/sorry/" in txt
            or "unusual traffic" in txt
            or "recaptcha" in txt
            or "g-recaptcha" in txt
        ):
            return True
        sel_hit = await page.locator(
            "form[action*='/sorry'], iframe[src*='recaptcha'], #recaptcha"
        ).count()
        return sel_hit > 0
    except Exception:
        return False


def _cooldown_secs(hit: int) -> int:
    """Calculate an exponential backoff delay based on CAPTCHA hits."""
    base = 18
    mx = 110
    return min(mx, int(base * (1.6 ** max(0, hit - 1))) + random.randint(0, 9))


# ---------- Playwright: browser único, contexto por request ----------
_pw = None
_browser = None

# A global lock used to serialise Playwright initialisation. Without
# this lock multiple concurrent calls to `_ensure_browser` could try to
# start Playwright or launch a browser at the same time, leading to
# race conditions and unpredictable failures. The lock is held only
# around the startup section and does not impact subsequent browser
# usage. See `_ensure_browser` for details.
_pw_lock = asyncio.Lock()


async def _ensure_browser():
    """
    Ensure that a single Playwright browser instance is running.

    This function lazily starts Playwright and launches the configured
    browser type. A per‑module lock prevents concurrent initialisation.
    Logging statements record when the browser or Playwright are started.

    Returns:
        The running Playwright browser instance.
    """
    global _pw, _browser
    # Ensure Playwright is available before attempting to start a browser.
    if async_playwright is None:
        raise ImportError(
            "Playwright is not installed. Install the 'playwright' package to use the scraper."
        )

    async with _pw_lock:
        if _pw is None:
            log.info("Starting Playwright…")
            _pw = await async_playwright().start()
        if _browser is None:
            launch_args = {
                "headless": settings.HEADLESS,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            }
            log.info(
                f"Launching {settings.BROWSER} browser (headless={settings.HEADLESS})…"
            )
            _browser = await getattr(_pw, settings.BROWSER).launch(**launch_args)
    return _browser


async def _new_context():
    """
    Create a fresh browser context with randomized settings. Each context
    gets its own user agent, timezone, locale, viewport, and optional
    proxy configuration. We also inject scripts to mask automation
    fingerprints.
    """
    browser = await _ensure_browser()
    ua = settings.USER_AGENT or random.choice(UA_POOL)
    proxy_kwargs = {}
    proxy_server = getattr(settings, "PROXY_SERVER", None)
    if proxy_server:
        proxy_kwargs["proxy"] = {"server": proxy_server}

    context = await browser.new_context(
        user_agent=ua,
        locale="pt-BR",
        timezone_id=random.choice(["America/Sao_Paulo", "America/Bahia"]),
        extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9"},
        viewport={"width": random.randint(1200, 1360), "height": random.randint(820, 920)},
        **proxy_kwargs,
    )
    # Mask automation fingerprints: remove webdriver flag and fake languages,
    # plugins and chrome runtime. These changes help avoid simple bot
    # detections on Google and other sites.
    await context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt'] });
        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3] });
        window.chrome = { runtime: {} };
        """
    )
    return context


# ---------- navegação blindada ----------
async def _safe_goto(page, url: str, **kw):
    """Navigate to a URL while shielding against task cancellation."""
    try:
        return await asyncio.shield(page.goto(url, **kw))
    except CancelledError:
        try:
            await page.close()
        except Exception:
            pass
        raise


# ---------- abrir ficha ----------
async def _open_and_extract_from_listing(
    context,
    href: str,
    seen: Optional[Set[str]] = None,
) -> List[Dict[str, Optional[str]]]:
    """
    Open a business listing in a new page and extract phone/name pairs.

    If ``seen`` is provided, numbers present in the set will be
    excluded from the returned results and added to ``seen``. When
    ``seen`` is ``None`` the function will return all numbers found
    within the listing without filtering against previously seen
    values. A per‑listing deduplication is always applied to avoid
    returning the same phone multiple times from a single page.
    """
    out: List[Dict[str, Optional[str]]] = []
    if not href:
        return out
    # Prepend host if relative path
    if href.startswith("/"):
        href = "https://www.google.com" + href

    page2 = await context.new_page()
    try:
        # Navigate to the listing card
        await _safe_goto(page2, href, wait_until="domcontentloaded", timeout=30000)
        # Attempt to extract the primary name of the business
        primary_name = await _primary_business_name(page2)

        # Try clicking on buttons/links that reveal phone numbers
        for sel in [
            "button:has-text('Telefone')",
            "button:has-text('Ligar')",
            "a[aria-label^='Ligar']",
            "[aria-label*='Telefone']",
            "button:has-text('Contato')",
        ]:
            try:
                loc = page2.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible():
                    await loc.first.click()
                    await page2.wait_for_timeout(350)
            except Exception:
                pass

        # Give the page a moment to update after revealing numbers
        await page2.wait_for_timeout(800)
        # Extract phones/names from the listing page
        leads = await _extract_phones_from_page(page2, default_name=primary_name)

        # Local deduplication to avoid duplicate phones from the same page
        added: Set[str] = set()
        for lead in leads:
            ph = lead.get("phone")
            if not ph or ph in added:
                continue
            added.add(ph)
            # If a ``seen`` set was supplied, only include numbers not
            # previously processed.  Otherwise return all numbers.
            if seen is None or ph not in seen:
                if seen is not None:
                    seen.add(ph)
                out.append(lead)
    except (PWError, CancelledError, Exception):
        # Intentionally swallow exceptions to keep scraping robust
        pass
    finally:
        try:
            await page2.close()
        except (PWError, CancelledError, Exception):
            pass
    return out


# ---------- busca principal ----------
async def search_numbers(
    nicho: str,
    locais: List[str],
    target: int,
    *,
    max_pages: Optional[int] = None,
) -> AsyncGenerator[Dict[str, Optional[str]], None]:
    """
    Asynchronously yield phone/name pairs scraped from Google Local results.

    Args:
        nicho: The niche (category) to search for, e.g. 'Marketing'.
        locais: A list of cities to search within.
        target: The maximum number of results to return. If zero or None,
            the scraper will run indefinitely (up to the natural end of
            results).
        max_pages: Optional maximum pages per term to fetch; None means no
            explicit limit. This parameter is primarily used for testing
            because Google may present an effectively infinite result set.

    Yields:
        Dicts with keys 'phone' and 'name'.
    """
    seen: Set[str] = set()
    q_base = _clean_query(nicho)
    empty_limit = int(getattr(settings, "MAX_EMPTY_PAGES", 14))
    captcha_hits_global = 0

    context = await _new_context()
    # Log the start of a scraping job with the supplied parameters.
    log.info(
        f"Starting phone search: nicho='{nicho}', locais={locais}, target={target}, max_pages={max_pages}"
    )

    try:
        total_yield = 0
        # Outer loop over provided cities
        for local in locais:
            city = (local or "").strip()
            if not city:
                continue
            uule = _uule_for_city(city)

            # Generate search terms combining niche variants and city variants
            terms: List[str] = []
            for v in _city_variants(city):
                for qv in _niche_variants(q_base):
                    t = f"{qv} {v}".strip()
                    if t and t not in terms:
                        terms.append(t)

            # Iterate over each variant of the search term
            for term in terms:
                empty_pages = 0
                idx = 0
                captcha_hits_term = 0
                # Track whether we've switched to the generic Google search
                use_local = True
                # Count how many leads we have produced for this term (across both
                # local and general searches) to decide whether to fallback
                generated_this_term = 0

                # Log each search term for clarity. Terms include variations of the niche and city.
                log.info(f"Searching term '{term}' in city '{city}'")

                while True:
                    # Respect the overall target across all terms and cities
                    if target and total_yield >= target:
                        return
                    # Optionally stop after a number of pages to avoid infinite loops
                    if max_pages is not None and idx >= max_pages:
                        break

                    start = idx * 20
                    q = term
                    if captcha_hits_term > 0:
                        # Slightly vary the query string to bypass caching or rate limits
                        decorations = ["", " ", "  ", " ★", " ✔", " ✓"]
                        q = (term + random.choice(decorations)).strip()

                    # Choose appropriate search URL. For local searches we append the uule
                    # parameter; for generic searches we omit it entirely.
                    if use_local:
                        url = SEARCH_FMT.format(
                            query=urllib.parse.quote_plus(q), start=start, uule=uule
                        )
                    else:
                        url = SEARCH_FMT_GENERAL.format(
                            query=urllib.parse.quote_plus(q), start=start
                        )

                    # Create a new page for each request
                    page = await context.new_page()
                    page.set_default_timeout(20000)

                    try:
                        try:
                            await _safe_goto(
                                page, url, wait_until="domcontentloaded", timeout=30000
                            )
                        except (PWError, CancelledError):
                            # If navigation failed, close and retry once on a new page
                            try:
                                await page.close()
                            except Exception:
                                pass
                            page = await context.new_page()
                            page.set_default_timeout(20000)
                            await _safe_goto(
                                page, url, wait_until="domcontentloaded", timeout=30000
                            )

                        await _try_accept_consent(page)
                        await _humanize(page)

                        # Check for CAPTCHA or unusual traffic pages
                        if await _is_captcha_or_sorry(page):
                            captcha_hits_term += 1
                            captcha_hits_global += 1
                            log.warning(
                                f"CAPTCHA or unusual traffic detected (term='{term}', city='{city}', hit={captcha_hits_term}, global_hits={captcha_hits_global})."
                            )
                            # Exponential backoff to avoid repeated CAPTCHAs
                            await page.wait_for_timeout(_cooldown_secs(captcha_hits_global) * 1000)
                            if captcha_hits_term >= 2:
                                log.info(
                                    f"Skipping to next page for term '{term}' due to repeated CAPTCHA hits"
                                )
                                idx += 1
                                continue

                        try:
                            await page.wait_for_selector(
                                "a[href^='tel:']," + ",".join(RESULT_CONTAINERS),
                                timeout=8000,
                            )
                        except PWTimeoutError:
                            pass

                        leads = await _extract_phones_from_page(page)

                        # Se encontramos números, verifique se os nomes
                        # extraídos parecem confiáveis.  Se todos os nomes são
                        # iguais ou se há entradas sem nome, trate todas essas
                        # entradas como "missing" para forçar a abertura das
                        # fichas e enriquecer corretamente.  Isso evita o
                        # problema em que um nome de fallback (geralmente
                        # proveniente de uma única ficha) é associado a todos
                        # os números.
                        if leads:
                            unique_names = set(
                                (l.get("name") or "") for l in leads if l.get("name")
                            )
                            if len(unique_names) <= 1:
                                missing = leads[:]
                            else:
                                missing = [l for l in leads if not (l or {}).get("name")]
                            # Sempre tente enriquecimento quando houver nomes
                            # ausentes ou suspeitos.  Em vez de usar tarefas
                            # assíncronas em paralelo (que podem deixar
                            # exceções sem tratamento se a página for fechada),
                            # abrimos cada card sequencialmente até obter
                            # nomes para todas as entradas necessárias.  O
                            # número de fichas abertas é limitado ao número de
                            # leads encontrados para tentar cobrir todos os
                            # telefones.
                            if missing:
                                try:
                                    cards = page.locator(",".join(LISTING_LINK_SELECTORS))
                                    count = await cards.count()
                                    # Abrir no máximo tantos cards quanto o número de leads que
                                    # necessitam de enriquecimento (entradas em ``missing``).  Isso
                                    # evita abrir mais fichas do que o necessário para obter
                                    # nomes ausentes ou repetidos.
                                    to_open = min(count, len(missing))
                                    enriched: List[Dict[str, Optional[str]]] = []
                                    for i in range(to_open):
                                        try:
                                            href = await cards.nth(i).get_attribute("href")
                                        except (PWError, Exception):
                                            href = None
                                        try:
                                            # Use a fresh ``seen`` (None) when enriching missing
                                            # names so that previously seen numbers can still be
                                            # retrieved to obtain their associated business
                                            # names.  This avoids skipping phones whose names
                                            # need updating simply because they have been seen
                                            # earlier in the scraping session.
                                            res = await _open_and_extract_from_listing(context, href, None)
                                        except Exception:
                                            res = []
                                        if res:
                                            enriched.extend(res)
                                        # Opcional: se já conseguimos nomes para todas as entradas "missing", podemos parar
                                        if len({e.get("phone") for e in enriched}) >= len(missing):
                                            # break early to reduce navigation
                                            break
                                    # Mapear phone->name e injetar nos leads
                                    name_map = {
                                        e["phone"]: e.get("name")
                                        for e in enriched
                                        if e.get("phone") and e.get("name")
                                    }
                                    for l in leads:
                                        # Se o nome estiver ausente ou se todos eram repetidos, tente atualizar
                                        if not l.get("name") or (len(unique_names) <= 1):
                                            nm = name_map.get(l["phone"])
                                            if nm:
                                                l["name"] = nm
                                except (PWError, Exception):
                                    pass

                        # If we didn't find any leads on this SERP page, open listing cards sequentially.
                        if not leads:
                            try:
                                cards = page.locator(",".join(LISTING_LINK_SELECTORS))
                                count = await cards.count()
                                # Open at most 15 listings sequentially to try to extract numbers
                                to_open = min(count, 15)
                                for i in range(to_open):
                                    try:
                                        href = await cards.nth(i).get_attribute("href")
                                    except (PWError, Exception):
                                        href = None
                                    try:
                                        # When no leads were found on the current SERP page we
                                        # open listing cards sequentially to extract phone
                                        # numbers.  Deduplication against the global ``seen`` set
                                        # is desired here to avoid re‑emitting numbers that have
                                        # already been collected elsewhere.
                                        res = await _open_and_extract_from_listing(context, href, seen)
                                    except Exception:
                                        res = []
                                    if res:
                                        leads.extend(res)
                                        # Break early if we've collected a reasonable number of leads
                                        if len(leads) >= 25:
                                            break
                                # No further gathering of tasks needed since we're opening sequentially
                            except (PWError, Exception):
                                pass

                        new = 0
                        for lead in leads:
                            ph = (lead or {}).get("phone")
                            nm = (lead or {}).get("name")
                            if not ph:
                                continue
                            if ph not in seen:
                                seen.add(ph)
                                new += 1
                                total_yield += 1
                                generated_this_term += 1
                                log.debug(f"New lead: {nm or '(sem nome)'} — {ph}")
                                yield {"phone": ph, "name": nm}
                                if target and total_yield >= target:
                                    log.info(
                                        f"Target of {target} leads reached. Terminating search."
                                    )
                                    try:
                                        await page.close()
                                    except Exception:
                                        pass
                                    return

                        # Update empty page counter. If no new leads, increment; otherwise reset.
                        empty_pages = empty_pages + 1 if new == 0 else 0

                        # If we've exhausted a number of pages without new leads, decide whether
                        # to fallback to general search or move to the next term.
                        if empty_pages >= empty_limit:
                            # If still using local search and we have produced very few leads
                            # for this term, fall back to general search and reset counters.
                            if use_local and generated_this_term < 3:
                                log.info(
                                    f"Few or no leads found for term '{term}' in local search. Falling back to general search."
                                )
                                use_local = False
                                empty_pages = 0
                                idx = 0
                                captcha_hits_term = 0
                                continue
                            # Otherwise break out to the next term.
                            log.info(
                                f"Reached empty page limit ({empty_limit}) for term '{term}'. Moving to next term."
                            )
                            try:
                                await page.close()
                            except Exception:
                                pass
                            break

                        # Compute wait time between requests to mimic human behaviour and reduce detection
                        wait_ms = random.randint(320, 620) + min(
                            1800, int(idx * 48 + random.randint(140, 300))
                        )
                        await page.wait_for_timeout(wait_ms)
                        idx += 1

                    except (PWError, CancelledError, Exception):
                        # Catch and handle any Playwright or other errors.  Close the page and
                        # proceed to the next index.
                        try:
                            await page.close()
                        except Exception:
                            pass
                        idx += 1
                        continue
                    finally:
                        try:
                            if not page.is_closed():
                                await page.close()
                        except Exception:
                            pass
    finally:
        # Always close the context to free browser resources, and log summary.
        try:
            await context.close()
        except (PWError, CancelledError, Exception):
            pass
        log.info(f"Search completed. Total leads yielded: {total_yield}")


async def shutdown_playwright():
    """
    Gracefully close the Playwright browser and stop Playwright. This is
    invoked at application shutdown to release resources.
    """
    global _pw, _browser
    log.info("Shutting down Playwright and browser…")
    try:
        if _browser:
            await _browser.close()
    except (PWError, CancelledError, Exception):
        pass
    finally:
        _browser = None
    try:
        if _pw:
            await _pw.stop()
    except (PWError, CancelledError, Exception):
        pass
    finally:
        _pw = None
