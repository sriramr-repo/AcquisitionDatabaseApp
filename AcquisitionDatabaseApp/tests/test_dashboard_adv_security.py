from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_new_dashboard_surfaces_are_behind_middleware():
    middleware = (ROOT / "web" / "middleware.ts").read_text()
    for route in ("/data-dictionary/:path*", "/api/adv/:path*", "/api/seller-intent/:path*"):
        assert route in middleware


def test_write_routes_recheck_authentication():
    for route in (
        ROOT / "web" / "app" / "api" / "adv" / "[firmId]" / "refresh" / "route.ts",
        ROOT / "web" / "app" / "api" / "seller-intent" / "[firmId]" / "route.ts",
    ):
        content = route.read_text()
        assert "await auth()" in content
        assert 'status: 401' in content
