from fastapi.testclient import TestClient

from app.main import app


def test_performance_page_discloses_t108_as_frozen_research_only() -> None:
    with TestClient(app) as client:
        page = client.get("/performance/")

    assert page.status_code == 200
    assert 'id="t108FrozenCandidate"' in page.text
    assert "目前最有希望的凍結研究候選" in page.text
    assert "前向 0／24 形成日" in page.text
    assert "不會進入正式推薦、排行榜或自動交易" in page.text
    assert "屬污染歷史" in page.text
    assert "+405.237%" in page.text
    assert "F04B325231C90AA37B34BAA32039A64C743A797FA7C32788B661C598C078D8BE" in page.text


def test_t108_website_card_preserves_the_frozen_rule() -> None:
    with TestClient(app) as client:
        page = client.get("/performance/").text

    assert "20日報酬 1／6、60日報酬 1／6、SMA60距離 1／3、20日波動率 1／3" in page
    assert "最多10檔、每檔5%、單一產業10%、總曝險50%" in page
    assert "下一官方交易日開盤" in page
    assert "至少24個新形成日且橫跨12個月" in page
