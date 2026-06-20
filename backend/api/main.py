import asyncio
import time
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from huggingface_hub import snapshot_download

from backend.api import services
from backend.api.intelligence import get_daily_briefing, get_patrol_map, get_zone_detail
from backend.dispatcher import acknowledge_latest_dispatch, read_dispatch_log, run_dispatch_cycle
from backend.api.services import SHIFT_WINDOWS, get_shift_intelligence


async def refresh_cache_loop() -> None:
    while True:
        await asyncio.sleep(300)
        services.warm_caches()


@asynccontextmanager
async def lifespan(app: FastAPI):
    snapshot_download(
        repo_id="thedestroyerks3004/sentri-artifacts",
        repo_type="dataset",
        local_dir="/app/artifacts",
    )
    services.store.load()
    services.warm_caches()
    task = asyncio.create_task(refresh_cache_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="SENTRI API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    print(f"[TIMING] {request.method} {request.url.path} took {elapsed:.4f}s")
    response.headers["X-Process-Time"] = f"{elapsed:.6f}"
    return response


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/stats/summary")
def stats_summary():
    return services.get_summary()


@app.get("/api/hotspots")
def hotspots(
    risk_tier: str | None = Query(None, description="Low Risk, Medium Risk, High Risk, Critical"),
    limit: int = Query(500, le=2000),
):
    return services.get_hotspots(risk_tier=risk_tier, limit=limit)


@app.get("/api/junctions")
def junctions(limit: int = Query(50, le=200)):
    return services.get_junctions(limit=limit)


@app.get("/api/anomalies")
def anomalies(
    min_score: float = Query(0.0, ge=0.0, le=1.0, description="Severity percentile 0-1"),
    limit: int = Query(500, le=5000),
):
    return services.get_anomalies(min_score=min_score, limit=limit)


@app.get("/api/forecast/{location}")
def forecast(location: str):
    result = services.get_forecast(location)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/scheduler")
def scheduler(
    hour: int = Query(..., ge=0, le=23),
    day: int = Query(..., ge=0, le=6, description="0=Monday … 6=Sunday"),
    limit: int = Query(10, le=20),
):
    return services.get_scheduler(hour=hour, day=day, limit=limit)


@app.get("/api/vehicle/{vehicle_number}")
def vehicle(vehicle_number: str):
    return services.get_vehicle(vehicle_number)


@app.get("/api/night-paradox")
def night_paradox():
    return services.get_night_paradox()


@app.get("/api/bulk-filing")
def bulk_filing():
    return services.get_bulk_filing()


@app.get("/api/station-performance")
def station_performance():
    return services.get_station_performance()


@app.get("/api/repeat-offenders")
def repeat_offenders():
    return services.get_repeat_offenders()


@app.get("/api/commercial-impact")
def commercial_impact():
    return services.get_commercial_impact()


@app.get("/api/offender-fingerprint")
def offender_fingerprint():
    return services.get_offender_fingerprint()


@app.get("/api/feedback-loop")
def feedback_loop(loc_key: str | None = Query(None)):
    return services.get_feedback_loop(loc_key=loc_key)


@app.get("/api/patrol-map")
async def patrol_map(
    hour: int = Query(5, ge=0, le=23),
    day: int = Query(0, ge=0, le=6),
    limit: int = Query(200, le=500),
    patrol_tonight: bool = Query(False),
    search: str | None = Query(None),
):
    return await run_in_threadpool(
        get_patrol_map,
        hour=hour,
        day=day,
        limit=limit,
        patrol_tonight=patrol_tonight,
        search=search,
    )


@app.get("/api/zone/{loc_key}")
async def zone_detail(loc_key: str):
    result = await run_in_threadpool(get_zone_detail, loc_key)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/daily-briefing")
async def daily_briefing():
    return await run_in_threadpool(get_daily_briefing)


@app.post("/api/dispatch/run")
def dispatch_run():
    return run_dispatch_cycle()


@app.post("/api/dispatch/acknowledge")
def dispatch_acknowledge():
    return acknowledge_latest_dispatch()


@app.get("/api/dispatch/log")
def dispatch_log(limit: int = Query(20, ge=1, le=100)):
    return read_dispatch_log(limit=limit)

@app.get("/api/shift-intelligence")
def shift_intelligence(shift: str = "Morning") -> dict:
    return get_shift_intelligence(shift=shift)


@app.get("/api/citizen/reports")
def citizen_reports() -> dict:
    from backend.api.services import get_citizen_reports
    return get_citizen_reports()


@app.get("/api/citizen/report/{tracking_id}")
def citizen_report(tracking_id: str) -> dict:
    from backend.api.services import get_citizen_report
    result = get_citizen_report(tracking_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return result


@app.get("/api/system-health")
def system_health() -> dict:
    from backend.api.services import get_system_health
    return get_system_health()


@app.get("/api/control/simulate")
def control_simulate(lat: float = Query(...), lon: float = Query(...), vehicle_type: str = Query("CAR")) -> dict:
    from backend.api.services import simulate_tactical_control
    return simulate_tactical_control(lat, lon, vehicle_type)


@app.get("/api/strategy/simulate")
def strategy_simulate(patrol_increase_pct: float = Query(50.0, ge=0, le=200)) -> dict:
    from backend.api.services import simulate_strategy
    return simulate_strategy(patrol_increase_pct)


@app.get("/api/analytics/explorer")
def analytics_explorer() -> dict:
    from backend.api.services import get_analytics_explorer
    return get_analytics_explorer()

