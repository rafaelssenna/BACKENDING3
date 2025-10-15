# app/main.py
import json
from io import StringIO
from typing import List, Dict, Tuple, Any
from asyncio import CancelledError
import asyncio

from fastapi import FastAPI, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response

from .config import settings

# Import seguro: se shutdown_playwright não existir, define um no-op.
try:
    from .services.scraper import search_numbers, shutdown_playwright as _shutdown_playwright
except Exception:
    from .services.scraper import search_numbers
    async def _shutdown_playwright():
        return

from .services.verifier import verify_batch
from .auth import router as auth_router, verify_access_via_query

app = FastAPI(title="ClickLeads Backend", version="2.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(auth_router)

KEEPALIVE_SEC = 10  # “tick” periódico no SSE para evitar ficar mudo

def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

def _batch_size(n: int) -> int:
    if n <= 5: return 6
    if n <= 20: return 10
    if n <= 100: return 20
    return 30

def _cidade(local: str) -> str:
    return (local or "").split(",")[0].strip()

def _scrape_cap(remaining: int, somente_wa: bool) -> int:
    # quando filtra por WA, precisamos sobre-amostrar
    return max(remaining * (16 if somente_wa else 1), 300 if somente_wa else 100)

def _lead_tuple(item: Any) -> Tuple[str, str | None]:
    """
    Aceita string (+55...) ou dict {"phone","name"} e retorna (phone, name).
    Mantém compatibilidade se algum scraper antigo retornar apenas string.
    """
    if isinstance(item, dict):
        ph = str(item.get("phone") or "").strip()
        nm = (item.get("name") or "").strip() or None
        return ph, nm
    return str(item or "").strip(), None

@app.get("/health")
async def health():
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
    _uid, _sid, _dev = auth

    somente_wa = verify == 1
    cidade = _cidade(local)
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
        def maybe_tick():
            nonlocal last_beat
            now = asyncio.get_event_loop().time()
            if now - last_beat >= KEEPALIVE_SEC:
                last_beat = now
                return sse("tick", {"ts": int(now)})
            return None

        async def flush_pool(pool: List[str]):
            nonlocal delivered, non_wa
            if not pool:
                return
            try:
                ok, bad = await verify_batch(pool, batch_size=len(pool))
            except Exception:
                ok, bad = [], []  # não marca como não-WA em caso de erro
            non_wa += len(bad)
            for p in ok:
                if delivered < target:
                    delivered += 1
                    yield sse("item", {"phone": p, "name": name_by_phone.get(p), "has_whatsapp": True})
                    if delivered >= target:
                        break
            yield sse("progress", {
                "wa_count": delivered, "non_wa_count": non_wa,
                "searched": searched, "city": cidade
            })

        try:
            yield sse("start", {"message": "started"})
            tick = maybe_tick()
            if tick: yield tick
            yield sse("city", {"status": "start", "name": cidade})

            pool: List[str] = []

            # 1ª passada: coleta de candidatos (sobre-amostra se somente_wa)
            scrape_cap = _scrape_cap(target - delivered, somente_wa)
            async for item in search_numbers(nicho, [cidade], scrape_cap, max_pages=None):
                tick = maybe_tick()
                if tick: yield tick

                if delivered >= target:
                    break

                ph, nm = _lead_tuple(item)
                if not ph or ph in vistos:
                    continue
                vistos.add(ph)
                searched += 1
                name_by_phone.setdefault(ph, nm)

                if not somente_wa:
                    delivered += 1
                    yield sse("item", {"phone": ph, "name": nm, "has_whatsapp": False})
                    yield sse("progress", {
                        "wa_count": delivered, "non_wa_count": non_wa,
                        "searched": searched, "city": cidade
                    })
                    continue

                pool.append(ph)
                if len(pool) >= min_batch and delivered < target:
                    async for chunk in flush_pool(pool[:min_batch]): yield chunk
                    pool = pool[min_batch:]
                if len(pool) >= full_batch and delivered < target:
                    async for chunk in flush_pool(pool[:full_batch]): yield chunk
                    pool = pool[full_batch:]

            # 2ª passada: ainda faltou WA? busca mais candidatos
            if somente_wa and delivered < target:
                extra_needed = target - delivered
                extra_cap = _scrape_cap(extra_needed, True)
                async for item in search_numbers(nicho, [cidade], extra_cap, max_pages=None):
                    tick = maybe_tick()
                    if tick: yield tick

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
                        async for chunk in flush_pool(pool[:min_batch]): yield chunk
                        pool = pool[min_batch:]

            # flush final
            if somente_wa and pool and delivered < target:
                async for chunk in flush_pool(pool): yield chunk
                pool.clear()

            yield sse("city", {"status": "done", "name": cidade})
            exhausted = delivered < target
            yield sse("done", {
                "wa_count": delivered,
                "non_wa_count": non_wa,
                "searched": searched,
                "exhausted": exhausted
            })
            sent_done = True

        except CancelledError:
            return
        except Exception as e:
            yield sse("progress", {
                "error": str(e),
                "wa_count": delivered,
                "non_wa_count": non_wa,
                "searched": searched
            })
            yield sse("done", {
                "wa_count": delivered,
                "non_wa_count": non_wa,
                "searched": searched,
                "exhausted": delivered < target
            })
            sent_done = True
        finally:
            if not sent_done:
                yield sse("done", {
                    "wa_count": delivered,
                    "non_wa_count": non_wa,
                    "searched": searched,
                    "exhausted": delivered < target
                })

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
    somente_wa = verify == 1
    cidade = _cidade(local)
    target = n

    items: List[Dict[str, Any]] = []  # cada item: {"phone":..., "name":...}
    delivered = 0
    non_wa = 0
    searched = 0
    vistos: set[str] = set()
    name_by_phone: Dict[str, str | None] = {}

    base_batch = _batch_size(target)
    min_batch = min(8, base_batch)

    try:
        pool: List[str] = []

        # 1ª passada
        scrape_cap = _scrape_cap(target - delivered, somente_wa)
        async for item in search_numbers(nicho, [cidade], scrape_cap, max_pages=None):
            if delivered >= target: break
            ph, nm = _lead_tuple(item)
            if not ph or ph in vistos: continue
            vistos.add(ph); searched += 1
            name_by_phone.setdefault(ph, nm)

            if not somente_wa:
                items.append({"phone": ph, "name": nm}); delivered += 1
                continue

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
                        items.append({"phone": p, "name": name_by_phone.get(p)}); delivered += 1
                        if delivered >= target: break

        # 2ª passada se necessário (e ainda há pool pendente)
        if somente_wa and delivered < target and pool:
            try:
                ok, bad = await verify_batch(pool, batch_size=len(pool))
            except Exception:
                ok, bad = [], []
            non_wa += len(bad)
            for p in ok:
                if delivered < target:
                    items.append({"phone": p, "name": name_by_phone.get(p)}); delivered += 1
                    if delivered >= target: break

    except Exception:
        pass

    # payload padronizado
    data = [{"phone": r["phone"], "name": r.get("name"), "has_whatsapp": bool(verify)} for r in items[:target]]
    return JSONResponse({
        "items": data,
        "leads": data,
        "wa_count": delivered,
        "non_wa_count": non_wa,
        "searched": searched
    })

def _csv_response(csv_bytes: bytes, filename: str) -> Response:
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
    resp = await leads(nicho=nicho, local=local, n=n, verify=verify)
    payload = json.loads(resp.body.decode("utf-8"))
    rows = payload.get("items", [])
    buf = StringIO(); buf.write("name,phone\n")
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
    await _shutdown_playwright()
