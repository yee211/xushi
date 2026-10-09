from pathlib import Path

from app import paths


def test_local_release_assets_match_release_script():
    from scripts import release
    assert paths.DOWNLOADS_DIR == Path(release.STATIC_DOWNLOAD_DIR)
    assert paths.FRONTEND_DIST == Path(release.FRONTEND_DIST)
    assert paths.VERSION_FILE == Path(release.ROOT_DIR) / 'data' / 'app_version.json'


def test_container_layout_and_explicit_override(tmp_path, monkeypatch):
    monkeypatch.delenv('XUSHI_ASSET_ROOT', raising=False)
    monkeypatch.setattr(paths, 'SERVER_ROOT', tmp_path / 'app')
    assert paths.asset_root() == tmp_path / 'app'
    monkeypatch.setenv('XUSHI_ASSET_ROOT', str(tmp_path / 'assets'))
    assert paths.asset_root() == tmp_path / 'assets'
