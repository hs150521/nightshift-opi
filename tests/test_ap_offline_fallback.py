from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ap_start_has_bounded_sta_wait_and_offline_fallback() -> None:
    script = (ROOT / "deploy" / "scripts" / "nightshift-ap-start").read_text()

    assert "readonly STA_WAIT_SECONDS=" in script
    assert 'if [ "$SECONDS" -ge "$STA_WAIT_DEADLINE" ]; then' in script
    assert "starting standalone AP" in script
    assert 'if [ "$STA_CONNECTED" = true ]; then' in script
