from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.analysis import analyze
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
from app.performance import capture_recommendation_snapshots, model_performance
from app.analysis_sync import analysis_sync_plan, sync_missing_analysis_data
from app.backtest import historical_backtest
from app.portfolio import PositionUpdate, portfolio_summary
from app.dividends import sync_dividends
from app.ownership import analyze_ownership, sync_ownership
from app.institutions import sync_institutional_trades
from app.company import company_profile
from app.alerts import build_alerts
from app.market_seed import load_analysis_seed, load_market_seed
from app.market_context import get_market_context
from app.stock_score import score_stock
from app.recommendations import recommend_stocks
from app.screening import (
    ScreenerFilters,
    screen_stocks,
    screening_csv,
    sync_screening_universe,
)

database = Database(settings.database_path)


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    load_market_seed(database)
    load_analysis_seed(database)
    yield


app = FastAPI(title="台股分析 API", version="0.1.0", lifespan=lifespan)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
def user_interface() -> FileResponse:
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/alerts")
def alerts(mode: Literal["short", "long"] = "short") -> dict:
    try:
        context = get_market_context()
    except Exception:
        context = {"market_score": 50, "regime": "資料暫缺", "events": []}
    return build_alerts(database, mode, context)


@app.post("/sync")
def sync() -> dict:
    return sync_market_data(database)


@app.post("/daily-sync")
def daily_sync() -> dict:
    return run_daily_close_sync(database)


@app.get("/daily-sync/status")
def daily_sync_status() -> dict:
    return latest_daily_sync(database)


@app.post("/performance/snapshot")
def performance_snapshot() -> dict:
    return capture_recommendation_snapshots(database, get_market_context())


@app.get("/performance/summary")
def performance_summary(
    profile: Literal["evidence_based", "balanced"] = "evidence_based",
    horizon: Literal[5, 20, 60, 120, 250] = 20,
    min_score: float = Query(65, ge=0, le=100),
) -> dict:
    return model_performance(database, profile, horizon, min_score)


@app.get("/performance/backtest")
def performance_backtest(
    horizon: Literal[5, 20, 60, 120, 250] = 20,
    min_score: float = Query(65, ge=0, le=100),
    top_n: int = Query(10, ge=1, le=50),
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    return historical_backtest(database, horizon, min_score, top_n,
                               start_date.isoformat() if start_date else None,
                               end_date.isoformat() if end_date else None)


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


@app.post("/stocks/{symbol}/sync-missing")
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


@app.put("/watchlist/{symbol}")
def watchlist_add(symbol: str) -> dict[str, str | bool]:
    instrument = database.get_instrument(symbol)
    if not instrument:
        raise HTTPException(404, "找不到股票代號；請先更新全市場清單")
    database.add_to_watchlist(symbol, instrument["market"])
    return {"symbol": symbol, "watched": True}


@app.delete("/watchlist/{symbol}")
def watchlist_remove(symbol: str) -> dict[str, str | bool]:
    database.remove_from_watchlist(symbol)
    return {"symbol": symbol, "watched": False}


@app.put("/watchlist/{symbol}/position")
def watchlist_position(symbol: str, position: PositionUpdate) -> dict:
    if not database.update_watchlist_position(symbol, position.model_dump()):
        raise HTTPException(404, "股票尚未加入我的股票")
    return {"symbol": symbol, "status": "updated"}


@app.get("/portfolio/summary")
def get_portfolio_summary() -> dict:
    return portfolio_summary(database)


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


@app.get("/stocks/{symbol}/score")
def stock_score(symbol: str) -> dict:
    result = score_stock(database, symbol)
    if not result:
        raise HTTPException(404, "找不到股票評分資料。")
    return result


@app.post("/dividends/sync")
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


@app.post("/ownership/sync")
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


@app.post("/institutions/sync")
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


@app.post("/history/sync")
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


@app.post("/revenue/sync")
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


@app.post("/valuation/sync")
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


@app.post("/financials/sync")
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


@app.post("/financials/history/sync")
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


@app.post("/financials/history/batch")
def financial_history_batch(
    target_limit: int = Query(100, ge=10, le=200),
    batch_size: int = Query(10, ge=1, le=10),
    years: int = Query(5, ge=3, le=10), retry_failed: bool = False,
) -> dict:
    return run_fundamental_batch(database, target_limit, batch_size, years, retry_failed)


@app.get("/financials/history/batch/status")
def financial_history_batch_status(target_limit: int = Query(100, ge=10, le=200)) -> dict:
    return database.get_fundamental_sync_progress(target_limit)


@app.get("/stocks/{symbol}/valuation/history")
def stock_historical_valuation(symbol: str, series_limit: int = Query(250, ge=20, le=1500)) -> dict:
    result = get_historical_valuation(database, symbol, series_limit)
    if not result:
        raise HTTPException(404, "Historical valuation data is not yet available")
    return result


@app.post("/prices/history/batch")
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


@app.post("/screener/sync")
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
    return recommend_stocks(database, limit, min_completeness, profile)


@app.get("/market-context")
def market_context(refresh: bool = False) -> dict:
    return get_market_context(force=refresh)


@app.get("/popular-stocks")
def popular_stocks(limit: int = Query(12, ge=1, le=50)) -> list[dict]:
    return database.list_popular_stocks(limit)
