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
# Expanded to cover multiple Google layout variants (2024/2025)
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
    ".uMdZh",  # 2024 local results
    ".Nv2PK",  # business card wrapper
    ".VkpGBb .cXedhc",  # nested result container
    "[data-attrid='kc:/location/location:address']",  # address containers often near phones
    ".I9GLp",  # new Maps integration
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
    "a[href*='maps/place'][data-cid]",  # Maps with CID
    "a[data-fid]",  # Feature ID links
    "a[jsname][href*='place']",  # JS-powered links
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
    "[data-attrid='title']",  # structured data title
    ".tAiQdd",  # 2024 business name
    "[aria-label*='Nome']",  # aria-label with name
    "[jsname] .fontHeadlineLarge",  # large headline in new layout
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


# ------------------------- helpers anti-erro/fechamento -------------------------

def _page_alive(page) -> bool:
    """Return True if page exists and is not closed."""
    try:
        return bool(page) and not page.is_closed()
    except Exception:
        return False


async def _safe_wait_for_selector(
    page,
    selector: str,
    *,
    timeout: int = None,
    state: str = "attached",
) -> bool:
    """
    Wait for selector with guards against TargetClosedError and timeouts.
    Returns True if the selector is observed (in the chosen state),
    otherwise False without raising.
    """
    if timeout is None:
        timeout = settings.SELECTOR_WAIT_TIMEOUT
    try:
        if not _page_alive(page):
            return False
        await page.wait_for_selector(selector, timeout=timeout, state=state)
        return True
    except (PWTimeoutError, PWError, CancelledError, Exception) as e:
        log.debug(f"Selector wait failed for '{selector[:50]}...': {e}")
        return False


# -------------------------------------------------------------------------------

async def _try_accept_consent(page) -> None:
    """
    Attempt to click any visible consent buttons on the page. Ignores
    exceptions if elements are not found. This is a best‑effort approach
    since consent dialogs vary by region and A/B test.
    """
    try:
        if not _page_alive(page):
            return
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
        if not _page_alive(page):
            return
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
    if not _page_alive(page):
        return None
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

        # As a very last resort, try <title> and strip suffixes
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
    if not _page_alive(page):
        return None
    try:
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
    Extract phone numbers and corresponding business names from the current page.
    """
    leads: Dict[str, Dict[str, Optional[str]]] = {}
    if not _page_alive(page):
        return []

    try:
        # Determine whether we are on a listing (business details) page
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

        # Passo 1: anchors tel:
        try:
            anchors = await page.query_selector_all("a[href^='tel:']")
        except Exception:
            anchors = []
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

        # Passo 2: blocos de resultados
        for sel in RESULT_CONTAINERS:
            if not _page_alive(page):
                break
            try:
                blocks = await page.query_selector_all(sel)
            except Exception:
                blocks = []
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

                if not name_in_block and primary:
                    name_in_block = primary

                for ph in extracted:
                    if ph not in leads:
                        leads[ph] = {"phone": ph, "name": (name_in_block or None)}

        # Passo 3: fallback no corpo
        if not leads and _page_alive(page):
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
    Produce variations of the city string to broaden search queries.
    """
    c = _city_alias(city)
    base = [c, f"{c} MG", f"{c}, MG"]
    no_acc = list({_norm_ascii(x) for x in base})
    variants = base + [f"em {x}" for x in base] + no_acc + [f"em {x}" for x in no_acc]
    return list(dict.fromkeys(variants))


async def _is_captcha_or_sorry(page) -> bool:
    """
    Detect whether the current page is a CAPTCHA or unusual traffic page.
    Enhanced detection with multiple indicators.
    """
    try:
        # Check URL first (fastest)
        url = page.url or ""
        if "/sorry/" in url or "showcaptcha" in url:
            return True
        
        # Check page title
        try:
            title = (await page.title()).lower()
            if "captcha" in title or "unusual traffic" in title:
                return True
        except Exception:
            pass
        
        # Check content (sample only to avoid huge payloads)
        txt = (await page.content())[:150000].lower()
        captcha_indicators = [
            "/sorry/",
            "unusual traffic",
            "recaptcha",
            "g-recaptcha",
            "captcha-box",
            "tráfego incomum",  # Portuguese
            "verify you're not a robot",
        ]
        if any(indicator in txt for indicator in captcha_indicators):
            return True
        
        # Check for CAPTCHA elements
        sel_hit = await page.locator(
            "form[action*='/sorry'], iframe[src*='recaptcha'], #recaptcha, .g-recaptcha"
        ).count()
        return sel_hit > 0
    except Exception:
        return False


def _cooldown_secs(hit: int) -> int:
    """Calculate an exponential backoff delay based on CAPTCHA hits."""
    base = settings.CAPTCHA_COOLDOWN_BASE
    mx = settings.CAPTCHA_MAX_COOLDOWN
    return min(mx, int(base * (1.5 ** max(0, hit - 1))) + random.randint(0, 12))


async def _retry_with_backoff(func, *args, max_attempts: int = None, **kwargs):
    """
    Execute a function with exponential backoff retry logic.
    Useful for recovering from transient network errors.
    """
    if max_attempts is None:
        max_attempts = settings.MAX_RETRIES
    
    last_error = None
    for attempt in range(max_attempts):
        try:
            return await func(*args, **kwargs)
        except (PWError, PWTimeoutError, Exception) as e:
            last_error = e
            if attempt < max_attempts - 1:
                delay = settings.RETRY_DELAY_MS * (1.8 ** attempt) / 1000.0
                log.warning(
                    f"Attempt {attempt + 1}/{max_attempts} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
            else:
                log.error(
                    f"All {max_attempts} attempts failed. Last error: {last_error}"
                )
    raise last_error


# ---------- Playwright: browser único, contexto por request ----------
_pw = None
_browser = None
_pw_lock = asyncio.Lock()


async def _ensure_browser():
    """
    Ensure that a single Playwright browser instance is running.
    """
    global _pw, _browser
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
    Create a fresh browser context with randomized settings.
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
async def _safe_goto(page, url: str, retries: int = 2, **kw):
    """
    Navigate to a URL with retry logic and cancellation protection.
    Applies sensible defaults for timeouts and wait conditions.
    """
    if "timeout" not in kw:
        kw["timeout"] = settings.NAVIGATION_TIMEOUT
    if "wait_until" not in kw:
        kw["wait_until"] = "domcontentloaded"
    
    for attempt in range(retries + 1):
        try:
            return await asyncio.shield(page.goto(url, **kw))
        except CancelledError:
            try:
                await page.close()
            except Exception:
                pass
            raise
        except (PWError, PWTimeoutError) as e:
            if attempt < retries:
                wait = 1.5 * (attempt + 1)
                log.warning(
                    f"Navigation to {url[:80]} failed (attempt {attempt + 1}/{retries + 1}): {e}. "
                    f"Retrying in {wait:.1f}s..."
                )
                await asyncio.sleep(wait)
            else:
                log.error(f"Failed to navigate to {url[:80]} after {retries + 1} attempts: {e}")
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
    values. A per‑listing deduplication is always applied.
    """
    out: List[Dict[str, Optional[str]]] = []
    if not href:
        return out
    if href.startswith("/"):
        href = "https://www.google.com" + href

    page2 = await context.new_page()
    try:
        # Navigate with built-in retry
        await _safe_goto(page2, href, retries=2)
        if not _page_alive(page2):
            return out

        # Wait for page to stabilize
        await asyncio.sleep(0.5)
        
        primary_name = await _primary_business_name(page2)

        # Try to reveal phone numbers by clicking buttons
        phone_reveal_selectors = [
            "button:has-text('Telefone')",
            "button:has-text('Ligar')",
            "button:has-text('Phone')",
            "a[aria-label^='Ligar']",
            "a[aria-label^='Call']",
            "[aria-label*='Telefone']",
            "[aria-label*='Phone']",
            "button:has-text('Contato')",
            "button:has-text('Contact')",
            "[data-item-id*='phone']",
        ]
        
        for sel in phone_reveal_selectors:
            try:
                if not _page_alive(page2):
                    break
                loc = page2.locator(sel)
                count = await loc.count()
                if count > 0:
                    first = loc.first
                    if await first.is_visible(timeout=1000):
                        await first.click()
                        await page2.wait_for_timeout(400)
                        log.debug(f"Clicked phone reveal button: {sel}")
            except Exception as e:
                log.debug(f"Failed to click {sel}: {e}")
                pass

        if _page_alive(page2):
            await page2.wait_for_timeout(1000)

        leads = await _extract_phones_from_page(page2, default_name=primary_name)

        added: Set[str] = set()
        for lead in leads:
            ph = lead.get("phone")
            if not ph or ph in added:
                continue
            added.add(ph)
            if seen is None or ph not in seen:
                if seen is not None:
                    seen.add(ph)
                out.append(lead)
    except (PWError, CancelledError, Exception):
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
    """
    seen: Set[str] = set()
    q_base = _clean_query(nicho)
    empty_limit = settings.MAX_EMPTY_PAGES
    captcha_hits_global = 0

    context = await _new_context()
    log.info(
        f"🔍 Starting phone search: nicho='{nicho}', locais={locais}, target={target}, max_pages={max_pages}"
    )

    try:
        total_yield = 0
        for local in locais:
            city = (local or "").strip()
            if not city:
                continue
            uule = _uule_for_city(city)

            terms: List[str] = []
            for v in _city_variants(city):
                for qv in _niche_variants(q_base):
                    t = f"{qv} {v}".strip()
                    if t and t not in terms:
                        terms.append(t)

                for term in terms:
                    empty_pages = 0
                    idx = 0
                    captcha_hits_term = 0
                    use_local = True
                    generated_this_term = 0

                    log.info(f"🔎 Searching term '{term}' in city '{city}'")

                    while True:
                        if target and total_yield >= target:
                            return
                        if max_pages is not None and idx >= max_pages:
                            break

                        start = idx * 20
                        q = term
                        if captcha_hits_term > 0:
                            decorations = ["", " ", "  ", " ★", " ✔", " ✓"]
                            q = (term + random.choice(decorations)).strip()

                        if use_local:
                            url = SEARCH_FMT.format(
                                query=urllib.parse.quote_plus(q), start=start, uule=uule
                            )
                        else:
                            url = SEARCH_FMT_GENERAL.format(
                                query=urllib.parse.quote_plus(q), start=start
                            )

                        page = await context.new_page()
                        page.set_default_timeout(settings.NAVIGATION_TIMEOUT)

                        try:
                            # Use _safe_goto with built-in retry
                            await _safe_goto(page, url, retries=2)

                            await _try_accept_consent(page)
                            await _humanize(page)

                            if await _is_captcha_or_sorry(page):
                                captcha_hits_term += 1
                                captcha_hits_global += 1
                                cooldown = _cooldown_secs(captcha_hits_global)
                                log.warning(
                                    f"⚠️ CAPTCHA detected (term='{term}', city='{city}', hit={captcha_hits_term}, "
                                    f"global_hits={captcha_hits_global}). Cooling down for {cooldown}s..."
                                )
                                await page.wait_for_timeout(cooldown * 1000)
                                if captcha_hits_term >= 3:
                                    log.info(
                                        f"⏭️ Skipping to next page for term '{term}' due to repeated CAPTCHA hits"
                                    )
                                    idx += 1
                                    continue

                            # Espera segura por conteúdo (não explode se a página fechar)
                            await _safe_wait_for_selector(
                                page,
                                "a[href^='tel:']," + ",".join(RESULT_CONTAINERS),
                                state="attached",
                            )

                            # Extração inicial (pode vir sem nomes na SERP)
                            leads = await _extract_phones_from_page(page)

                            # Enriquecimento de nomes quando necessário
                            if leads:
                                unique_names = set(
                                    (l.get("name") or "") for l in leads if l.get("name")
                                )
                                if len(unique_names) <= 1:
                                    missing = leads[:]
                                else:
                                    missing = [l for l in leads if not (l or {}).get("name")]

                                if missing and _page_alive(page):
                                    try:
                                        cards = page.locator(",".join(LISTING_LINK_SELECTORS))
                                        count = await cards.count()
                                        MAX_ENRICH_CARDS = 25
                                        to_open = min(count, MAX_ENRICH_CARDS)

                                        # Conjunto dos telefones que realmente precisam de nome
                                        missing_phones = {
                                            (m.get("phone") or "") for m in missing if m.get("phone")
                                        }
                                        found_for_missing: Set[str] = set()
                                        enriched: List[Dict[str, Optional[str]]] = []

                                        log.debug(f"📋 Enriching {len(missing_phones)} phone(s) from {to_open} cards")

                                        for i in range(to_open):
                                            try:
                                                href = await cards.nth(i).get_attribute("href")
                                            except (PWError, Exception):
                                                href = None
                                            try:
                                                # Não usa 'seen' no enriquecimento — precisamos re-extrair
                                                # para mapear phone→name corretamente.
                                                res = await _open_and_extract_from_listing(context, href, None)
                                            except Exception as e:
                                                log.debug(f"Failed to extract from listing: {e}")
                                                res = []
                                            if res:
                                                enriched.extend(res)
                                                # Atualiza o conjunto de missing cobertos
                                                for e in res:
                                                    eph = e.get("phone")
                                                    if eph and eph in missing_phones:
                                                        found_for_missing.add(eph)
                                                # Agora só paramos quando TODOS os 'missing' foram cobertos
                                                if missing_phones and missing_phones.issubset(found_for_missing):
                                                    log.debug(f"✅ All missing phones enriched")
                                                    break

                                        # phone->name apenas para os que interessam
                                        name_map = {
                                            e["phone"]: e.get("name")
                                            for e in enriched
                                            if e.get("phone") in missing_phones and e.get("name")
                                        }
                                        for l in leads:
                                            if not l.get("name") or (len(unique_names) <= 1):
                                                nm = name_map.get(l["phone"])
                                                if nm:
                                                    l["name"] = nm
                                    except (PWError, Exception) as e:
                                        log.warning(f"Name enrichment failed: {e}")
                                        pass

                            # Fallback: abrir cards se nada foi achado na SERP
                            if not leads and _page_alive(page):
                                log.debug("No phones on SERP, opening cards as fallback...")
                                try:
                                    cards = page.locator(",".join(LISTING_LINK_SELECTORS))
                                    count = await cards.count()
                                    to_open = min(count, 15)
                                    for i in range(to_open):
                                        try:
                                            href = await cards.nth(i).get_attribute("href")
                                        except (PWError, Exception):
                                            href = None
                                        try:
                                            res = await _open_and_extract_from_listing(context, href, seen)
                                        except Exception:
                                            res = []
                                        if res:
                                            leads.extend(res)
                                            if len(leads) >= 25:
                                                break
                                except (PWError, Exception) as e:
                                    log.debug(f"Fallback card extraction failed: {e}")
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
                                    log.debug(f"✅ New lead: {nm or '(sem nome)'} — {ph}")
                                    yield {"phone": ph, "name": nm}
                                    if target and total_yield >= target:
                                        log.info(
                                            f"🎯 Target of {target} leads reached. Terminating search."
                                        )
                                        try:
                                            await page.close()
                                        except Exception:
                                            pass
                                        return

                            empty_pages = empty_pages + 1 if new == 0 else 0

                            if empty_pages >= empty_limit:
                                if use_local and generated_this_term < 3:
                                    log.info(
                                        f"🔄 Few or no leads found for term '{term}' in local search. Falling back to general search."
                                    )
                                    use_local = False
                                    empty_pages = 0
                                    idx = 0
                                    captcha_hits_term = 0
                                    continue
                                log.info(
                                    f"⏭️ Reached empty page limit ({empty_limit}) for term '{term}'. Moving to next term."
                                )
                                try:
                                    await page.close()
                                except Exception:
                                    pass
                                break

                            wait_ms = random.randint(320, 620) + min(
                                1800, int(idx * 48 + random.randint(140, 300))
                            )
                            if _page_alive(page):
                                await page.wait_for_timeout(wait_ms)
                            idx += 1

                        except (PWError, CancelledError, Exception) as e:
                            log.error(f"❌ Error processing page {idx} for term '{term}': {e}")
                            try:
                                await page.close()
                            except Exception:
                                pass
                            idx += 1
                            continue
                        finally:
                            try:
                                if _page_alive(page):
                                    await page.close()
                            except Exception:
                                pass
    finally:
        try:
            await context.close()
        except (PWError, CancelledError, Exception):
            pass
        log.info(f"Search completed. Total leads yielded: {total_yield}")


async def shutdown_playwright():
    """
    Gracefully close the Playwright browser and stop Playwright.
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
