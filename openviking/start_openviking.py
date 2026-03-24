"""Render ov.conf, then exec the OpenViking server without a shell wrapper."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from render_ov_conf import main as render_config


def main() -> None:
    render_config()
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
