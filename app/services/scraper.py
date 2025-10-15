# app/services/scraper.py
import asyncio
from asyncio import CancelledError
import random
import urllib.parse
import base64
import unicodedata
from typing import AsyncGenerator, List, Set, Optional, Dict

from playwright.async_api import (
    async_playwright,
    TimeoutError as PWTimeoutError,
    Error as PWError,
)
from ..config import settings
from ..utils.phone import extract_phones_from_text, normalize_br
from ..utils.logs import setup_logger

# Initialise a module‑level logger. Using a single logger ensures
# consistent formatting and avoids reattaching handlers on each import.
log = setup_logger("scraper")

SEARCH_FMT = "https://www.google.com/search?tbm=lcl&hl=pt-BR&gl=BR&q={query}&start={start}{uule}"

RESULT_CONTAINERS = [
    ".rlfl__tls", ".VkpGBb", ".rllt__details", ".rllt__wrapped",
    "div[role='article']", "#search", "div[role='main']", "#rhs", ".kp-wholepage",
]

LISTING_LINK_SELECTORS = [
    "a[href*='/local/place']",
    "a[href*='://www.google.com/local/place']",
    "a[href*='://www.google.com/maps/place']",
    "a[href^='https://www.google.com/maps/place']",
    "a[href*='ludocid=']",
    "a[href*='/search?'][href*='ludocid']",
    "a[href*='/search?'][href*='lrd=']",
]

CONSENT_BUTTONS = [
    "button#L2AGLb",
    "button:has-text('Aceitar tudo')",
    "button:has-text('Concordo')",
    "button:has-text('Aceitar')",
    "button:has-text('I agree')",
    "button:has-text('Accept all')",
]

# Nome do estabelecimento: seletores comuns em SERP/Maps
NAME_CANDIDATES = [
    ".DUwDvf",              # título no Google Maps
    "h1", "h2", "h3",
    ".dbg0pd",
    ".rllt__details > div:first-child",
    "[role='heading'] span",
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
    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(ch))

def _clean_query(s: str) -> str:
    s = (s or "").strip()
    return " ".join(s.split())

def _quoted_variants(q: str) -> List[str]:
    out = [q]
    if " " in q: out.append(f'"{q}"')
    if q.endswith("s"): out.append(q[:-1])
    return list(dict.fromkeys(out))

def _niche_variants(q: str) -> List[str]:
    q = _clean_query(q)
    base = [q]
    synonyms = {
        "restaurantes veganos": ["restaurante vegano", "comida vegana", "vegano"],
        "distribuidores de alimentos": ["distribuidora de alimentos", "atacadista de alimentos", "atacado de alimentos"],
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
    if not c: return ""
    if "," not in c: c = f"{c},Brazil"
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
        await page.mouse.move(random.randint(40, 420), random.randint(60, 320), steps=random.randint(6, 14))
        await page.evaluate("() => { window.scrollBy(0, Math.floor(180 + Math.random()*280)); }")
        await page.wait_for_timeout(random.randint(260, 520))
    except Exception:
        pass

async def _closest_name_for(page, element) -> Optional[str]:
    try:
        # Busca um contêiner pertinente e tenta extrair um "título" dentro dele.
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
                  node = node.parentElement;
                }}
                return null;
            }}""",
            element,
        )
    except Exception:
        return None

async def _extract_phones_from_page(page) -> List[Dict[str, Optional[str]]]:
    """
    Extrai pares {name, phone} da página atual.
    - Prioriza <a href="tel:"> e tenta achar o nome "próximo".
    - Faz varredura dos contêineres conhecidos e tenta casar um heading do card.
    - Como último recurso, varre o body inteiro e extrai apenas o telefone.
    """
    leads: Dict[str, Dict[str, Optional[str]]] = {}
    try:
        # 1) Telefones clicáveis (anchors tel:) + nome mais próximo
        anchors = await page.query_selector_all("a[href^='tel:']")
        for a in anchors or []:
            try:
                href = (await a.get_attribute("href")) or ""
                text = (await a.inner_text()) or (await a.text_content()) or ""
                phone = normalize_br(href.replace("tel:", "")) or normalize_br(text)
                if not phone:
                    continue
                name = await _closest_name_for(page, a)
                if phone not in leads:
                    leads[phone] = {"phone": phone, "name": (name or None)}
            except Exception:
                continue

        # 2) Blocos de resultados: tenta achar phones + heading dentro do bloco
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
                    # nome do bloco (se houver)
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
                                return null;
                            }}""",
                            block,
                        )
                    except Exception:
                        name_in_block = None
                    for ph in extracted:
                        if ph not in leads:
                            leads[ph] = {"phone": ph, "name": (name_in_block or leads.get(ph, {}).get("name"))}
            except Exception:
                continue

        # 3) Fallback absoluto: varre o body inteiro
        if not leads:
            try:
                body_text = await page.evaluate("() => document.body ? (document.body.innerText || '') : ''")
            except Exception:
                body_text = ""
            for ph in extract_phones_from_text(body_text or ""):
                if ph not in leads:
                    leads[ph] = {"phone": ph, "name": None}

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
        if "/sorry/" in txt or "unusual traffic" in txt or "recaptcha" in txt or "g-recaptcha" in txt:
            return True
        sel_hit = await page.locator("form[action*='/sorry'], iframe[src*='recaptcha'], #recaptcha").count()
        return sel_hit > 0
    except Exception:
        return False

def _cooldown_secs(hit: int) -> int:
    base = 18; mx = 110
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
    """Ensure that a single Playwright browser instance is running."""
    global _pw, _browser
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

# ---------- navegação blindada ----------
async def _safe_goto(page, url: str, **kw):
    try:
        return await asyncio.shield(page.goto(url, **kw))
    except CancelledError:
        try:
            await page.close()
        except Exception:
            pass
        raise

# ---------- abrir ficha ----------
async def _open_and_extract_from_listing(context, href: str, seen: Set[str]) -> List[Dict[str, Optional[str]]]:
    out: List[Dict[str, Optional[str]]] = []
    if not href: return out
    if href.startswith("/"): href = "https://www.google.com" + href

    page2 = await context.new_page()
    try:
        await _safe_goto(page2, href, wait_until="domcontentloaded", timeout=30000)
        for sel in ["button:has-text('Telefone')", "button:has-text('Ligar')", "a[aria-label^='Ligar']", "[aria-label*='Telefone']"]:
            try:
                loc = page2.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible():
                    await loc.first.click()
                    await page2.wait_for_timeout(350)
            except Exception:
                pass
        await page2.wait_for_timeout(1000)
        leads = await _extract_phones_from_page(page2)
        for lead in leads:
            ph = lead.get("phone")
            if ph and ph not in seen:
                seen.add(ph)
                out.append(lead)
    except (PWError, CancelledError, Exception):
        pass
    finally:
        try: await page2.close()
        except (PWError, CancelledError, Exception): pass
    return out

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
    log.info(f"Starting phone search: nicho='{nicho}', locais={locais}, target={target}, max_pages={max_pages}")

    try:
        total_yield = 0
        for local in locais:
            city = (local or "").strip()
            if not city: continue
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
                log.info(f"Searching term '{term}' in city '{city}'")

                while True:
                    if target and total_yield >= target: return
                    if max_pages is not None and idx >= max_pages: break

                    start = idx * 20
                    q = term
                    if captcha_hits_term > 0:
                        decorations = ["", " ", "  ", " ★", " ✔", " ✓"]
                        q = (term + random.choice(decorations)).strip()

                    url = SEARCH_FMT.format(query=urllib.parse.quote_plus(q), start=start, uule=uule)

                    page = await context.new_page()
                    page.set_default_timeout(20000)

                    try:
                        try:
                            await _safe_goto(page, url, wait_until="domcontentloaded", timeout=30000)
                        except (PWError, CancelledError):
                            try: await page.close()
                            except Exception: pass
                            page = await context.new_page()
                            page.set_default_timeout(20000)
                            await _safe_goto(page, url, wait_until="domcontentloaded", timeout=30000)

                        await _try_accept_consent(page)
                        await _humanize(page)

                        if await _is_captcha_or_sorry(page):
                            captcha_hits_term += 1
                            captcha_hits_global += 1
                            log.warning(f"CAPTCHA or unusual traffic detected (term='{term}', city='{city}', hit={captcha_hits_term}, global_hits={captcha_hits_global}).")
                            await page.wait_for_timeout(_cooldown_secs(captcha_hits_global) * 1000)
                            if captcha_hits_term >= 2:
                                log.info(f"Skipping to next page for term '{term}' due to repeated CAPTCHA hits")
                                idx += 1
                                continue

                        try:
                            await page.wait_for_selector("a[href^='tel:']," + ",".join(RESULT_CONTAINERS), timeout=8000)
                        except PWTimeoutError:
                            pass

                        leads = await _extract_phones_from_page(page)

                        if not leads:
                            try:
                                cards = page.locator(",".join(LISTING_LINK_SELECTORS))
                                count = await cards.count()
                                to_open = min(count, 12)
                                max_conc = max(1, int(getattr(settings, "LISTING_CONCURRENCY", 3)))
                                tasks: List[asyncio.Task] = []
                                for i in range(to_open):
                                    try:
                                        href = await cards.nth(i).get_attribute("href")
                                    except (PWError, Exception):
                                        href = None
                                    tasks.append(asyncio.create_task(_open_and_extract_from_listing(context, href, seen)))
                                    if len(tasks) >= max_conc:
                                        results = await asyncio.gather(*tasks, return_exceptions=True)
                                        tasks.clear()
                                        for res in results:
                                            if isinstance(res, Exception):
                                                continue
                                            leads.extend(res)
                                            if len(leads) >= 20: break
                                    if len(leads) >= 20:
                                        break
                                if tasks and len(leads) < 20:
                                    results = await asyncio.gather(*tasks, return_exceptions=True)
                                    tasks.clear()
                                    for res in results:
                                        if isinstance(res, Exception):
                                            continue
                                        leads.extend(res)
                                        if len(leads) >= 20: break
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
                                log.debug(f"New lead: {nm or '(sem nome)'} — {ph}")
                                yield {"phone": ph, "name": nm}
                                if target and total_yield >= target:
                                    log.info(f"Target of {target} leads reached. Terminating search.")
                                    try: await page.close()
                                    except Exception: pass
                                    return

                        empty_pages = empty_pages + 1 if new == 0 else 0
                        if empty_pages >= empty_limit:
                            log.info(f"Reached empty page limit ({empty_limit}) for term '{term}'. Moving to next term.")
                            try: await page.close()
                            except Exception: pass
                            break

                        wait_ms = random.randint(320, 620) + min(1800, int(idx * 48 + random.randint(140, 300)))
                        await page.wait_for_timeout(wait_ms)
                        idx += 1

                    except (PWError, CancelledError, Exception):
                        try: await page.close()
                        except Exception: pass
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
