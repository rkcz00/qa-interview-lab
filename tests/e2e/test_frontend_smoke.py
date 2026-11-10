from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright


def test_built_frontend_renders_start_page():
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    assert (dist / "index.html").is_file(), "Run npm run build in frontend before this test"

    handler = partial(SimpleHTTPRequestHandler, directory=dist)
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    response = page.goto(f"http://127.0.0.1:{server.server_port}/", timeout=10_000)
                    assert response is not None and response.status == 200
                    heading = page.get_by_role("heading", name="QA Interview Lab", exact=True)
                    expect(heading).to_be_visible()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            thread.join()
