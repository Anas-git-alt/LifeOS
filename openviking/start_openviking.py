"""Render ov.conf, then exec the OpenViking server without a shell wrapper."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from render_ov_conf import main as render_config


def _install_sitecustomize_patch() -> None:
    """Patch OpenViking quirks that are only configurable at Python import time."""
    patch_dir = Path("/tmp/lifeos-openviking-sitecustomize")
    patch_dir.mkdir(parents=True, exist_ok=True)
    (patch_dir / "sitecustomize.py").write_text(
        '''
import os


def _disabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"0", "false", "no", "off"}


if _disabled(os.getenv("OPENVIKING_EMBEDDING_SEND_DIMENSIONS")):
    try:
        from openviking.models.embedder.openai_embedders import OpenAIDenseEmbedder

        def _lifeos_do_not_send_dimensions(self):
            return False

        OpenAIDenseEmbedder._should_send_dimensions = _lifeos_do_not_send_dimensions
    except Exception:
        pass
'''.lstrip(),
        encoding="utf-8",
    )
    existing = os.getenv("PYTHONPATH", "").strip()
    os.environ["PYTHONPATH"] = (
        f"{patch_dir}{os.pathsep}{existing}" if existing else str(patch_dir)
    )


def main() -> None:
    render_config()
    _install_sitecustomize_patch()
    config_path = os.getenv("OPENVIKING_CONFIG_OUTPUT", "/app/ov.conf").strip() or "/app/ov.conf"
    if not Path(config_path).exists():
        raise FileNotFoundError(f"Rendered OpenViking config was not created at {config_path}")
    os.execv(
        "/app/.venv/bin/python",
        [
            "/app/.venv/bin/python",
            "-m",
            "openviking.server.bootstrap",
            "--config",
            config_path,
        ],
    )


if __name__ == "__main__":
    main()
