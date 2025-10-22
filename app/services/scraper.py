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
# appears to have no effect outside of local results.
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

# Labels of consent buttons that Google may present.
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
    ".DUwDvf",
    "h1[role='heading'] span",
    "h1[role='heading']",
    "meta[itemprop='name']::attr(content)",  # atributo content (lidado em _primary_business_name)
    ".qrShPb span",
    ".SPZz6b span",
]

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 13; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
]


def _norm_ascii(s: str) -> str:
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", s or "")
        if not unicodedata.combining(ch)
    )


def _clean_query(s: str) -> str:
    s = (s or "").strip()
    return " ".join(s.split())


def _quoted_variants(q: str) -> List[str]:
    out = [q]
    if " " in q:
        out.append(f'"{q}"')
    if q.endswith("s"):
        out.append(q[:-1])
    return list(dict.fromkeys(out))


def _niche_variants(q: str) -> List[str]:
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
    c = _city_alias(city)
    if not c:
        return ""
    if "," not in c:
        c = f"{c},Brazil"
    b64 = base64.b64encode(c.encode("utf-8")).decode("ascii")
    return "&uule=" + urllib.parse.quote("w+CAIQICI" + b64, safe="")


async def _try_accept_consent(page) -> None:
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
    try:
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
    try:
        # Só considere 'primary' quando estivermos, de fato, dentro da ficha.
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

        # Passo 1: <a href="tel:">
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
    c = _city_alias(city)
    base = [c, f"{c} MG", f"{c}, MG"]
    no_acc = list({_norm_ascii(x) for x in base})
    variants = base + [f"em {x}" for x in base] + no_acc + [f"em {x}" for x in no_acc]
    return list(dict.fromkeys(variants))


async def _is_captcha_or_sorry(page) -> bool:
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
    base = 18
    mx = 110
    return min(mx, int(base * (1.6 ** max(0, hit - 1))) + random.randint(0, 9))


# ---------- Playwright: browser único, contexto por request ----------
_pw = None
_browser = None
_pw_lock = asyncio.Lock()


async def _ensure_browser():
    global _pw, _browser
    if async_playwright is None:
        raise ImportError("Playwright is not installed. Install 'playwright' to use the scraper.")

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
            log.info(f"Launching {settings.BROWSER} browser (headless={settings.HEADLESS})…")
            _browser = await getattr(_pw, settings.BROWSER).launch(**launch_args)
    return _browser


async def _new_context():
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


async def _safe_goto(page, url: str, **kw):
    try:
        return await asyncio.shield(page.goto(url, **kw))
    except CancelledError:
        try:
            await page.close()
        except Exception:
            pass
        raise


async def _open_and_extract_from_listing(context, href: str, seen: Set[str]) -> List[Dict[str, Optional[str]]]:
    out: List[Dict[str, Optional[str]]] = []
    if not href:
        return out
    if href.startswith("/"):
        href = "https://www.google.com" + href

    page2 = await context.new_page()
    try:
        await _safe_goto(page2, href, wait_until="domcontentloaded", timeout=30000)
        primary_name = await _primary_business_name(page2)

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

        await page2.wait_for_timeout(800)
        leads = await _extract_phones_from_page(page2, default_name=primary_name)
        for lead in leads:
            ph = lead.get("phone")
            if ph and ph not in seen:
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


async def _enrich_names_from_cards(page, context, seen: Set[str], needed: int) -> Dict[str, Optional[str]]:
    """
    Abre sequencialmente os primeiros cartões e retorna um mapa phone->name.
    Abertura sequencial evita TargetClosedError por tarefas pendentes.
    """
    name_map: Dict[str, Optional[str]] = {}
    try:
        cards = page.locator(",".join(LISTING_LINK_SELECTORS))
        count = await cards.count()
        to_open = min(count, max(12, needed))
        for i in range(to_open):
            href = None
            try:
                href = await cards.nth(i).get_attribute("href")
            except Exception:
                href = None
            try:
                enriched = await _open_and_extract_from_listing(context, href, seen)
            except Exception:
                enriched = []
            for e in enriched:
                ph = e.get("phone")
                nm = e.get("name")
                if ph and nm and ph not in name_map:
                    name_map[ph] = nm
            # pequena pausa para reduzir detecção
            await asyncio.sleep(random.uniform(0.08, 0.18))
    except Exception:
        pass
    return name_map


# ---------- busca principal ----------
async def search_numbers(
    nicho: str,
    locais: List[str],
    target: int,
    *,
    max_pages: Optional[int] = None,
) -> AsyncGenerator[Dict[str, Optional[str]], None]:
    seen: Set[str] = set()
    q_base = _clean_query(nicho)
    empty_limit = int(getattr(settings, "MAX_EMPTY_PAGES", 14))
    captcha_hits_global = 0

    context = await _new_context()
    log.info(
        f"Starting phone search: nicho='{nicho}', locais={locais}, target={target}, max_pages={max_pages}"
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

                log.info(f"Searching term '{term}' in city '{city}'")

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
                    page.set_default_timeout(20000)

                    try:
                        try:
                            await _safe_goto(
                                page, url, wait_until="domcontentloaded", timeout=30000
                            )
                        except (PWError, CancelledError):
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

                        if await _is_captcha_or_sorry(page):
                            captcha_hits_term += 1
                            captcha_hits_global += 1
                            log.warning(
                                f"CAPTCHA or unusual traffic detected (term='{term}', city='{city}', hit={captcha_hits_term}, global_hits={captcha_hits_global})."
                            )
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

                        # Enriquecimento de nomes se estiverem iguais/ausentes
                        if leads:
                            unique_names = set((l.get("name") or "") for l in leads if l.get("name"))
                            needs_enrichment = (len(unique_names) <= 1) or any(not (l or {}).get("name") for l in leads)
                            if needs_enrichment:
                                missing_count = sum(1 for l in leads if not (l or {}).get("name"))
                                missing_count = max(missing_count, len(leads))
                                name_map = await _enrich_names_from_cards(
                                    page, context, seen, missing_count
                                )
                                for l in leads:
                                    if not l.get("name") or len(unique_names) <= 1:
                                        nm = name_map.get(l["phone"])
                                        if nm:
                                            l["name"] = nm

                        # Sem leads? Tenta abrir cartões diretamente (sequencial)
                        if not leads:
                            name_map = await _enrich_names_from_cards(page, context, seen, needed=15)
                            leads = [{"phone": ph, "name": nm} for ph, nm in name_map.items()]

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
                                    log.info(f"Target of {target} leads reached. Terminating search.")
                                    try:
                                        await page.close()
                                    except Exception:
                                        pass
                                    return

                        empty_pages = empty_pages + 1 if new == 0 else 0

                        if empty_pages >= empty_limit:
                            if use_local and generated_this_term < 3:
                                log.info(
                                    f"Few or no leads found for term '{term}' in local search. Falling back to general search."
                                )
                                use_local = False
                                empty_pages = 0
                                idx = 0
                                captcha_hits_term = 0
                                continue
                            log.info(
                                f"Reached empty page limit ({empty_limit}) for term '{term}'. Moving to next term."
                            )
                            try:
                                await page.close()
                            except Exception:
                                pass
                            break

                        wait_ms = random.randint(320, 620) + min(
                            1800, int(idx * 48 + random.randint(140, 300))
                        )
                        await page.wait_for_timeout(wait_ms)
                        idx += 1

                    except (PWError, CancelledError, Exception):
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
        try:
            await context.close()
        except (PWError, CancelledError, Exception):
            pass
        log.info(f"Search completed. Total leads yielded: {total_yield}")


async def shutdown_playwright():
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
