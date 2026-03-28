"""Background update checker for PathSafe.

Checks GitHub releases API for new versions. Disabled by default (opt-in via
Settings menu) to respect hospital network policies and HIPAA/GDPR concerns.

Design decisions:
- Disabled by default: no phoning home without consent
- Runs on a background QThread, never blocks GUI startup
- 2-second timeout, silent failure if offline
- Opens external browser for download (no auto-exec)
"""

import json
import platform
import urllib.error
import urllib.request
from dataclasses import dataclass

import pathsafe


GITHUB_API_URL = "https://api.github.com/repos/DrSoma/PathSafe/releases/latest"
RELEASES_PAGE = "https://github.com/DrSoma/PathSafe/releases/latest"
REQUEST_TIMEOUT = 2  # seconds


@dataclass
class UpdateInfo:
    """Information about an available update."""

    current_version: str
    latest_version: str
    release_url: str
    download_url: str | None = None
    is_newer: bool = False


def parse_version(v: str) -> tuple:
    """Parse version string like '1.1.0' or 'v1.1.0' into comparable tuple."""
    v = v.lstrip("v")
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_for_update() -> UpdateInfo | None:
    """Check GitHub for a newer release. Returns UpdateInfo or None.

    Returns None on any error (network, parse, timeout). Never raises.
    """
    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"PathSafe/{pathsafe.__version__}",
            },
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read())

        tag = data.get("tag_name", "")
        html_url = data.get("html_url", RELEASES_PAGE)

        current = parse_version(pathsafe.__version__)
        latest = parse_version(tag)

        if latest <= current:
            return None

        # Find the right download URL for this platform
        download_url = _find_download_url(data.get("assets", []))

        return UpdateInfo(
            current_version=pathsafe.__version__,
            latest_version=tag.lstrip("v"),
            release_url=html_url,
            download_url=download_url,
            is_newer=True,
        )
    except Exception:
        return None


def _find_download_url(assets: list) -> str | None:
    """Find the appropriate download URL for the current platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    for asset in assets:
        name = asset.get("name", "").lower()
        url = asset.get("browser_download_url", "")

        if system == "linux":
            if "arm64" in machine or "aarch64" in machine:
                if "linux-arm64" in name and name.endswith(".appimage"):
                    return url
            else:
                if "linux" in name and "arm64" not in name and name.endswith(".appimage"):
                    return url
        elif system == "darwin":
            if name.endswith(".dmg"):
                return url
        elif system == "windows" and name.endswith(".exe") and "setup" in name:
            return url

    # Fallback: return the release page
    return None
