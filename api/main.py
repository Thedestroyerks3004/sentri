import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from api import services
from api.intelligence import get_daily_briefing, get_patrol_map, get_zone_detail
from dispatcher import acknowledge_latest_dispatch, read_dispatch_log, run_dispatch_cycle

services.store.load()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


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


@app.get("/api/feedback-loop")
def feedback_loop(loc_key: str | None = Query(None)):
    return services.get_feedback_loop(loc_key=loc_key)


@app.get("/api/patrol-map")
def patrol_map(
    hour: int = Query(5, ge=0, le=23),
    day: int = Query(0, ge=0, le=6),
    limit: int = Query(200, le=500),
    patrol_tonight: bool = Query(False),
    search: str | None = Query(None),
):
    return get_patrol_map(hour=hour, day=day, limit=limit, patrol_tonight=patrol_tonight, search=search)


@app.get("/api/zone/{loc_key}")
def zone_detail(loc_key: str):
    result = get_zone_detail(loc_key)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/daily-briefing")
def daily_briefing():
    return get_daily_briefing()


@app.post("/api/dispatch/run")
def dispatch_run():
    return run_dispatch_cycle()


@app.post("/api/dispatch/acknowledge")
def dispatch_acknowledge():
    return acknowledge_latest_dispatch()


@app.get("/api/dispatch/log")
def dispatch_log(limit: int = Query(20, ge=1, le=100)):
    return read_dispatch_log(limit=limit)
