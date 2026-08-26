"""Evidence artifact storage (Block D.1).

Persists per-check evidence files under ``{evidence_dir}/{check_id}/`` with a
SHA-256 chain-of-custody manifest stored on the checks row:

- suspect.png / reference.png  — images as they were analyzed,
- screenshot.png               — full marketplace page at check time (best effort),
- manifest.json                — file list + hashes + timestamps.
"""

import base64
import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _evidence_dir(check_id: int) -> str:
    root = os.getenv("EVIDENCE_DIR", "evidence")
    return os.path.join(root, str(check_id))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_artifact(check_id: int, filename: str, data: bytes) -> Dict[str, Any]:
    """Write one evidence file; returns its manifest entry."""
    directory = _evidence_dir(check_id)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    with open(path, "wb") as f:
        f.write(data)
    return {
        "name": filename,
        "sha256": sha256_bytes(data),
        "size": len(data),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }


def load_artifact(check_id: int, filename: str) -> Optional[bytes]:
    path = os.path.join(_evidence_dir(check_id), filename)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def get_manifest(check_id: int) -> list:
    """Manifest from disk (source of truth); DB mirror is a convenience copy."""
    manifest_path = os.path.join(_evidence_dir(check_id), "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f).get("files", [])
    return []


def capture_page_screenshot(check_id: int, url: str) -> Optional[Dict[str, Any]]:
    """Best-effort full-page screenshot of the marketplace listing.

    Runs synchronously (call from a background task); returns the manifest
    entry or None when Playwright/browser is unavailable.
    """
    try:
        import asyncio

        from services.browser_service import PLAYWRIGHT_AVAILABLE

        if not PLAYWRIGHT_AVAILABLE:
            return None

        async def _shoot() -> bytes:
            from services.browser_service import BrowserSettings, MinimalBrowserService

            async with MinimalBrowserService(BrowserSettings()) as browser:
                await browser.navigate(url)
                await asyncio.sleep(2)
                return await browser.take_screenshot(full_page=True)

        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Called from async context via run_in_executor-free helper below.
            raise RuntimeError("use capture_page_screenshot_async in running loop")
        shot = loop.run_until_complete(_shoot())
        return save_artifact(check_id, "screenshot.png", shot)
    except RuntimeError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Screenshot failed for check {check_id}: {e}")
        return None


async def capture_page_screenshot_async(check_id: int, url: str) -> Optional[Dict[str, Any]]:
    """Async variant used from FastAPI background tasks."""
    try:
        from services.browser_service import PLAYWRIGHT_AVAILABLE

        if not PLAYWRIGHT_AVAILABLE:
            return None

        async def _shoot() -> bytes:
            from services.browser_service import BrowserSettings, MinimalBrowserService

            async with MinimalBrowserService(BrowserSettings()) as browser:
                await browser.navigate(url)
                await asyncio.sleep(2)
                return await browser.take_screenshot(full_page=True)

        shot = await _shoot()
        entry = save_artifact(check_id, "screenshot.png", shot)

        # Refresh manifest on disk with the screenshot included.
        files = get_manifest(check_id)
        if all(f["name"] != "screenshot.png" for f in files):
            files.append(entry)
        finalize_manifest(check_id, files)
        return entry
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Screenshot failed for check {check_id}: {e}")
        return None


def finalize_manifest(check_id: int, files: list) -> None:
    """Write manifest.json and mirror it onto the checks row (async-safe wrapper)."""
    directory = _evidence_dir(check_id)
    os.makedirs(directory, exist_ok=True)
    manifest = {
        "check_id": check_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": "SHA-256",
        "files": files,
    }
    with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    try:
        import asyncio

        from database import update_check_evidence

        coro = update_check_evidence(
            check_id, json.dumps(manifest["files"], ensure_ascii=False)
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            asyncio.run(coro)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Manifest DB mirror failed for check {check_id}: {e}")


def persist_analysis_artifacts(
    check_id: int,
    url: str,
    reference_b64: Optional[str],
    suspect_b64: Optional[str],
) -> list:
    """Persist reference/suspect images of a completed analysis. Returns manifest."""
    entries: list = []

    meta = {
        "url": url,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "note": "Artifacts saved at analysis time by FakeDetect",
    }
    meta_bytes = json.dumps(meta, ensure_ascii=False, indent=2).encode()
    entries.append(save_artifact(check_id, "meta.json", meta_bytes))

    for name, b64 in (("reference.png", reference_b64), ("suspect.png", suspect_b64)):
        if not b64:
            continue
        try:
            data = base64.b64decode(b64) if isinstance(b64, str) else b64
            entries.append(save_artifact(check_id, name, data))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Evidence artifact {name} skipped for check {check_id}: {e}")

    finalize_manifest(check_id, entries)
    return entries
