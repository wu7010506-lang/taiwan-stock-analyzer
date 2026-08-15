from app.providers import _get_twse_history_response


class FakeResponse:
    def __init__(self, status_code, url, location=None):
        self.status_code = status_code
        self.url = url
        self.headers = {"location": location} if location else {}

    @property
    def is_redirect(self):
        return 300 <= self.status_code < 400


class RedirectingClient:
    def __init__(self):
        origin = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20230901"
        target = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20230901&response=json"
        self.responses = [
            FakeResponse(307, origin, target),
            FakeResponse(200, target),
        ]
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_twse_history_follows_a_remaining_official_redirect():
    client = RedirectingClient()

    response = _get_twse_history_response(client, "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY")

    assert response.status_code == 200
    assert len(client.calls) == 2
    assert client.calls[0][1]["follow_redirects"] is True
    assert client.calls[1][1]["follow_redirects"] is True
