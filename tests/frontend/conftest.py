"""Browser tests: start the app on a spare port with its own temporary database,
then drive real pages with Playwright (Chromium in CI; set PW_CHANNEL=msedge or
PW_CHANNEL=chrome to use an installed browser locally)."""
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -r requirements-dev.txt to run browser tests")
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url():
    port = _free_port()
    env = {**os.environ, "LANGTUTOR_DB": str(Path(tempfile.mkdtemp()) / "ui.db"), "ADMIN_PASSWORD": "ui-test-admin"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "/api/version", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("app server did not start")
    yield url
    proc.terminate()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel=os.getenv("PW_CHANNEL") or None)
        yield b
        b.close()


@pytest.fixture
def page_factory(browser, base_url):
    """open(path, logged_in=False, mobile=False) -> a page with Mila's voice muted."""
    contexts = []

    def open_page(path="/", logged_in=False, mobile=False):
        size = {"width": 390, "height": 844} if mobile else {"width": 1280, "height": 900}
        ctx = browser.new_context(viewport=size, is_mobile=mobile, has_touch=mobile)
        contexts.append(ctx)
        if logged_in:
            name = "ui_" + uuid.uuid4().hex[:8]
            ctx.request.post(base_url + "/auth/signup", data={"username": name, "password": "secret123"})
            ctx.request.post(base_url + "/auth/login", data={"username": name, "password": "secret123"})
            ctx.request.post(base_url + "/onboarding/submit", data={"reason": "fun", "goal": "Fun", "level": "Beginner", "daily_goal": 10})
            ctx.request.post(base_url + "/tour/done")
        ctx.add_init_script("localStorage.setItem('tutorMuted', '1')")
        page = ctx.new_page()
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.goto(base_url + path)
        page.wait_for_load_state("networkidle")
        page.evaluate("document.querySelectorAll('.popup-overlay, #onboardingModal, #recapModal').forEach(e => e.classList.remove('active'))")
        return page

    yield open_page
    for ctx in contexts:
        ctx.close()
