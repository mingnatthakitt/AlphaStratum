"""Auth middleware and /health tests.

The backend is deployed to a public hostname, so the governing property is:
unless a real secret is configured, NO request may reach an endpoint. These
tests pin that down, along with the explicit local-dev escape hatch.
"""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app, raise_server_exceptions=False)

PROTECTED = "/models/cache/stats"
REAL_PASSWORD = "s3cret-from-openssl-rand-base64-32"


def _configure(monkeypatch, password: str = REAL_PASSWORD):
    """A realistic deployed config: real password, no dev-mode escape."""
    monkeypatch.setenv("AUTH_PASSWORD", password)
    monkeypatch.delenv("AUTH_DEV_MODE", raising=False)


def _unconfigured(monkeypatch):
    """The misconfiguration that must not silently open the API."""
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("AUTH_DEV_MODE", raising=False)


# ── the core property ────────────────────────────────────────────────────────


def test_missing_password_fails_closed(monkeypatch):
    """No secret configured => 503, not 200. This is the regression that
    matters: the backend is on a public URL, so fail-open publishes it."""
    _unconfigured(monkeypatch)
    assert client.get(PROTECTED).status_code == 503


def test_empty_password_fails_closed(monkeypatch):
    """Render's `sync: false` creates an EMPTY string rather than leaving the
    var unset, so the empty case has to be handled separately."""
    _unconfigured(monkeypatch)
    monkeypatch.setenv("AUTH_PASSWORD", "")
    assert client.get(PROTECTED).status_code == 503


def test_whitespace_password_fails_closed(monkeypatch):
    _unconfigured(monkeypatch)
    monkeypatch.setenv("AUTH_PASSWORD", "   ")
    assert client.get(PROTECTED).status_code == 503


def test_unconfigured_ignores_any_supplied_key(monkeypatch):
    """A 503 must not be bypassable by guessing — there is nothing to guess."""
    _unconfigured(monkeypatch)
    assert client.get(f"{PROTECTED}?key=anything").status_code == 503
    assert client.get(PROTECTED, headers={"X-Auth-Key": "anything"}).status_code == 503


def test_unconfigured_blocks_writes_too(monkeypatch):
    """Fail-closed has to cover state-changing routes, not just GETs."""
    _unconfigured(monkeypatch)
    resp = client.post("/models/var", json={"positions": [{"symbol": "AAPL", "shares": 1, "avgCost": 1}]})
    assert resp.status_code == 503


# ── the example-file placeholder ─────────────────────────────────────────────


def test_placeholder_password_is_rejected(monkeypatch):
    """Someone who copies .env.example to Render gets a secret that is public
    in this repo. It must be treated as no secret at all, not as a valid one."""
    _unconfigured(monkeypatch)
    monkeypatch.setenv("AUTH_PASSWORD", "change_me_to_a_strong_random_string")
    assert client.get(PROTECTED).status_code == 503
    # ...and the placeholder itself does not open the door either.
    assert client.get(f"{PROTECTED}?key=change_me_to_a_strong_random_string").status_code == 503


def test_placeholder_rejected_case_insensitively(monkeypatch):
    _unconfigured(monkeypatch)
    monkeypatch.setenv("AUTH_PASSWORD", "CHANGE_ME_TO_A_STRONG_RANDOM_STRING")
    assert client.get(PROTECTED).status_code == 503


def test_placeholder_does_not_mask_dev_mode(monkeypatch):
    """Setting a placeholder is not a way to request unauthenticated access."""
    _unconfigured(monkeypatch)
    monkeypatch.setenv("AUTH_PASSWORD", "changeme")
    assert client.get(PROTECTED).status_code == 503


# ── explicit dev mode ────────────────────────────────────────────────────────


def test_dev_mode_opens_the_api(monkeypatch):
    """The one sanctioned way to run without a secret, for localhost work."""
    _unconfigured(monkeypatch)
    monkeypatch.setenv("AUTH_DEV_MODE", "1")
    assert client.get(PROTECTED).status_code == 200


def test_dev_mode_ignored_when_password_configured(monkeypatch):
    """With a real password set, dev mode must not weaken it."""
    _configure(monkeypatch)
    monkeypatch.setenv("AUTH_DEV_MODE", "1")
    assert client.get(PROTECTED).status_code == 401
    assert client.get(f"{PROTECTED}?key={REAL_PASSWORD}").status_code == 200


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_dev_mode_truthy_spellings(monkeypatch, value):
    _unconfigured(monkeypatch)
    monkeypatch.setenv("AUTH_DEV_MODE", value)
    assert client.get(PROTECTED).status_code == 200


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "maybe"])
def test_dev_mode_falsy_spellings_still_fail_closed(monkeypatch, value):
    """A typo in the flag must not read as truthy — the safe direction."""
    _unconfigured(monkeypatch)
    monkeypatch.setenv("AUTH_DEV_MODE", value)
    assert client.get(PROTECTED).status_code == 503


def test_legacy_auth_required_var_does_not_reopen(monkeypatch):
    """AUTH_REQUIRED was the old opt-in-to-secure flag and is gone. If a stale
    copy is still in the environment it must not re-enable fail-open."""
    _unconfigured(monkeypatch)
    monkeypatch.setenv("AUTH_REQUIRED", "1")
    assert client.get(PROTECTED).status_code == 503


# ── credentials ──────────────────────────────────────────────────────────────


def test_401_without_key(monkeypatch):
    _configure(monkeypatch)
    assert client.get(PROTECTED).status_code == 401


def test_401_wrong_key(monkeypatch):
    _configure(monkeypatch)
    assert client.get(f"{PROTECTED}?key=wrong").status_code == 401


def test_200_with_correct_key(monkeypatch):
    _configure(monkeypatch)
    assert client.get(f"{PROTECTED}?key={REAL_PASSWORD}").status_code == 200


def test_200_with_correct_header_key(monkeypatch):
    """The header is what the app's own proxy sends."""
    _configure(monkeypatch)
    assert client.get(PROTECTED, headers={"X-Auth-Key": REAL_PASSWORD}).status_code == 200


def test_401_empty_key_param(monkeypatch):
    _configure(monkeypatch)
    assert client.get(f"{PROTECTED}?key=").status_code == 401


def test_401_wrong_header_key(monkeypatch):
    _configure(monkeypatch)
    assert client.get(PROTECTED, headers={"X-Auth-Key": "wrong"}).status_code == 401


def test_header_takes_precedence_over_query(monkeypatch):
    """A correct header must win even when a wrong query key is also present."""
    _configure(monkeypatch)
    resp = client.get(f"{PROTECTED}?key=wrong", headers={"X-Auth-Key": REAL_PASSWORD})
    assert resp.status_code == 200


def test_key_comparison_is_case_sensitive(monkeypatch):
    _configure(monkeypatch)
    assert client.get(PROTECTED, headers={"X-Auth-Key": REAL_PASSWORD.upper()}).status_code == 401


# ── brute-force throttle ─────────────────────────────────────────────────────


def test_repeated_failures_are_throttled(monkeypatch):
    """A single shared secret on a public URL is otherwise guessable without
    limit. After the threshold, answer 429 instead of 401."""
    _configure(monkeypatch)
    limit = main._AUTH_FAIL_LIMIT
    for _ in range(limit):
        assert client.get(f"{PROTECTED}?key=wrong").status_code == 401
    throttled = client.get(f"{PROTECTED}?key=wrong")
    assert throttled.status_code == 429
    assert "Retry-After" in throttled.headers


def test_correct_key_also_blocked_while_throttled(monkeypatch):
    """Otherwise the throttle is a DoS: an attacker locks out the real client.
    The window is short and bounded, which is the deliberate trade-off."""
    _configure(monkeypatch)
    for _ in range(main._AUTH_FAIL_LIMIT):
        client.get(f"{PROTECTED}?key=wrong")
    assert client.get(f"{PROTECTED}?key={REAL_PASSWORD}").status_code == 429


def test_success_clears_the_failure_count(monkeypatch):
    """A client that mistypes then corrects itself is not penalised."""
    _configure(monkeypatch)
    for _ in range(main._AUTH_FAIL_LIMIT - 1):
        client.get(f"{PROTECTED}?key=wrong")
    assert client.get(f"{PROTECTED}?key={REAL_PASSWORD}").status_code == 200
    assert client.get(f"{PROTECTED}?key=wrong").status_code == 401


def test_expired_failures_do_not_throttle(monkeypatch):
    """Failures outside the window are not counted."""
    _configure(monkeypatch)
    main._fail_counts["testclient"] = [
        main.time.monotonic() - main._AUTH_FAIL_WINDOW_S - 60
    ] * (main._AUTH_FAIL_LIMIT + 5)
    assert client.get(f"{PROTECTED}?key={REAL_PASSWORD}").status_code == 200


def test_failure_table_stays_bounded(monkeypatch):
    """A spray of distinct source addresses must not grow the dict forever."""
    _configure(monkeypatch)
    now = main.time.monotonic()
    main._fail_counts.update(
        (f"10.0.{i // 256}.{i % 256}", [now]) for i in range(20_000)
    )
    main._fail_counts["1.2.3.4"] = [now] * (main._AUTH_FAIL_LIMIT + 5)
    assert client.get(f"{PROTECTED}?key=wrong").status_code in (401, 429)
    assert len(main._fail_counts) <= main._MAX_TRACKED_CLIENTS


# ── public surface ───────────────────────────────────────────────────────────


def test_health_is_public(monkeypatch):
    """Render's health check has no credential; it must keep working."""
    _unconfigured(monkeypatch)
    assert client.get("/health").status_code == 200


def test_health_does_not_leak_auth_posture(monkeypatch):
    """/health is the one endpoint an anonymous caller can read. It must not
    report whether a credential is configured — that is a free open/closed
    oracle for anyone scanning for exposed hosts."""
    _configure(monkeypatch)
    body = client.get("/health").json()
    assert set(body) == {"status", "database"}
    # The same response shape whether or not auth is set up, so the body
    # itself carries no signal.
    _unconfigured(monkeypatch)
    assert client.get("/health").json() == body


def test_root_requires_auth(monkeypatch):
    """`/` used to be public. It is not needed by the health check, so it
    should not be a free fingerprinting endpoint."""
    _configure(monkeypatch)
    assert client.get("/").status_code == 401
    assert client.get("/", headers={"X-Auth-Key": REAL_PASSWORD}).status_code == 200


def test_root_still_reachable_in_dev_mode(monkeypatch):
    _unconfigured(monkeypatch)
    monkeypatch.setenv("AUTH_DEV_MODE", "1")
    assert client.get("/").status_code == 200


def test_health_reports_database_status(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    body = client.get("/health").json()
    assert body["database"] == "unconfigured"
    assert body["status"] == "healthy"


def test_documented_paths_all_require_the_key(monkeypatch):
    """Spot-check that the routers really are behind the middleware — a router
    included before the middleware would be a hole in the whole scheme."""
    _configure(monkeypatch)
    for path in (
        "/models/regime/AAPL",
        "/fetch/ticker/AAPL",
        "/rag/chat",
        "/portfolio/holdings",
        "/",
    ):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers={"X-Auth-Key": REAL_PASSWORD}).status_code != 401, path
