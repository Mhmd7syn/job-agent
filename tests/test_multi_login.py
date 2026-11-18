import os
import sys
from unittest.mock import MagicMock, patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.login import SUPPORTED_SITES, USER_DATA_DIR, multi_login, main as login_main


def test_supported_sites_registry():
    expected_sites = ["linkedin", "tanqeeb", "glassdoor", "bayt", "wuzzuf", "indeed", "whatsapp"]
    for site in expected_sites:
        assert site in SUPPORTED_SITES
        assert "url" in SUPPORTED_SITES[site]
        assert SUPPORTED_SITES[site]["url"].startswith("http")


def test_persistent_profile_directory():
    assert USER_DATA_DIR is not None
    assert "playwright_profile" in USER_DATA_DIR or os.getenv("EDGE_USER_DATA_DIR")


@patch("scripts.login.launch_persistent_browser")
@patch("scripts.login.sync_playwright")
@patch("scripts.login.wait_for_user_completion")
def test_multi_login_opens_tabs_without_clearing_profile(mock_wait, mock_pw, mock_launch):
    mock_context = MagicMock()
    mock_page = MagicMock()
    mock_context.pages = [mock_page]
    mock_context.new_page.return_value = MagicMock()
    mock_launch.return_value = mock_context

    # Run for a subset of sites
    multi_login(selected_keys=["linkedin", "tanqeeb"])

    assert mock_launch.called
    kwargs = mock_launch.call_args[1]
    assert kwargs["user_data_dir"] == USER_DATA_DIR
    assert kwargs["headless"] is False

    # Ensure context.clear_cookies() is never called
    assert not hasattr(mock_context, "clear_cookies") or not mock_context.clear_cookies.called

    # Ensure pages navigated to the target URLs
    assert mock_page.goto.called


@patch("scripts.login.multi_login")
def test_login_cli_filter(mock_multi_login):
    with patch("sys.argv", ["login.py", "linkedin"]):
        login_main()
        mock_multi_login.assert_called_with(selected_keys=["linkedin"])


def test_auth_login_endpoints():
    from fastapi.testclient import TestClient
    from web.app import app
    import web.routers.profile as profile_mod

    client = TestClient(app)

    # Initial status should be not running
    profile_mod.login_process = None
    res = client.get("/api/auth/login-status")
    assert res.status_code == 200
    assert res.json()["is_running"] is False

    # Mock subprocess.Popen for launch-login
    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 99999
        mock_popen.return_value = mock_proc

        res = client.post("/api/auth/launch-login", json={"sites": ["linkedin", "glassdoor"]})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "started"
        assert data["pid"] == 99999

        # Second launch should report already_running
        res_dup = client.post("/api/auth/launch-login", json={})
        assert res_dup.status_code == 200
        assert res_dup.json()["status"] == "already_running"

        # Status check while running
        res_status = client.get("/api/auth/login-status")
        assert res_status.status_code == 200
        assert res_status.json()["is_running"] is True
        assert res_status.json()["pid"] == 99999

        # Stop login endpoint
        res_stop = client.post("/api/auth/stop-login")
        assert res_stop.status_code == 200
        assert res_stop.json()["status"] == "stopped"
        assert mock_proc.terminate.called

    profile_mod.login_process = None

    # Test GET /api/auth/platforms
    res_platforms = client.get("/api/auth/platforms")
    assert res_platforms.status_code == 200
    pdata = res_platforms.json()
    assert "platforms" in pdata
    platforms = pdata["platforms"]
    assert "linkedin" in platforms
    assert "glassdoor" in platforms
    assert "tanqeeb" in platforms
    assert "bayt" in platforms
    assert "wuzzuf" in platforms
    assert "indeed" in platforms
    assert "whatsapp" in platforms
    for key, info in platforms.items():
        assert "logged_in" in info
        assert "status" in info


def test_check_platform_auth_status_unit():
    from core.auth_status import check_platform_auth_status
    status = check_platform_auth_status()
    assert isinstance(status, dict)
    assert "linkedin" in status
    assert status["linkedin"]["name"] == "LinkedIn"
    assert isinstance(status["linkedin"]["logged_in"], bool)


