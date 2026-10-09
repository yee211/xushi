"""Resolve shared release assets in local-checkout and container layouts."""
import os
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parent.parent


def asset_root():
    override = os.getenv('XUSHI_ASSET_ROOT', '').strip()
    if override:
        return Path(override).expanduser().resolve()
    # Local checkout stores release assets beside server/. Container copies app/ directly.
    return SERVER_ROOT.parent if (SERVER_ROOT.parent / 'server' / 'app').is_dir() else SERVER_ROOT


ASSET_ROOT = asset_root()
FRONTEND_DIST = ASSET_ROOT / 'frontend' / 'dist'
DOWNLOADS_DIR = ASSET_ROOT / 'static' / 'downloads'
VERSION_FILE = ASSET_ROOT / 'data' / 'app_version.json'
