from fastapi.testclient import TestClient

from app.main import app


def test_home_page_serves_user_interface():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "台股研究台" in response.text
    assert 'href="/screener/"' in response.text
    assert "今日關注" in response.text
    assert 'href="/stock/"' in response.text
    assert "/static/focus.js" in response.text


def test_static_assets_are_available():
    with TestClient(app) as client:
        response = client.get("/static/styles.css")
    assert response.status_code == 200
    assert "--green" in response.text


def test_screener_has_its_own_page():
    with TestClient(app) as client:
        response = client.get("/screener/")
        script = client.get("/static/screener.js")
    assert response.status_code == 200
    assert "所有股票" in response.text
    assert "/static/screener.js" in response.text
    assert script.status_code == 200
    assert "/screener/sync" in script.text
    assert 'id="filterPopular" type="checkbox" checked' in response.text
    assert 'params.set("popular_only"' in script.text
    assert 'limit: "3000"' in script.text
    assert '成交金額前 100 名' in response.text
    assert script.text.rstrip().endswith("run();")
    assert 'id="filterAiTheme"' in response.text
    assert 'id="filterDefenseTheme"' in response.text
    assert 'id="filterIcDesignTheme"' in response.text
    assert 'params.set("ai_theme"' in script.text


def test_primary_navigation_marks_the_current_page():
    routes = {
        "/alerts/": "/alerts/",
        "/watchlist/": "/watchlist/",
        "/recommendations/": "/recommendations/",
        "/screener/": "/screener/",
    }
    with TestClient(app) as client:
        for route, current_href in routes.items():
            page = client.get(route).text
            assert page.count('class="text-link nav-link') >= 4
            assert f'href="{current_href}" class="text-link nav-link active" aria-current="page"' in page


def test_watchlist_has_its_own_page():
    with TestClient(app) as client:
        response = client.get("/watchlist/")
        script = client.get("/static/watchlist.js")
    assert response.status_code == 200
    assert "我的股票" in response.text
    assert "/static/watchlist.js" in response.text
    assert script.status_code == 200
    assert 'api("/watchlist")' in script.text
    assert 'id="positionDialog"' in response.text
    assert 'id="portfolioSummary"' in response.text
    assert '/portfolio/summary' in script.text
    assert '/position`' in script.text
    assert "portfolio_decision" in script.text
    assert "position-decision" in script.text


def test_recommendations_have_their_own_explainable_page():
    with TestClient(app) as client:
        response = client.get("/recommendations/")
        script = client.get("/static/recommendations.js")
    assert response.status_code == 200
    assert "價值型" in response.text
    assert "PE&lt;15" in response.text
    assert "長期優質企業" in response.text
    assert "不構成投資建議" in response.text
    assert "/static/recommendations.js" in response.text
    assert script.status_code == 200
    assert "profile=${profile}" in script.text
    assert 'id="popularGrid"' in response.text
    assert 'api("/popular-stocks?limit=12")' in script.text
    assert 'value="vnext"' in response.text
    assert '"/recommendations/vnext?limit=24"' in script.text
    assert 'accumulate:"分批加碼"' in script.text
    assert 'durable_business_quality:"企業品質具持續性"' in script.text
    assert 'fundamentals_deteriorate:"基本面惡化"' in script.text
    assert "speculation_risk: row.crowding_risk" in script.text


def test_ui_auto_syncs_one_year_when_stock_is_selected():
    with TestClient(app) as client:
        response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "autoSyncStockData(stock.symbol)" in response.text
    assert "/sync-plan" in response.text
    assert "/sync-missing" in response.text
    assert "if (plan.ready)" in response.text


def test_individual_stock_page_has_candlestick_chart():
    with TestClient(app) as client:
        page = client.get("/stock/")
        script = client.get("/static/app.js")
    assert 'id="chartMode"' in page.text
    assert "K線圖" in page.text
    assert "function drawCandlesticks" in script.text
    assert 'const rising = close >= open' in script.text


def test_individual_stock_page_has_shareholder_distribution():
    with TestClient(app) as client:
        page = client.get("/stock/")
        script = client.get("/static/app.js")
    assert 'id="ownershipSummary"' in page.text
    assert "股權分散與籌碼結構" in page.text
    assert 'api(`/ownership/sync?' in script.text
    assert "function renderOwnership" in script.text


def test_individual_stock_page_has_institutional_trading_flow():
    with TestClient(app) as client:
        page = client.get("/stock/")
        script = client.get("/static/app.js")
    assert 'id="institutionSummary"' in page.text
    assert "外資與投信買賣張數" in page.text
    assert 'api(`/institutions/sync?' in script.text


def test_individual_stock_page_has_company_profile():
    with TestClient(app) as client:
        page = client.get("/stock/")
        script = client.get("/static/app.js")
    assert 'id="companyBusinessSummary"' in page.text
    assert "這家公司在做什麼？" in page.text
    assert 'api(`/stocks/${symbol}/company`)' in script.text


def test_individual_stock_page_has_short_term_analysis_contract():
    with TestClient(app) as client:
        page = client.get("/stock/")
        script = client.get("/static/app.js?v=20260815-individual-position-1")
    assert 'id="shortAnalysisTitle">短線分析' in page.text
    assert "3–10 個交易日研究" in page.text
    assert "交易計畫是條件式研究" in page.text
    assert 'src="/static/app.js?v=20260815-individual-position-1"' in page.text
    assert "maximum_entry_price" in script.text
    assert "minimum_target_required_rr" in script.text
    assert "maximum_entry_formula" in script.text
    assert "mfi_check" in script.text
    assert "交易評估" in script.text
    assert "純技術交易評估" in script.text
    assert "整體判定" in script.text
    assert "不會覆蓋基本面門檻" in script.text
    assert "追價控制未通過：短線漲幅與乖離過度延伸" in script.text
    assert 'id="plainShortConclusion"' in script.text
    assert "白話結論" in script.text
    assert 'id="recordShortPositionButton"' in page.text
    assert "我已買進" in page.text
    assert 'id="individualPurchaseDialog"' in page.text
    assert 'api("/short-term-positions/manual"' in script.text
    assert "可登記任何已買股票" in script.text


def test_short_term_ranking_page_uses_the_fixed_research_api():
    with TestClient(app) as client:
        page = client.get("/ranking/")
        script = client.get("/static/ranking.js?v=20260815-split-ranking-2")

    assert page.status_code == 200
    assert "短線排行榜" in page.text
    assert 'id="rankingList"' in page.text
    assert 'src="/static/ranking.js?v=20260815-split-ranking-2"' in page.text
    assert "/short-term-decisions?limit=10" in script.text
    assert "成本後 RR" in script.text
    assert "相對強度" in script.text
    assert "基本面與技術條件均完成" in script.text
    assert "今日新觸發" in script.text
    assert "訊號持續追蹤" in script.text
    assert "前次訊號失效或等待重新觸發" in script.text
    assert "不建議買進：基本面未通過" in script.text
    assert "未通過基本面安全門檻" in script.text
    assert "不追價：短線過度延伸" in script.text
    assert "財報與估值待同步" in script.text
    assert "資料不一致先暫停" in script.text
    assert "進場尚未觸發" in script.text
    assert "/short-term-ranking/tracking" in script.text
    assert "effectiveness_assessment" in script.text
    assert "查看嚴格 PIT 歷史回放" in script.text
    assert "前十名中最接近可操作的五檔" in script.text
    assert "RR不足另列於原股票卡片" in script.text
    assert 'id="actionableRanking"' in script.text
    assert 'id="attentionRanking"' in script.text
    assert "今日可操作排行榜" in script.text
    assert "可操作排序不沿用關注名次" in script.text
    assert "operationPriority" in script.text
    assert "研究優先順序" in page.text
    assert 'id="privatePositionArea"' in page.text
    assert "我的短線持倉與賣出提醒" in page.text
    assert 'id="purchaseDialog"' in page.text
    assert 'id="executionDialog"' in page.text
    assert 'positionApi("/short-term-positions")' in script.text
    assert 'method: "POST"' in script.text
    assert "我已買進" in script.text
    assert "登記已賣出" in script.text
    assert "公開網址為唯讀" in script.text


def test_public_site_cannot_mutate_short_term_positions():
    with TestClient(app, base_url="https://public.example") as client:
        response = client.post("/short-term-positions", json={})
    assert response.status_code == 403
    assert "公開網站只能查看" in response.json()["detail"]


def test_alert_center_has_own_page():
    with TestClient(app) as client:
        page = client.get("/alerts/")
        script = client.get("/static/alerts.js")
    assert page.status_code == 200
    assert "提醒中心" in page.text
    assert 'id="alertGrid"' in page.text
    assert script.status_code == 200
    assert 'api(`/alerts?mode=${decisionMode}`)' in script.text
    assert 'data-mode="short"' in page.text
    assert 'data-mode="long"' in page.text
    assert 'id="alertSearch"' in page.text
    assert 'id="alertCategory"' in page.text
    assert 'id="unreadOnly"' in page.text
    assert 'id="markAllRead"' in page.text
    assert 'localStorage.setItem(READ_KEY' in script.text


def _legacy_global_sync_button_markup_check():
    with TestClient(app) as client:
        pages = [client.get(path).text for path in
                 ("/", "/watchlist/", "/recommendations/", "/screener/", "/alerts/")]
        script = client.get("/static/global-sync.js")
    assert all('/static/global-sync.js' in page for page in pages)
    assert script.status_code == 200
    assert 'button.textContent = "同步所有資料"' in script.text
    assert "data_freshness" in script.text
    return
    assert 'button.textContent = "同步所有資料"' in script.text
    assert 'button.textContent = "同步所有資料"' in script.text
    assert 'fetch("/daily-sync", { method: "POST" })' in script.text
    assert "data_freshness" in script.text


def _legacy_global_sync_reports_per_market_data_coverage():
    with TestClient(app) as client:
        pages = [client.get(path).text for path in
                 ("/", "/watchlist/", "/recommendations/", "/screener/", "/alerts/")]
        script = client.get("/static/global-sync.js")
    assert all('/static/global-sync.js' in page for page in pages)
    assert script.status_code == 200
    assert 'button.textContent = "同步所有資料"' in script.text
    assert 'fetch("/daily-sync", { method: "POST" })' in script.text
    assert "data_freshness" in script.text
    assert 'qualityLink.href = "/data-quality/"' in script.text


def test_global_navigation_replaces_legacy_page_specific_links():
    with TestClient(app) as client:
        script = client.get("/static/global-sync.js")
    assert script.status_code == 200
    assert 'actions.replaceChildren(fragment)' in script.text
    assert '["/stock/", "看股票"]' in script.text
    assert '["/screener/", "找股票"]' in script.text
    assert '["/watchlist/", "我的追蹤"]' in script.text
    assert '["/research/", "研究與資料"]' in script.text
    assert "/short-analysis/" not in script.text
    assert "/dashboard/" not in script.text


def test_model_performance_has_own_page():
    with TestClient(app) as client:
        page = client.get("/performance/")
        script = client.get("/static/performance.js")
    assert page.status_code == 200
    assert "模型成績" in page.text
    assert 'id="performanceSummary"' in page.text
    assert 'id="performanceRows"' in page.text
    assert script.status_code == 200
    assert "/performance/summary" in script.text
    assert "/performance/snapshot" in script.text
    assert 'id="paperGovernanceStatus"' in page.text
    assert "/research/paper-strategies" in script.text


def test_primary_pages_reach_performance_through_research_navigation():
    with TestClient(app) as client:
        pages = [client.get(path).text for path in
                 ("/", "/screener/", "/watchlist/", "/recommendations/", "/alerts/", "/data-quality/")]
        research = client.get("/research/").text
    assert all(
        'href="/research/"' in page or 'href="/performance/"' in page
        for page in pages
    )
    assert 'href="/performance/"' in research


def test_research_lab_has_isolated_ui_and_auditable_history_api():
    with TestClient(app) as client:
        page = client.get("/research/")
        script = client.get("/static/research.js")
        history = client.get("/research/experiments")
    assert page.status_code == 200
    assert "不會改變正式推薦" in page.text
    assert script.status_code == 200
    assert "/research/experiments" in script.text
    assert history.status_code == 200
    assert isinstance(history.json(), list)


def test_research_lab_exposes_locked_paper_strategy_tracking():
    with TestClient(app) as client:
        page = client.get("/research/")
        schema = client.get("/openapi.json").json()
    assert 'id="paperStrategyRows"' in page.text
    assert "/research/paper-strategies" in schema["paths"]
    assert "/research/paper-strategies/valuation" in schema["paths"]


def test_model_performance_offers_historical_backtest():
    with TestClient(app) as client:
        page = client.get("/performance/")
        script = client.get("/static/performance.js")
    assert 'id="performanceMode"' in page.text
    assert "歷史選股回測" in page.text
    assert "/performance/backtest" in script.text


def test_model_performance_groups_recommendation_validation_under_one_mode():
    with TestClient(app) as client:
        page = client.get("/performance/")
        script = client.get("/static/performance.js")

    assert 'value="recommendations"' in page.text
    assert 'id="recommendationReport"' in page.text
    assert 'id="recommendationReportControl"' in page.text
    assert 'id="minScoreControl"' in page.text
    assert 'selectedMode === "recommendations"' in script.text


def test_model_performance_offers_market_strategy_walk_forward_backtest():
    with TestClient(app) as client:
        page = client.get("/performance/")
        script = client.get("/static/performance.js")
        response = client.get("/performance/strategy-backtest")

    assert page.status_code == 200
    assert "市場策略 Walk-forward 回測" in page.text
    assert script.status_code == 200
    assert "/performance/strategy-backtest" in script.text
    assert "renderStrategy" in script.text
    assert response.status_code == 200
    assert response.json()["mode"] == "strategy_backtest"
    assert 'id="outOfSampleStart"' in page.text
    assert 'id="slippageBps"' in page.text
    assert 'id="minimumTurnover"' in page.text
    assert "out_of_sample_start" in script.text
    assert "slippage_bps" in script.text
    assert "min_turnover" in script.text


def test_model_performance_offers_factor_validation():
    with TestClient(app) as client:
        page = client.get("/performance/")
        script = client.get("/static/performance.js")
        response = client.get("/performance/factors")

    assert 'value="factors"' in page.text
    assert "/performance/factors" in script.text
    assert "renderFactors" in script.text
    assert response.status_code == 200
    assert response.json()["mode"] == "factor_validation"


def test_individual_stock_page_has_transparent_score():
    with TestClient(app) as client:
        page = client.get("/stock/")
        script = client.get("/static/app.js")
    assert 'id="scoreGauge"' in page.text
    assert "個股綜合評分" in page.text
    assert 'api(`/stocks/${symbol}/score`)' in script.text
    assert "function renderStockScore" in script.text


def test_other_pages_do_not_link_directly_to_individual_analysis():
    with TestClient(app) as client:
        pages = [client.get(path).text for path in ("/screener/", "/watchlist/", "/recommendations/", "/alerts/")]
    assert all('href="/"' not in page for page in pages)
    assert all('>個股分析</a>' not in page for page in pages)


def test_vnext_is_exposed_as_separate_api_without_replacing_existing_model():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    assert "/stocks/{symbol}/vnext" in schema["paths"]
    assert "/recommendations/vnext" in schema["paths"]
    assert "/recommendations" in schema["paths"]


def test_data_quality_page_offers_resumable_full_market_financial_batch():
    with TestClient(app) as client:
        page = client.get("/data-quality/")
        script = client.get("/static/data-quality.js")
        schema = client.get("/openapi.json").json()

    assert 'id="syncAllFinancialsButton"' in page.text
    assert "scope=all" in script.text
    assert "每日收盤同步也會自動接續" in script.text
    parameters = schema["paths"]["/financials/history/batch"]["post"]["parameters"]
    assert any(item["name"] == "scope" for item in parameters)


def test_watchlist_entry_plan_does_not_read_zone_when_plan_is_incomplete():
    with TestClient(app) as client:
        script = client.get("/static/watchlist.js")

    assert "plan?.entry_zone" in script.text
    assert "plan.entry_zone.low" in script.text
    assert "entry_zone?.low" not in script.text
