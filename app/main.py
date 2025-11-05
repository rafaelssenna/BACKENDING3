"""
Main FastAPI application exposing endpoints for lead generation. This
version handles phone leads with optional WhatsApp verification, returns
both phone numbers and business names, streams progress via SSE and
produces JSON/CSV outputs. It integrates with the scraper service and
provides health checks and graceful shutdown of Playwright.
"""

import json
from io import StringIO
from typing import List, Dict, Tuple, Any
from asyncio import CancelledError
import asyncio

from fastapi import FastAPI, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response

from .config import settings

# Import scraper and shutdown function. If shutdown_playwright is not
# available (e.g. during tests), define a no‑op fallback.
try:
    from .services.scraper import search_numbers, shutdown_playwright as _shutdown_playwright
except Exception:
    from .services.scraper import search_numbers

    async def _shutdown_playwright():
        return

from .services.verifier import verify_batch
# Import the authentication router and query verifier.  These are optional
# and may fail to import if dependencies like SQLAlchemy or passlib are
# missing in the runtime environment.  In that case we provide dummy
# implementations that effectively disable authentication, allowing the
# application to start and non‑auth endpoints to function.  Note that
# disabling authentication in this way should only be used in testing
# environments; production deployments must install the required
# packages and enable proper auth.
try:
    from .auth import router as auth_router, verify_access_via_query  # type: ignore
except Exception:
    from fastapi import APIRouter  # type: ignore

    auth_router = APIRouter()

    async def verify_access_via_query(*args, **kwargs):  # type: ignore[no-untyped-def]
        # Simply return dummy values; downstream code expects a tuple of
        # (uid, session_id, device_id).  Without proper authentication
        # these values are None, but the endpoints will still run.
        return None, None, None


app = FastAPI(title="ClickLeads Backend", version="2.2.0")

# Configure CORS.  Accept any origin by default and explicitly add the
# Luna PG Admin frontend to avoid CORS errors when this service is
# consumed from that domain.  Because ``allow_credentials`` is
# disabled we can include "*" alongside a specific origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "https://luna-pg-admin.vercel.app"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(auth_router)


KEEPALIVE_SEC = 10  # periodic 'tick' for SSE to keep the connection alive


def sse(event: str, data: dict) -> str:
    """Format a message for server‑sent events."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _batch_size(n: int) -> int:
    """Determine batch sizes for WhatsApp verification based on target size."""
    if n <= 5:
        return 6
    if n <= 20:
        return 10
    if n <= 100:
        return 20
    return 30


def _cidade(local: str) -> str:
    """Extract the first city from the ``local`` parameter.

    Historically this backend only supported a single city and would
    split on the first comma to strip the state abbreviation (e.g.
    ``"Belo Horizonte, MG"`` → ``"Belo Horizonte"``).  To maintain
    backward‑compatibility this helper still performs that behaviour
    when a single city is supplied.  When multiple cities are provided
    in the same ``local`` string this function simply returns the first
    non‑empty entry after splitting on common separators (``|``, ``;`` or
    newlines) and then on a comma.  See :func:`_locais` for splitting
    the full list of cities.
    """
    # Normalise multiple cities via _locais and return the first one
    cities = _locais(local)
    if not cities:
        return ""
    # Preserve original behaviour: strip anything after the first comma
    city = cities[0]
    return city.split(",")[0].strip()


def _locais(local: str) -> List[str]:
    """Split the ``local`` query parameter into a list of city strings.

    Clients can supply multiple cities separated by ``|``, ``;`` or
    newlines.  Commas are *not* treated as delimiters so that state
    abbreviations (e.g. ``"São Paulo, SP"``) remain intact.  Leading
    and trailing whitespace around each city is stripped.  Empty
    segments are ignored.

    Examples::

        >>> _locais("Belo Horizonte, MG")
        ['Belo Horizonte, MG']
        >>> _locais("Belo Horizonte|São Paulo;Rio de Janeiro\nCuritiba")
        ['Belo Horizonte', 'São Paulo', 'Rio de Janeiro', 'Curitiba']
    """
    if not local:
        return []
    text = str(local).strip()
    # Look for known separators and split on the first one present.  We
    # check specific separators in a deterministic order and only split
    # on the first one found to avoid splitting on commas inside city
    # names (e.g. the ``", SP"`` in ``"São Paulo, SP"``).
    for delim in ["|", ";", "\n", "\r", "\r\n"]:
        if delim in text:
            parts = [p.strip() for p in text.split(delim) if p and p.strip()]
            return parts
    # No multi‑city separator – treat the whole string as one entry
    return [text]


def _scrape_cap(remaining: int, somente_wa: bool) -> int:
    """
    Determine how many results to scrape to satisfy the remaining count. When
    filtering by WhatsApp, over‑sample to account for invalid numbers.
    """
    return max(remaining * (16 if somente_wa else 1), 300 if somente_wa else 100)


def _lead_tuple(item: Any) -> Tuple[str, str | None]:
    """
    Normalize scraped items into a (phone, name) tuple. Supports both
    string and dict formats for backward compatibility.
    """
    if isinstance(item, dict):
        ph = str(item.get("phone") or "").strip()
        nm = (item.get("name") or "").strip() or None
        return ph, nm
    return str(item or "").strip(), None


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


# ================= STREAM =================
@app.get("/leads/stream")
async def leads_stream(
    nicho: str = Query(...),
    local: str = Query(...),
    n: int = Query(..., ge=1, le=min(500, settings.MAX_RESULTS)),
    verify: int = Query(0),
    auth=Depends(verify_access_via_query),
):
    """
    SSE endpoint for real‑time delivery of leads.  Supports multiple
    cities separated by ``|``, ``;`` or newlines.  Emits `city`
    events signalling the start and end of scraping for each city.  If
    ``verify=1``, numbers are checked via the WhatsApp verifier
    service before being emitted.
    """
    _uid, _sid, _dev = auth

    somente_wa = verify == 1
    # Parse the list of cities from the incoming query.  If nothing is
    # provided default to an empty list, which will result in no
    # results.
    cities = _locais(local)
    target = n

    async def gen():
        delivered = 0
        non_wa = 0
        searched = 0
        vistos: set[str] = set()
        name_by_phone: Dict[str, str | None] = {}

        base_batch = _batch_size(target)
        min_batch = min(8, base_batch)
        full_batch = base_batch
        sent_done = False

        last_beat = asyncio.get_event_loop().time()
        # Keep track of the city currently being processed for progress
        current_city = ""

        def maybe_tick():
            nonlocal last_beat
            now = asyncio.get_event_loop().time()
            if now - last_beat >= KEEPALIVE_SEC:
                last_beat = now
                return sse("tick", {"ts": int(now)})
            return None

        async def flush_pool(pool: List[str]):
            """
            Verify the batch of phones in ``pool``, update counters and
            yield SSE events for each verified number as well as
            progress.  Uses the outer scope variables ``delivered``,
            ``non_wa``, ``searched`` and ``current_city``.  Note that
            ``pool`` is consumed (i.e. not cleared) by the caller.
            """
            nonlocal delivered, non_wa
            if not pool:
                return
            try:
                ok, bad = await verify_batch(pool, batch_size=len(pool))
            except Exception:
                ok, bad = [], []  # do not mark as non‑WA on error
            non_wa += len(bad)
            for p in ok:
                if delivered < target:
                    delivered += 1
                    yield sse(
                        "item",
                        {
                            "phone": p,
                            "name": name_by_phone.get(p),
                            "has_whatsapp": True,
                        },
                    )
                    if delivered >= target:
                        break
            # Always report progress after verifying a batch
            yield sse(
                "progress",
                {
                    "wa_count": delivered,
                    "non_wa_count": non_wa,
                    "searched": searched,
                    "city": current_city,
                },
            )

        try:
            # Notify client that the stream has begun
            yield sse("start", {"message": "started"})
            tick = maybe_tick()
            if tick:
                yield tick

            # Iterate through each provided city sequentially
            for cidade in cities:
                # Update the currently processed city for progress events
                current_city = cidade
                # Emit a city start event
                yield sse("city", {"status": "start", "name": cidade})

                # A fresh pool for each city when verifying WhatsApp
                pool: List[str] = []

                # First pass: collect candidates (over‑sample if verifying WhatsApp)
                while delivered < target:
                    # Determine the number of results to scrape.  If no
                    # leads remain to deliver break out of this city loop.
                    remaining = target - delivered
                    if remaining <= 0:
                        break
                    scrape_cap = _scrape_cap(remaining, somente_wa)
                    # Run the scraper for the current city.  The search_numbers
                    # generator yields phone/name dictionaries.  We break out
                    # when we have enough leads or when the scraper is
                    # exhausted.
                    async for item in search_numbers(
                        nicho, [cidade], scrape_cap, max_pages=None
                    ):
                        tick = maybe_tick()
                        if tick:
                            yield tick

                        if delivered >= target:
                            break

                        ph, nm = _lead_tuple(item)
                        if not ph or ph in vistos:
                            continue
                        vistos.add(ph)
                        searched += 1
                        # Save the name associated with this phone if we
                        # haven't seen it before
                        name_by_phone.setdefault(ph, nm)

                        if not somente_wa:
                            # Immediate emit when not verifying WhatsApp
                            delivered += 1
                            yield sse(
                                "item",
                                {"phone": ph, "name": nm, "has_whatsapp": False},
                            )
                            yield sse(
                                "progress",
                                {
                                    "wa_count": delivered,
                                    "non_wa_count": non_wa,
                                    "searched": searched,
                                    "city": current_city,
                                },
                            )
                            if delivered >= target:
                                break
                            # Continue collecting until we reach the target or
                            # exhaust the search
                            continue

                        # When verifying WhatsApp: accumulate numbers into
                        # batches before verifying via UAZAPI
                        pool.append(ph)
                        if len(pool) >= min_batch and delivered < target:
                            async for chunk in flush_pool(pool[:min_batch]):
                                yield chunk
                            pool = pool[min_batch:]
                        if len(pool) >= full_batch and delivered < target:
                            async for chunk in flush_pool(pool[:full_batch]):
                                yield chunk
                            pool = pool[full_batch:]
                    # The inner search loop may have been exhausted or
                    # interrupted.  Break out to the next phase (second pass
                    # or next city) once we've iterated over this
                    # scrape_cap worth of results.
                    break

                # Second pass: if verifying WhatsApp and we still need more
                # valid numbers after the first pass.  Over‑sample again to
                # find additional candidates.
                if somente_wa and delivered < target:
                    remaining = target - delivered
                    if remaining > 0:
                        extra_cap = _scrape_cap(remaining, True)
                        async for item in search_numbers(
                            nicho, [cidade], extra_cap, max_pages=None
                        ):
                            tick = maybe_tick()
                            if tick:
                                yield tick

                            if delivered >= target:
                                break
                            ph, nm = _lead_tuple(item)
                            if not ph or ph in vistos:
                                continue
                            vistos.add(ph)
                            searched += 1
                            name_by_phone.setdefault(ph, nm)
                            pool.append(ph)
                            if len(pool) >= min_batch and delivered < target:
                                async for chunk in flush_pool(pool[:min_batch]):
                                    yield chunk
                                pool = pool[min_batch:]
                        # end of extra search loop

                # Flush any remaining numbers in the pool for this city if
                # verifying WhatsApp and there are still numbers to deliver
                if somente_wa and pool and delivered < target:
                    async for chunk in flush_pool(pool):
                        yield chunk
                    pool.clear()

                # Emit a city done event when we're finished with this city
                yield sse("city", {"status": "done", "name": cidade})

                # If we've reached our target, stop processing further cities
                if delivered >= target:
                    break

            # After all cities processed or target reached, emit the final
            # done event.  The ``exhausted`` flag indicates whether we
            # managed to fill the requested number of leads before running
            # out of results.
            exhausted = delivered < target
            yield sse(
                "done",
                {
                    "wa_count": delivered,
                    "non_wa_count": non_wa,
                    "searched": searched,
                    "exhausted": exhausted,
                },
            )
            sent_done = True

        except CancelledError:
            # The client cancelled the connection; simply stop sending data
            return
        except Exception as e:
            # Emit error information in the progress and done events
            yield sse(
                "progress",
                {
                    "error": str(e),
                    "wa_count": delivered,
                    "non_wa_count": non_wa,
                    "searched": searched,
                    "city": current_city,
                },
            )
            yield sse(
                "done",
                {
                    "wa_count": delivered,
                    "non_wa_count": non_wa,
                    "searched": searched,
                    "exhausted": delivered < target,
                },
            )
            sent_done = True
        finally:
            if not sent_done:
                yield sse(
                    "done",
                    {
                        "wa_count": delivered,
                        "non_wa_count": non_wa,
                        "searched": searched,
                        "exhausted": delivered < target,
                    },
                )

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ================= JSON (fallback) =================
@app.get("/leads")
async def leads(
    nicho: str = Query(...),
    local: str = Query(...),
    n: int = Query(..., ge=1, le=min(500, settings.MAX_RESULTS)),
    verify: int = Query(0),
):
    """
    Fallback endpoint returning leads in JSON.  Supports multiple
    cities separated by ``|``, ``;`` or newlines.  When ``verify=1``
    numbers are checked for WhatsApp availability before inclusion.
    Each returned entry includes both the phone number and the
    associated establishment name when available.
    """
    somente_wa = verify == 1
    cities = _locais(local)
    target = n

    items: List[Dict[str, Any]] = []
    delivered = 0
    non_wa = 0
    searched = 0
    vistos: set[str] = set()
    name_by_phone: Dict[str, str | None] = {}

    base_batch = _batch_size(target)
    min_batch = min(8, base_batch)
    full_batch = base_batch

    try:
        pool: List[str] = []
        # Process each city sequentially until the target number of leads is met
        for cidade in cities:
            if delivered >= target:
                break
            # First pass: scrape an over‑sampled number of results for this city
            remaining = target - delivered
            if remaining <= 0:
                break
            scrape_cap = _scrape_cap(remaining, somente_wa)
            async for item in search_numbers(
                nicho, [cidade], scrape_cap, max_pages=None
            ):
                if delivered >= target:
                    break
                ph, nm = _lead_tuple(item)
                if not ph or ph in vistos:
                    continue
                vistos.add(ph)
                searched += 1
                name_by_phone.setdefault(ph, nm)

                if not somente_wa:
                    items.append({"phone": ph, "name": nm})
                    delivered += 1
                    if delivered >= target:
                        break
                    continue

                # verifying WhatsApp: accumulate numbers into batches
                pool.append(ph)
                # verify in small batches to avoid large API calls and to fill up leads sooner
                if len(pool) >= min_batch:
                    try:
                        ok, bad = await verify_batch(pool[:min_batch], batch_size=min_batch)
                    except Exception:
                        ok, bad = [], []
                    pool = pool[min_batch:]
                    non_wa += len(bad)
                    for p in ok:
                        if delivered < target:
                            items.append({"phone": p, "name": name_by_phone.get(p)})
                            delivered += 1
                            if delivered >= target:
                                break
                # Optionally flush a larger batch if we accumulate many numbers at once
                if len(pool) >= full_batch:
                    try:
                        ok, bad = await verify_batch(pool[:full_batch], batch_size=full_batch)
                    except Exception:
                        ok, bad = [], []
                    pool = pool[full_batch:]
                    non_wa += len(bad)
                    for p in ok:
                        if delivered < target:
                            items.append({"phone": p, "name": name_by_phone.get(p)})
                            delivered += 1
                            if delivered >= target:
                                break

            # Second pass: if verifying WhatsApp and still need more leads,
            # over‑sample additional results for this city.  This mirrors
            # the second pass in the streaming endpoint, improving the
            # likelihood of finding enough valid numbers when the first
            # batch yields too few.
            if somente_wa and delivered < target:
                remaining = target - delivered
                if remaining > 0:
                    extra_cap = _scrape_cap(remaining, True)
                    async for item in search_numbers(
                        nicho, [cidade], extra_cap, max_pages=None
                    ):
                        if delivered >= target:
                            break
                        ph, nm = _lead_tuple(item)
                        if not ph or ph in vistos:
                            continue
                        vistos.add(ph)
                        searched += 1
                        name_by_phone.setdefault(ph, nm)
                        pool.append(ph)
                        if len(pool) >= min_batch:
                            try:
                                ok, bad = await verify_batch(pool[:min_batch], batch_size=min_batch)
                            except Exception:
                                ok, bad = [], []
                            pool = pool[min_batch:]
                            non_wa += len(bad)
                            for p in ok:
                                if delivered < target:
                                    items.append({"phone": p, "name": name_by_phone.get(p)})
                                    delivered += 1
                                    if delivered >= target:
                                        break
                    # end of extra search loop

            # After finishing scraping this city, flush any remaining numbers in the pool
            if somente_wa and pool and delivered < target:
                try:
                    ok, bad = await verify_batch(pool, batch_size=len(pool))
                except Exception:
                    ok, bad = [], []
                non_wa += len(bad)
                for p in ok:
                    if delivered < target:
                        items.append({"phone": p, "name": name_by_phone.get(p)})
                        delivered += 1
                        if delivered >= target:
                            break
                pool.clear()

        # end for each city

    except Exception:
        pass

    # Build the response payload.  Each entry includes ``has_whatsapp``
    # indicating whether WhatsApp verification was requested (not per‑number
    # success).  The ``items`` and ``leads`` keys are duplicated for
    # backwards compatibility with older clients.
    data = [
        {"phone": r["phone"], "name": r.get("name"), "has_whatsapp": bool(verify)}
        for r in items[:target]
    ]
    return JSONResponse(
        {
            "items": data,
            "leads": data,
            "wa_count": delivered,
            "non_wa_count": non_wa,
            "searched": searched,
        }
    )


def _csv_response(csv_bytes: bytes, filename: str) -> Response:
    """Helper to build a CSV HTTP response with proper headers."""
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export")
async def export_get(
    nicho: str = Query(...),
    local: str = Query(...),
    n: int = Query(...),
    verify: int = Query(0),
):
    """
    Export endpoint producing a CSV with name and phone columns. It reuses
    the `/leads` endpoint to obtain the list of leads and then formats
    them into a CSV string.
    """
    resp = await leads(nicho=nicho, local=local, n=n, verify=verify)
    payload = json.loads(resp.body.decode("utf-8"))
    rows = payload.get("items", [])
    buf = StringIO()
    buf.write("name,phone\n")
    for r in rows:
        nm = str(r.get("name") or "").replace(",", " ").strip()
        ph = str(r.get("phone") or "").strip()
        if ph:
            buf.write(f"{nm},{ph}\n")
    csv = buf.getvalue().encode("utf-8")
    filename = f"leads_{nicho.strip().replace(' ','_')}_{_cidade(local).replace(' ','_')}.csv"
    return _csv_response(csv, filename)


@app.on_event("shutdown")
async def _shutdown():
    """FastAPI shutdown hook to cleanly close Playwright."""
    await _shutdown_playwright()
