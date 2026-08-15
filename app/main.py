import asyncio
import secrets
import json
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.security import APIKeyHeader
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.analysis import analyze
from app.technical_indicators import calculate_technical_indicators
from app.config import settings
from app.database import Database
from app.service import sync_history, sync_market_data
from app.revenue import analyze_revenue, sync_revenue
from app.valuation import analyze_valuations, sync_valuations
from app.financials import analyze_financials, sync_financials
from app.historical_fundamentals import sync_historical_fundamentals
from app.fundamental_batch import run_fundamental_batch, run_price_history_batch
from app.historical_valuation import get_historical_valuation
from app.daily_sync import latest_daily_sync, run_daily_close_sync
from app.sync_scheduler import daily_sync_loop
from app.performance import capture_recommendation_snapshots, model_performance
from app.analysis_sync import analysis_sync_plan, sync_missing_analysis_data
from app.backtest import historical_backtest
from app.strategy_backtest import strategy_walk_forward_backtest
from app.technical_strategy_backtest import (
    bollinger_rsi_mean_reversion_backtest, breakout_atr_backtest, ema_adx_atr_backtest,
)
from app.research_lab import (
    breakout_walk_forward_study, factor_ablation_study, technical_execution_assumptions, technical_parameter_study,
    technical_research_governance,
)
from app.strategy_governance import experiment_history, record_strategy_experiment
from app.research_jobs import research_jobs
from app.paper_strategy import paper_strategy_summary, run_paper_strategy_valuation
from app.vnext_backtest import vnext_walk_forward_backtest
from app.portfolio import PositionUpdate, portfolio_summary
from app.dividends import sync_dividends
from app.ownership import analyze_ownership, sync_ownership
from app.institutions import sync_institutional_trades
from app.company import company_profile
from app.alerts import build_alerts
from app.market_seed import load_analysis_seed, load_market_seed
from app.market_context import get_market_context
from app.market_score_research import validate_market_score
from app.stock_score import score_stock
from app.recommendations import recommend_stocks
from app.vnext_model import evaluate_vnext_stock, recommend_vnext_stocks
from app.recommendation_gate import apply_formal_recommendation_gate
from app.data_quality import build_data_quality_report, capture_data_quality_snapshot
from app.factor_validation import factor_validation_report
from app.dashboard import build_daily_dashboard
from app.short_term_decision import market_mode
from app.short_analysis import build_short_analysis
from app.short_term_tracking import (
    capture_short_term_ranking_snapshot,
    published_short_term_decisions,
    short_term_ranking_tracking,
)
from app.short_term_ranking_backtest import short_term_ranking_backtest
from app.short_term_positions import (
    ManualShortTermPositionOpen,
    ShortTermPositionExecution,
    ShortTermPositionOpen,
    open_manual_short_term_position,
    open_short_term_position,
    record_short_term_execution,
    short_term_position_summary,
)
from app.decision_history import capture_daily_decision_history
from app.screening import (
    ScreenerFilters,
    screen_stocks,
    screening_csv,
    sync_screening_universe,
)

database = Database(settings.database_path)
admin_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def require_admin_key(api_key: Annotated[str | None, Depends(admin_key_header)]) -> None:
    """Protect all state-changing routes in configured or hosted environments."""
    protection_enabled = settings.require_admin_key or bool(settings.admin_api_key)
    if not protection_enabled:
        return
    if not settings.admin_api_key:
        raise HTTPException(503, "管理 API 尚未配置 ADMIN_API_KEY")
    if not api_key or not secrets.compare_digest(api_key, settings.admin_api_key):
        raise HTTPException(401, "需要有效的 X-Admin-Key")


def require_local_request(request: Request) -> None:
    """Allow portfolio mutations only through the loopback website."""
    if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(403, "公開網站只能查看；請回到本機網站登記交易")


@asynccontextmanager
async def lifespan(application: FastAPI):
    database.initialize()
    load_market_seed(database)
    load_analysis_seed(database)
    stop_scheduler = asyncio.Event()
    scheduler_task = asyncio.create_task(daily_sync_loop(database, stop_scheduler))
    application.state.scheduler_task = scheduler_task
    try:
        yield
    finally:
        stop_scheduler.set()
        await scheduler_task


app = FastAPI(title="台股分析 API", version="0.1.0", lifespan=lifespan)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
def user_interface() -> FileResponse:
    return FileResponse(static_dir / "focus.html")


@app.get("/stock/", include_in_schema=False)
def stock_interface() -> FileResponse:
    """Keep the full individual-stock workspace outside the daily home."""
    return FileResponse(static_dir / "index.html")


@app.get("/screener/", include_in_schema=False)
def screener_interface() -> FileResponse:
    return FileResponse(static_dir / "screener.html")


@app.get("/watchlist/", include_in_schema=False)
def watchlist_interface() -> FileResponse:
    return FileResponse(static_dir / "watchlist.html")


@app.get("/recommendations/", include_in_schema=False)
def recommendations_interface() -> FileResponse:
    return FileResponse(static_dir / "recommendations.html")


@app.get("/alerts/", include_in_schema=False)
def alerts_interface() -> FileResponse:
    return FileResponse(static_dir / "alerts.html")


@app.get("/performance/", include_in_schema=False)
def performance_interface() -> FileResponse:
    return FileResponse(static_dir / "performance.html")


@app.get("/data-quality/", include_in_schema=False)
def data_quality_interface() -> FileResponse:
    return FileResponse(static_dir / "data-quality.html")


@app.get("/short-analysis/", include_in_schema=False)
def short_analysis_interface() -> FileResponse:
    return FileResponse(static_dir / "short-analysis.html")


@app.get("/ranking/", include_in_schema=False)
def ranking_interface() -> FileResponse:
    return FileResponse(static_dir / "ranking.html")


@app.get("/dashboard/", include_in_schema=False)
def dashboard_interface() -> RedirectResponse:
    """The former decision UI is retired; audit APIs remain available."""
    return RedirectResponse(url="/recommendations/", status_code=307)


@app.get("/health")
def health(response: Response) -> dict[str, object]:
    database_status = "ok"
    try:
        with database.connect() as connection:
            connection.execute("SELECT 1").fetchone()
    except Exception:
        database_status = "unavailable"
    scheduler_task = getattr(app.state, "scheduler_task", None)
    scheduler_status = (
        "running" if scheduler_task is not None and not scheduler_task.done() else "stopped"
    )
    latest = database.get_latest_daily_sync_run() if database_status == "ok" else None
    ready = database_status == "ok" and scheduler_status == "running"
    response.status_code = 200 if ready else 503
    return {
        "status": "ok" if ready else "degraded",
        "database": database_status,
        "scheduler": scheduler_status,
        "version": "0.1.0",
        "build": os.getenv("RENDER_GIT_COMMIT", "local")[:12],
        "latest_daily_sync": ({
            "id": latest.get("id"),
            "status": latest.get("status"),
            "finished_at": latest.get("finished_at"),
        } if latest else None),
    }


@app.get("/alerts")
def alerts(mode: Literal["short", "long"] = "short") -> dict:
    try:
        context = get_market_context()
    except Exception:
        context = {"market_score": 50, "regime": "資料暫缺", "events": []}
    return build_alerts(database, mode, context)


@app.post("/sync", dependencies=[Depends(require_admin_key)])
def sync() -> dict:
    return sync_market_data(database)


@app.post("/daily-sync", dependencies=[Depends(require_admin_key)])
def daily_sync() -> dict:
    return run_daily_close_sync(database)


@app.get("/daily-sync/status")
def daily_sync_status() -> dict:
    return latest_daily_sync(database)


@app.get("/data-quality")
def data_quality(target_limit: int = Query(100, ge=10, le=200)) -> dict:
    return build_data_quality_report(database, target_limit)


@app.post("/data-quality/snapshot", dependencies=[Depends(require_admin_key)])
def data_quality_snapshot() -> dict:
    return capture_data_quality_snapshot(database)


@app.get("/data-quality/snapshots")
def data_quality_snapshots(limit: int = Query(30, ge=1, le=100)) -> list[dict]:
    return database.list_data_quality_snapshots(limit)


@app.get("/dashboard")
def dashboard() -> dict:
    context = get_market_context()
    return build_daily_dashboard(database, context)


@app.get("/short-term-decisions")
def short_term_decisions(limit: int = Query(20, ge=1, le=100), as_of: date | None = None) -> dict:
    """Research-only 3–10 session decision candidates, evaluated after the close."""
    return published_short_term_decisions(
        database, get_market_context(), as_of or date.today(), limit
    )


@app.get("/short-term-positions")
def short_term_positions(as_of: date | None = None) -> dict:
    """Track actual ranking-derived positions separately from ranking membership."""
    return short_term_position_summary(database, as_of)


@app.post("/short-term-positions", dependencies=[Depends(require_local_request)])
def short_term_position_open(payload: ShortTermPositionOpen) -> dict:
    try:
        return open_short_term_position(database, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/short-term-positions/manual", dependencies=[Depends(require_local_request)])
def manual_short_term_position_open(payload: ManualShortTermPositionOpen) -> dict:
    try:
        return open_manual_short_term_position(database, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post(
    "/short-term-positions/{symbol}/executions",
    dependencies=[Depends(require_local_request)],
)
def short_term_position_execution(
    symbol: str, payload: ShortTermPositionExecution
) -> dict:
    try:
        return record_short_term_execution(database, symbol.strip(), payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/short-term-ranking/snapshot", dependencies=[Depends(require_admin_key)])
def short_term_ranking_snapshot(as_of: date | None = None) -> dict:
    return capture_short_term_ranking_snapshot(
        database, get_market_context(), as_of or date.today()
    )


@app.get("/short-term-ranking/tracking")
def short_term_ranking_tracking_api(
    snapshot_limit: int = Query(300, ge=10, le=2000),
) -> dict:
    return short_term_ranking_tracking(database, snapshot_limit=snapshot_limit)


@app.get("/research/short-term-ranking-backtest")
def short_term_ranking_backtest_api(
    start_date: date = date(2023, 4, 1),
    end_date: date | None = None,
    frequency: Literal["daily", "weekly", "monthly"] = "monthly",
    top_n: int = Query(10, ge=1, le=50),
    minimum_full_factor_symbols: int = Query(50, ge=1, le=2000),
    require_complete_factor_coverage: bool = True,
    max_signal_dates: int = Query(120, ge=1, le=260),
    commission_bps: float = Query(14.25, ge=0, le=100),
    sell_tax_bps: float = Query(30, ge=0, le=100),
    slippage_bps: float = Query(5, ge=0, le=100),
) -> dict:
    """Replay the fixed attention ranking with strict point-in-time gates."""
    return short_term_ranking_backtest(
        database,
        start_date=start_date.isoformat(),
        end_date=(end_date or date.today()).isoformat(),
        frequency=frequency,
        top_n=top_n,
        minimum_full_factor_symbols=minimum_full_factor_symbols,
        require_complete_factor_coverage=require_complete_factor_coverage,
        max_signal_dates=max_signal_dates,
        commission_bps=commission_bps,
        sell_tax_bps=sell_tax_bps,
        slippage_bps=slippage_bps,
    )


@app.post(
    "/research/jobs/short-term-ranking-backtest",
    dependencies=[Depends(require_admin_key)],
)
def start_short_term_ranking_backtest_job(
    start_date: date = date(2023, 4, 1),
    end_date: date | None = None,
    frequency: Literal["daily", "weekly", "monthly"] = "monthly",
    top_n: int = Query(10, ge=1, le=50),
    minimum_full_factor_symbols: int = Query(50, ge=1, le=2000),
    require_complete_factor_coverage: bool = True,
    max_signal_dates: int = Query(120, ge=1, le=260),
    commission_bps: float = Query(14.25, ge=0, le=100),
    sell_tax_bps: float = Query(30, ge=0, le=100),
    slippage_bps: float = Query(5, ge=0, le=100),
) -> dict:
    """Run the expensive PIT replay outside the request connection."""
    resolved_end = end_date or date.today()
    if start_date > resolved_end:
        raise HTTPException(400, "start_date must not be after end_date")
    parameters = {
        "start_date": start_date.isoformat(),
        "end_date": resolved_end.isoformat(),
        "frequency": frequency,
        "top_n": top_n,
        "minimum_full_factor_symbols": minimum_full_factor_symbols,
        "require_complete_factor_coverage": require_complete_factor_coverage,
        "max_signal_dates": max_signal_dates,
        "commission_bps": commission_bps,
        "sell_tax_bps": sell_tax_bps,
        "slippage_bps": slippage_bps,
    }

    def work() -> dict:
        return short_term_ranking_backtest(database, **parameters)

    cache_key = json.dumps(parameters, sort_keys=True)
    job = research_jobs.submit(
        "short-term-ranking-backtest", work, cache_key=cache_key
    )
    return {
        "job": job,
        "parameters": parameters,
        "poll_url": f"/research/jobs/{job['id']}",
        "research_only": True,
        "formal_recommendation_allowed": False,
        "limitation": "背景工作在伺服器重啟時會中止；相同參數會重用目前或已完成的工作。",
    }


@app.post("/dashboard/snapshot", dependencies=[Depends(require_admin_key)])
def dashboard_snapshot() -> dict:
    context = get_market_context()
    quality = database.list_data_quality_snapshots(1)
    decision = capture_daily_decision_history(database, context, quality[0]["id"] if quality else None)
    paper = run_paper_strategy_valuation(database)
    return {**decision, "paper_strategy_tracking": paper}


@app.get("/dashboard/history")
def dashboard_history(limit: int = Query(30, ge=1, le=180)) -> list[dict]:
    return database.list_daily_decision_logs(limit)


@app.post("/research/paper-strategies/valuation", dependencies=[Depends(require_admin_key)])
def research_paper_strategy_valuation() -> dict:
    return run_paper_strategy_valuation(database)


@app.get("/research/paper-strategies")
def research_paper_strategies() -> dict:
    return paper_strategy_summary(database)


@app.post("/performance/snapshot", dependencies=[Depends(require_admin_key)])
def performance_snapshot() -> dict:
    return capture_recommendation_snapshots(database, get_market_context())


@app.get("/performance/summary")
def performance_summary(
    profile: Literal["evidence_based", "balanced"] = "evidence_based",
    horizon: Literal["5", "20", "60", "120", "250"] = "20",
    min_score: float = Query(65, ge=0, le=100),
) -> dict:
    return model_performance(database, profile, int(horizon), min_score)


@app.get("/performance/backtest")
def performance_backtest(
    horizon: Literal["5", "20", "60", "120", "250"] = "20",
    min_score: float = Query(65, ge=0, le=100),
    top_n: int = Query(10, ge=1, le=50),
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    return historical_backtest(database, int(horizon), min_score, top_n,
                               start_date.isoformat() if start_date else None,
                               end_date.isoformat() if end_date else None)


@app.get("/performance/factors")
def performance_factors(
    profile: Literal["evidence_based", "balanced"] = "evidence_based",
    horizon: Literal["5", "20", "60", "120", "250"] = "20",
    minimum_sample: int = Query(20, ge=10, le=500),
) -> dict:
    return factor_validation_report(database, profile, int(horizon), minimum_sample)


@app.get("/performance/strategy-backtest")
def performance_strategy_backtest(
    min_score: float = Query(65, ge=0, le=100),
    top_n: int = Query(10, ge=1, le=50),
    commission_bps: float = Query(14.25, ge=0, le=100),
    sell_tax_bps: float = Query(30, ge=0, le=100),
    slippage_bps: float = Query(5, ge=0, le=100),
    min_turnover: float = Query(10_000_000, ge=0),
    single_stock_limit_percent: float = Query(10, gt=0, le=100),
    industry_limit_percent: float = Query(25, gt=0, le=100),
    start_date: date | None = None,
    end_date: date | None = None,
    out_of_sample_start: date | None = None,
) -> dict:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "start_date must not be after end_date")
    if out_of_sample_start and start_date and out_of_sample_start < start_date:
        raise HTTPException(400, "out_of_sample_start must be inside the selected period")
    if out_of_sample_start and end_date and out_of_sample_start > end_date:
        raise HTTPException(400, "out_of_sample_start must be inside the selected period")
    return strategy_walk_forward_backtest(
        database, min_score=min_score, top_n=top_n, commission_bps=commission_bps,
        sell_tax_bps=sell_tax_bps, slippage_bps=slippage_bps,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        out_of_sample_start=out_of_sample_start.isoformat() if out_of_sample_start else None,
        min_turnover=min_turnover, single_stock_limit_percent=single_stock_limit_percent,
        industry_limit_percent=industry_limit_percent,
    )


@app.get("/performance/vnext-walk-forward")
def performance_vnext_walk_forward(
    horizon: Literal["5", "20", "60", "120", "250"] = "20",
    top_n: int = Query(10, ge=1, le=50),
    commission_bps: float = Query(14.25, ge=0, le=100),
    sell_tax_bps: float = Query(30, ge=0, le=100),
    slippage_bps: float = Query(5, ge=0, le=100),
    min_turnover: float = Query(10_000_000, ge=0),
    embargo_sessions: int = Query(7, ge=0, le=60),
    max_total_exposure_percent: float = Query(80, gt=0, le=100),
    single_stock_limit_percent: float = Query(10, gt=0, le=100),
    industry_limit_percent: float = Query(25, gt=0, le=100),
    technical_timing: bool = False,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "start_date must not be after end_date")
    return vnext_walk_forward_backtest(
        database, int(horizon), top_n, commission_bps, sell_tax_bps, slippage_bps,
        min_turnover, start_date.isoformat() if start_date else None,
        end_date.isoformat() if end_date else None, embargo_sessions,
        max_total_exposure_percent, single_stock_limit_percent, industry_limit_percent,
        technical_timing,
    )


@app.get("/performance/technical-breakout-backtest")
def performance_technical_breakout_backtest(
    lookback: int = Query(20, ge=10, le=120),
    volume_multiple: float = Query(1.5, ge=1, le=5),
    min_breakout_percent: float = Query(3, ge=0, le=20),
    max_holding_days: int = Query(20, ge=2, le=250),
    stop_atr_multiple: float = Query(2, ge=.5, le=10),
    reward_risk: float = Query(2, ge=.5, le=10),
    commission_bps: float = Query(14.25, ge=0, le=100),
    sell_tax_bps: float = Query(30, ge=0, le=100),
    slippage_bps: float = Query(5, ge=0, le=100),
    min_turnover: float = Query(10_000_000, ge=0),
    max_total_exposure_percent: float = Query(80, gt=0, le=100),
    single_stock_limit_percent: float = Query(10, gt=0, le=100),
    industry_limit_percent: float = Query(25, gt=0, le=100),
    start_date: date | None = None,
    end_date: date | None = None,
    out_of_sample_start: date | None = None,
) -> dict:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "start_date must not be after end_date")
    return breakout_atr_backtest(
        database, lookback=lookback, volume_multiple=volume_multiple,
        min_breakout_percent=min_breakout_percent, max_holding_days=max_holding_days,
        stop_atr_multiple=stop_atr_multiple, reward_risk=reward_risk,
        commission_bps=commission_bps, sell_tax_bps=sell_tax_bps, slippage_bps=slippage_bps,
        min_turnover=min_turnover, start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        out_of_sample_start=out_of_sample_start.isoformat() if out_of_sample_start else None,
        max_total_exposure_percent=max_total_exposure_percent,
        single_stock_limit_percent=single_stock_limit_percent,
        industry_limit_percent=industry_limit_percent,
    )


@app.get("/performance/technical-ema-adx-backtest")
def performance_technical_ema_adx_backtest(
    start_date: date | None = None, end_date: date | None = None,
    out_of_sample_start: date | None = None,
) -> dict:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "start_date must not be after end_date")
    return ema_adx_atr_backtest(
        database, start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        out_of_sample_start=out_of_sample_start.isoformat() if out_of_sample_start else None,
    )


@app.get("/research/experiments")
def research_experiments(strategy_key: str | None = None, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    return experiment_history(database, strategy_key, limit)


@app.post("/research/experiments/market-strategy", dependencies=[Depends(require_admin_key)])
def record_market_strategy_experiment(
    min_score: float = Query(65, ge=0, le=100), top_n: int = Query(10, ge=1, le=50),
    out_of_sample_start: date | None = None, start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """Run and record a bounded research experiment; it cannot modify live settings."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "start_date must not be after end_date")
    result = strategy_walk_forward_backtest(
        database, min_score=min_score, top_n=top_n,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        out_of_sample_start=out_of_sample_start.isoformat() if out_of_sample_start else None,
    )
    audit_records = [{"symbol": "aggregate_fold", "decision_date": row.get("date"),
                      "available_at": row.get("date")}
                     for row in result.get("outcomes", [])]
    saved = record_strategy_experiment(
        database, strategy_key="market_strategy", strategy_version="walk-forward-portfolio-v1",
        parameters={"min_score": min_score, "top_n": top_n,
                    "start_date": start_date, "end_date": end_date,
                    "out_of_sample_start": out_of_sample_start},
        result=result, audit_records=audit_records,
        train_start=start_date.isoformat() if start_date else None,
        train_end=out_of_sample_start.isoformat() if out_of_sample_start else None,
        out_of_sample_start=out_of_sample_start.isoformat() if out_of_sample_start else None,
        out_of_sample_end=end_date.isoformat() if end_date else None,
    )
    return {"experiment": saved, "result": result,
            "research_only": True, "formal_recommendation_allowed": False}


@app.get("/research/lab")
def research_lab() -> dict:
    return technical_parameter_study(database)


@app.get("/research/market-score-validation")
def market_score_validation(start_date: date | None = None, end_date: date | None = None) -> dict:
    """Evaluate fixed market-score states without changing live decisions."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "start_date must not be after end_date")
    return validate_market_score(
        database,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
    )


@app.post("/research/jobs/parameter-study", dependencies=[Depends(require_admin_key)])
def start_parameter_study_job() -> dict:
    def work() -> dict:
        result = technical_parameter_study(database)
        saved = record_strategy_experiment(
            database, strategy_key="technical_parameter_study", strategy_version="breakout-neighbourhood-v1",
            parameters=result["test_family"], result=result, audit_records=result.get("audit_records", []),
            out_of_sample_start=result["out_of_sample_start"],
        )
        return {"experiment": saved, "result": result}
    job = research_jobs.submit("parameter-study", work)
    return {"job": job, "research_only": True, "formal_recommendation_allowed": False,
            "limitation": "Job state is in memory and is lost if the local server restarts; completed results do not alter live rules."}


@app.get("/research/jobs/{job_id}")
def research_job(job_id: str) -> dict:
    job = research_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Research job was not found or the local server restarted")
    return job


@app.post("/research/jobs/breakout-walk-forward", dependencies=[Depends(require_admin_key)])
def start_breakout_walk_forward_job() -> dict:
    def work() -> dict:
        result = breakout_walk_forward_study(database)
        saved = record_strategy_experiment(
            database, strategy_key="technical_breakout_walk_forward", strategy_version="20d_breakout_volume_atr_v1",
            parameters={"folds": 3, "fold_sessions": 120, "purge_sessions": 20, "embargo_sessions": 5},
            result=result, audit_records=result.get("audit_records", []),
        )
        return {"experiment": saved, "result": result}
    job = research_jobs.submit("breakout-walk-forward", work)
    return {"job": job, "research_only": True, "formal_recommendation_allowed": False,
            "limitation": "Frozen-rule walk-forward output is research evidence only and does not remove the paper-tracking requirement."}


@app.get("/research/ema-adx")
def research_ema_adx() -> dict:
    return ema_adx_atr_backtest(database, out_of_sample_start="2026-01-01")


@app.post("/research/experiments/ema-adx", dependencies=[Depends(require_admin_key)])
def record_ema_adx_experiment(
    out_of_sample_start: date = date(2026, 1, 1), start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """Run the locked EMA/ADX study and retain its PIT audit evidence."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "start_date must not be after end_date")
    result = ema_adx_atr_backtest(
        database, start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        out_of_sample_start=out_of_sample_start.isoformat(),
    )
    audit_records = result.get("audit_records", [])
    saved = record_strategy_experiment(
        database, strategy_key="technical_ema_adx_atr",
        strategy_version="ema20_ema100_adx_atr_v1",
        parameters=result["parameters"], result=result, audit_records=audit_records,
        train_start=start_date.isoformat() if start_date else None,
        train_end=out_of_sample_start.isoformat(),
        out_of_sample_start=out_of_sample_start.isoformat(),
        out_of_sample_end=end_date.isoformat() if end_date else None,
    )
    return {"experiment": saved, "result": result,
            "research_only": True, "formal_recommendation_allowed": False}


@app.post("/research/experiments/technical-breakout", dependencies=[Depends(require_admin_key)])
def record_technical_breakout_experiment(
    out_of_sample_start: date = date(2026, 1, 1), start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """Save the fixed breakout rule's point-in-time evidence without touching live rules."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "start_date must not be after end_date")
    result = breakout_atr_backtest(
        database, start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        out_of_sample_start=out_of_sample_start.isoformat(),
    )
    saved = record_strategy_experiment(
        database, strategy_key="technical_breakout_atr", strategy_version="20d_breakout_volume_atr_v1",
        parameters=result["parameters"], result=result, audit_records=result.get("audit_records", []),
        train_start=start_date.isoformat() if start_date else None,
        train_end=out_of_sample_start.isoformat(), out_of_sample_start=out_of_sample_start.isoformat(),
        out_of_sample_end=end_date.isoformat() if end_date else None,
    )
    return {"experiment": saved, "result": result,
            "research_only": True, "formal_recommendation_allowed": False}


@app.post("/research/experiments/bollinger-rsi", dependencies=[Depends(require_admin_key)])
def record_bollinger_rsi_experiment(
    out_of_sample_start: date = date(2026, 1, 1), start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "start_date must not be after end_date")
    result = bollinger_rsi_mean_reversion_backtest(
        database, start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        out_of_sample_start=out_of_sample_start.isoformat(),
    )
    saved = record_strategy_experiment(
        database, strategy_key="technical_bollinger_rsi", strategy_version="bollinger20_rsi14_mean_reversion_v1",
        parameters=result["parameters"], result=result, audit_records=result["audit_records"],
        train_start=start_date.isoformat() if start_date else None,
        train_end=out_of_sample_start.isoformat(), out_of_sample_start=out_of_sample_start.isoformat(),
        out_of_sample_end=end_date.isoformat() if end_date else None,
    )
    return {"experiment": saved, "result": result,
            "research_only": True, "formal_recommendation_allowed": False}


@app.get("/research/technical-governance")
def research_technical_governance() -> dict:
    return technical_research_governance(database)


@app.get("/research/execution-assumptions")
def research_execution_assumptions() -> dict:
    return technical_execution_assumptions()


@app.get("/research/factor-ablation")
def research_factor_ablation(out_of_sample_start: date = date(2026, 1, 1)) -> dict:
    return factor_ablation_study(database, out_of_sample_start.isoformat())


@app.get("/research/", include_in_schema=False)
def research_interface() -> FileResponse:
    return FileResponse(static_dir / "research.html")


@app.get("/stocks")
def stocks(q: str | None = None, limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    return database.list_instruments(q, limit)


@app.get("/stocks/{symbol}/company")
def company(symbol: str) -> dict:
    instrument = database.get_instrument(symbol)
    if not instrument:
        raise HTTPException(404, "找不到公司基本資料，請先同步市場清單。")
    return company_profile(instrument)


@app.get("/stocks/{symbol}/sync-plan")
def stock_sync_plan(symbol: str) -> dict:
    try:
        return analysis_sync_plan(database, symbol)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/stocks/{symbol}/sync-missing", dependencies=[Depends(require_admin_key)])
def stock_sync_missing(symbol: str, force: bool = False) -> dict:
    try:
        return sync_missing_analysis_data(database, symbol, force)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/watchlist")
def watchlist() -> list[dict]:
    return database.list_watchlist()


@app.get("/watchlist/{symbol}/status")
def watchlist_status(symbol: str) -> dict[str, bool]:
    return {"watched": database.is_watched(symbol)}


@app.put("/watchlist/{symbol}", dependencies=[Depends(require_admin_key)])
def watchlist_add(symbol: str) -> dict[str, str | bool]:
    instrument = database.get_instrument(symbol)
    if not instrument:
        raise HTTPException(404, "找不到股票代號；請先更新全市場清單")
    database.add_to_watchlist(symbol, instrument["market"])
    return {"symbol": symbol, "watched": True}


@app.delete("/watchlist/{symbol}", dependencies=[Depends(require_admin_key)])
def watchlist_remove(symbol: str) -> dict[str, str | bool]:
    database.remove_from_watchlist(symbol)
    return {"symbol": symbol, "watched": False}


@app.put("/watchlist/{symbol}/position", dependencies=[Depends(require_admin_key)])
def watchlist_position(symbol: str, position: PositionUpdate) -> dict:
    if not database.update_watchlist_position(symbol, position.model_dump()):
        raise HTTPException(404, "股票尚未加入我的股票")
    return {"symbol": symbol, "status": "updated"}


@app.get("/portfolio/summary")
def get_portfolio_summary() -> dict:
    try:
        context = get_market_context()
    except Exception:
        context = {"market_score": 50, "overheat_score": 0, "regime": "unknown"}
    return portfolio_summary(database, context)


@app.get("/stocks/{symbol}/prices")
def prices(
    symbol: str,
    limit: int = Query(250, ge=1, le=5000),
    start: date | None = None,
    end: date | None = None,
) -> list[dict]:
    if start and end and start > end:
        raise HTTPException(400, "start 不可晚於 end")
    rows = database.get_prices(
        symbol,
        limit,
        start.isoformat() if start else None,
        end.isoformat() if end else None,
    )
    if not rows:
        raise HTTPException(404, "找不到行情；請先執行 POST /sync")
    return rows


@app.get("/stocks/{symbol}/analysis")
def stock_analysis(symbol: str) -> dict:
    # 技術指標只使用尾端資料，但歷史最高收盤價必須涵蓋所有已同步行情。
    result = analyze(database.get_prices(symbol, 100_000))
    if not result:
        raise HTTPException(404, "找不到行情；請先執行 POST /sync")
    return result


@app.get("/stocks/{symbol}/technical")
def stock_technical_analysis(symbol: str, limit: int = Query(300, ge=20, le=1000),
                             engine: Literal["auto", "python", "talib"] = "auto") -> dict:
    if not database.get_instrument(symbol):
        raise HTTPException(404, f"Stock {symbol} was not found")
    result = calculate_technical_indicators(database.get_prices(symbol, limit), engine)
    if result["input_rows"] == 0:
        raise HTTPException(404, "No daily price history is available")
    return result


@app.get("/stocks/{symbol}/short-analysis")
def stock_short_analysis(symbol: str, as_of: date | None = None) -> dict:
    try:
        context = get_market_context()
        return build_short_analysis(database, symbol, as_of=as_of.isoformat() if as_of else None,
                                    market_mode=market_mode(context), market_context=context)
    except LookupError:
        raise HTTPException(404, f"Stock {symbol} was not found")


@app.get("/stocks/{symbol}/score")
def stock_score(symbol: str) -> dict:
    result = score_stock(database, symbol)
    if not result:
        raise HTTPException(404, "找不到股票評分資料。")
    return result


@app.get("/stocks/{symbol}/vnext")
def stock_vnext(symbol: str, as_of: date | None = None) -> dict:
    if not database.get_instrument(symbol):
        raise HTTPException(404, f"Stock {symbol} was not found")
    try:
        context = get_market_context()
    except Exception:
        context = {"market_score": 50, "overheat_score": 0, "regime": "unknown"}
    result = evaluate_vnext_stock(database, symbol, as_of or date.today(), context)
    return apply_formal_recommendation_gate(result, build_data_quality_report(database))


@app.post("/dividends/sync", dependencies=[Depends(require_admin_key)])
def dividends_sync(symbol: str) -> dict:
    try:
        return sync_dividends(database, symbol)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"官方除權息資料同步失敗：{exc}") from exc


@app.get("/stocks/{symbol}/dividends")
def dividends(symbol: str, limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    return database.get_dividend_events(symbol, limit)


@app.post("/ownership/sync", dependencies=[Depends(require_admin_key)])
def ownership_sync(symbol: str) -> dict:
    try:
        return sync_ownership(database, symbol)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"同步股權分散資料失敗：{exc}") from exc


@app.get("/stocks/{symbol}/ownership")
def ownership(symbol: str) -> dict:
    result = analyze_ownership(database.get_shareholder_distribution(symbol))
    if not result:
        raise HTTPException(404, "尚無股權分散資料，請先執行同步。")
    return result


@app.post("/institutions/sync", dependencies=[Depends(require_admin_key)])
def institutions_sync(symbol: str) -> dict:
    try:
        return sync_institutional_trades(database, symbol)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"同步法人買賣資料失敗：{exc}") from exc


@app.get("/stocks/{symbol}/institutions")
def institutions(symbol: str, limit: int = Query(120, ge=1, le=500)) -> list[dict]:
    return database.get_institutional_trades(symbol, limit)


@app.post("/history/sync", dependencies=[Depends(require_admin_key)])
def history_sync(symbol: str, start: date, end: date) -> dict:
    try:
        return sync_history(database, symbol, start, end)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"官方歷史行情同步失敗：{exc}") from exc


@app.get("/history/status")
def history_status(
    symbol: str | None = None, limit: int = Query(20, ge=1, le=100)
) -> list[dict]:
    return database.list_sync_runs(symbol, limit)


@app.post("/revenue/sync", dependencies=[Depends(require_admin_key)])
def revenue_sync(symbol: str, start: str, end: str) -> dict:
    try:
        return sync_revenue(database, symbol, start, end)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"官方月營收同步失敗：{exc}") from exc


@app.get("/stocks/{symbol}/revenue")
def monthly_revenue(symbol: str, limit: int = Query(60, ge=1, le=240)) -> list[dict]:
    return database.get_monthly_revenues(symbol, limit)


@app.get("/stocks/{symbol}/revenue/analysis")
def revenue_analysis(symbol: str) -> dict:
    result = analyze_revenue(database.get_monthly_revenues(symbol, 240))
    if not result:
        raise HTTPException(404, "找不到月營收；請先同步月營收資料")
    return result


@app.post("/valuation/sync", dependencies=[Depends(require_admin_key)])
def valuation_sync(symbol: str, start: str, end: str) -> dict:
    try:
        return sync_valuations(database, symbol, start, end)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"官方估值資料同步失敗：{exc}") from exc


@app.get("/stocks/{symbol}/valuations")
def valuations(symbol: str, limit: int = Query(120, ge=1, le=240)) -> list[dict]:
    return database.get_valuations(symbol, limit)


@app.get("/stocks/{symbol}/valuations/analysis")
def valuation_analysis(symbol: str) -> dict:
    result = analyze_valuations(database.get_valuations(symbol, 240))
    if not result:
        raise HTTPException(404, "找不到估值資料；請先同步估值資料")
    return result


@app.post("/financials/sync", dependencies=[Depends(require_admin_key)])
def financials_sync(symbol: str) -> dict:
    try:
        return sync_financials(database, symbol)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"官方財報同步失敗：{exc}") from exc


@app.get("/stocks/{symbol}/financials")
def financials(symbol: str, limit: int = Query(20, ge=1, le=40)) -> list[dict]:
    return database.get_financials(symbol, limit)


@app.post("/financials/history/sync", dependencies=[Depends(require_admin_key)])
def financial_history_sync(symbol: str, years: int = Query(5, ge=3, le=10)) -> dict:
    try:
        return sync_historical_fundamentals(database, symbol, years)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Historical fundamentals sync failed: {exc}") from exc


@app.get("/stocks/{symbol}/fundamentals/coverage")
def fundamentals_coverage(symbol: str) -> dict:
    if not database.get_instrument(symbol):
        raise HTTPException(404, f"Stock {symbol} was not found")
    return database.get_fundamentals_coverage(symbol)


@app.post("/financials/history/batch", dependencies=[Depends(require_admin_key)])
def financial_history_batch(
    target_limit: int = Query(100, ge=10, le=2500),
    batch_size: int = Query(10, ge=1, le=10),
    years: int = Query(5, ge=3, le=10), retry_failed: bool = False,
    scope: Literal["popular", "all"] = "popular",
) -> dict:
    return run_fundamental_batch(database, None if scope == "all" else target_limit,
                                 batch_size, years, retry_failed)


@app.get("/financials/history/batch/status")
def financial_history_batch_status(
    target_limit: int = Query(100, ge=10, le=2500),
    scope: Literal["popular", "all"] = "popular",
) -> dict:
    return database.get_fundamental_sync_progress(None if scope == "all" else target_limit)


@app.get("/stocks/{symbol}/valuation/history")
def stock_historical_valuation(symbol: str, series_limit: int = Query(250, ge=20, le=1500)) -> dict:
    result = get_historical_valuation(database, symbol, series_limit)
    if not result:
        raise HTTPException(404, "Historical valuation data is not yet available")
    return result


@app.post("/prices/history/batch", dependencies=[Depends(require_admin_key)])
def price_history_batch(target_limit: int = Query(100, ge=10, le=200),
                        batch_size: int = Query(10, ge=1, le=10),
                        years: int = Query(3, ge=2, le=5),
                        retry_failed: bool = False) -> dict:
    return run_price_history_batch(database, target_limit, batch_size, years, retry_failed)


@app.get("/prices/history/batch/status")
def price_history_batch_status(target_limit: int = Query(100, ge=10, le=200)) -> dict:
    return database.get_price_sync_progress(target_limit)


@app.get("/stocks/{symbol}/financials/analysis")
def financials_analysis(symbol: str) -> dict:
    result = analyze_financials(database.get_financials(symbol, 40))
    if not result:
        raise HTTPException(404, "找不到財報資料；請先同步最新財報")
    return result


@app.post("/screener/sync", dependencies=[Depends(require_admin_key)])
def screener_sync() -> dict:
    try:
        market = sync_market_data(database)
        return {**sync_screening_universe(database), "market": market}
    except Exception as exc:
        raise HTTPException(502, f"選股資料同步失敗：{exc}") from exc


@app.get("/screener")
def screener(filters: Annotated[ScreenerFilters, Query()]) -> list[dict]:
    return screen_stocks(database, filters)


@app.get("/screener/export")
def screener_export(filters: Annotated[ScreenerFilters, Query()]) -> Response:
    content = screening_csv(screen_stocks(database, filters))
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=taiwan-stock-screening.csv"},
    )


@app.get("/recommendations")
def recommendations(
    limit: int = Query(20, ge=1, le=100),
    min_completeness: int = Query(70, ge=0, le=100),
    profile: Literal["balanced", "value", "growth", "quality", "long_term_quality",
                     "evidence_based"] = "balanced",
) -> list[dict]:
    effective_limit = max(limit, 20) if profile == "evidence_based" else limit
    rows = recommend_stocks(database, effective_limit, min_completeness, profile)
    return rows[:limit]


@app.get("/recommendations/vnext")
def vnext_recommendations(
    limit: int = Query(20, ge=1, le=100),
    as_of: date | None = None,
) -> dict:
    try:
        context = get_market_context()
    except Exception:
        context = {"market_score": 50, "overheat_score": 0, "regime": "unknown"}
    result = recommend_vnext_stocks(database, as_of or date.today(), context, limit)
    apply_formal_recommendation_gate(result, build_data_quality_report(database))
    result["watchlist_sync"] = {"added": 0, "skipped": "manual_watchlist_only"}
    database.save_vnext_recommendation_run(
        result["as_of_date"], json.dumps(result, ensure_ascii=False, default=str)
    )
    return result


@app.get("/market-context")
def market_context(refresh: bool = False) -> dict:
    return get_market_context(force=refresh)


@app.get("/popular-stocks")
def popular_stocks(limit: int = Query(12, ge=1, le=50)) -> list[dict]:
    return database.list_popular_stocks(limit)
