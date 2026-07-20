from fastapi.testclient import TestClient

from app.main import app


def test_home_page_serves_user_interface():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "台股研究台" in response.text
    assert 'href="/screener/"' in response.text
    assert "前往所有股票" in response.text
    assert "/static/app.js" in response.text


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


def test_recommendations_have_their_own_explainable_page():
    with TestClient(app) as client:
        response = client.get("/recommendations/")
        script = client.get("/static/recommendations.js")
    assert response.status_code == 200
    assert "價值型" in response.text
    assert "PE&lt;15" in response.text
    assert "不構成投資建議" in response.text
    assert "/static/recommendations.js" in response.text
    assert script.status_code == 200
    assert "profile=${profile}" in script.text
    assert 'id="popularGrid"' in response.text
    assert 'api("/popular-stocks?limit=12")' in script.text


def test_ui_auto_syncs_one_year_when_stock_is_selected():
    with TestClient(app) as client:
        response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "autoSyncStockData(stock.symbol)" in response.text
    assert 'setFullYear(startDate.getFullYear() - 1)' in response.text
    assert 'api(`/history/sync?' in response.text
    assert 'api(`/revenue/sync?' in response.text
    assert 'api(`/valuation/sync?' in response.text
    assert 'api(`/financials/sync?' in response.text


def test_individual_stock_page_has_candlestick_chart():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/app.js")
    assert 'id="chartMode"' in page.text
    assert "K線圖" in page.text
    assert "function drawCandlesticks" in script.text
    assert 'const rising = close >= open' in script.text


def test_individual_stock_page_has_shareholder_distribution():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/app.js")
    assert 'id="ownershipSummary"' in page.text
    assert "股權分散與籌碼結構" in page.text
    assert 'api(`/ownership/sync?' in script.text
    assert "function renderOwnership" in script.text


def test_individual_stock_page_has_institutional_trading_flow():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/app.js")
    assert 'id="institutionSummary"' in page.text
    assert "外資與投信買賣張數" in page.text
    assert 'api(`/institutions/sync?' in script.text


def test_individual_stock_page_has_company_profile():
    with TestClient(app) as client:
        page = client.get("/")
        script = client.get("/static/app.js")
    assert 'id="companyBusinessSummary"' in page.text
    assert "這家公司在做什麼？" in page.text
    assert 'api(`/stocks/${symbol}/company`)' in script.text


def test_alert_center_has_own_page():
    with TestClient(app) as client:
        page = client.get("/alerts/")
        script = client.get("/static/alerts.js")
    assert page.status_code == 200
    assert "提醒中心" in page.text
    assert 'id="alertGrid"' in page.text
    assert script.status_code == 200
    assert 'api("/alerts")' in script.text
    assert 'id="alertSearch"' in page.text
    assert 'id="alertCategory"' in page.text
    assert 'id="unreadOnly"' in page.text
    assert 'id="markAllRead"' in page.text
    assert 'localStorage.setItem(READ_KEY' in script.text


def test_individual_stock_page_has_transparent_score():
    with TestClient(app) as client:
        page = client.get("/")
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
