# tests/test_network_middleware.py
from fastapi.testclient import TestClient
from services import network_share as ns


def _app_with_pin(pin="123456"):
    from main import app
    app.state.network_share = ns.ShareState(enabled=True, share_port=3901, pin=pin, lan_addresses=["10.0.0.9"])
    return app


def teardown_function():
    from main import app
    app.state.network_share = ns.ShareState()  # reset → middleware inert


def test_inert_when_no_pin():
    from main import app
    app.state.network_share = ns.ShareState()  # no pin
    c = TestClient(app, client=("10.0.0.5", 1))   # non-loopback
    assert c.get("/health").status_code == 200


def test_loopback_bypasses_pin():
    c = TestClient(_app_with_pin(), client=("127.0.0.1", 1))
    assert c.get("/system/info").status_code == 200  # loopback → ok


def test_non_loopback_without_pin_401_on_api():
    c = TestClient(_app_with_pin(), client=("10.0.0.5", 1))
    r = c.get("/api/voices")  # any non-shell API path
    assert r.status_code in (401,)  # PIN required


def test_non_loopback_with_valid_pin_passes():
    c = TestClient(_app_with_pin("654321"), client=("10.0.0.5", 1))
    r = c.get("/api/voices", headers={"X-OmniVoice-Pin": "654321"})
    assert r.status_code != 401


def test_spa_shell_served_without_pin():
    c = TestClient(_app_with_pin(), client=("10.0.0.5", 1))
    assert c.get("/health").status_code == 200


def test_middleware_is_plain_asgi_not_buffering():
    # A pure ASGI middleware (class with __call__(scope, receive, send)) does
    # NOT subclass starlette's BaseHTTPMiddleware, which buffers streaming
    # responses. Guard against a regression back to the buffering base class.
    from starlette.middleware.base import BaseHTTPMiddleware
    from main import NetworkAccessMiddleware

    assert not issubclass(NetworkAccessMiddleware, BaseHTTPMiddleware)
    assert callable(getattr(NetworkAccessMiddleware, "__call__", None))


def test_streaming_response_passes_through_with_valid_pin():
    # A PIN'd, non-loopback request to a StreamingResponse route must stream
    # chunk-by-chunk, not be collected into one buffered body. We mount a tiny
    # streaming route on a fresh app wrapped with the real middleware and
    # confirm the response arrives chunked (multiple yields concatenated).
    from fastapi import FastAPI
    from starlette.responses import StreamingResponse
    from main import NetworkAccessMiddleware

    app = FastAPI()
    app.add_middleware(NetworkAccessMiddleware)
    app.state.network_share = ns.ShareState(
        enabled=True, share_port=3901, pin="777888", lan_addresses=["10.0.0.9"]
    )

    @app.get("/stream")
    def stream():
        def gen():
            for i in range(5):
                yield f"chunk-{i}\n"

        return StreamingResponse(gen(), media_type="text/plain")

    c = TestClient(app, client=("10.0.0.5", 1))
    # Without the PIN, the stream route is gated.
    assert c.get("/stream").status_code == 401
    # With the PIN, it streams the full body through the ASGI middleware.
    r = c.get("/stream", headers={"X-OmniVoice-Pin": "777888"})
    assert r.status_code == 200
    body = r.text
    for i in range(5):
        assert f"chunk-{i}" in body
    # Streaming responses carry no precomputed Content-Length — a buffering
    # middleware would re-materialise the body and set one.
    assert "content-length" not in {k.lower() for k in r.headers}


def test_valid_pin_sets_cookie_via_asgi():
    from fastapi import FastAPI
    from main import NetworkAccessMiddleware

    app = FastAPI()
    app.add_middleware(NetworkAccessMiddleware)
    app.state.network_share = ns.ShareState(
        enabled=True, share_port=3901, pin="424242", lan_addresses=["10.0.0.9"]
    )

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    c = TestClient(app, client=("10.0.0.5", 1))
    r = c.get("/api/ping", headers={"X-OmniVoice-Pin": "424242"})
    assert r.status_code == 200
    # The ASGI send-wrapper injects Set-Cookie on the first valid-PIN request
    # (when the cookie isn't already present).
    set_cookie = r.headers.get("set-cookie", "")
    assert "ov_pin=424242" in set_cookie
