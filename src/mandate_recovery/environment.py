"""Explicit project environment loading for local scripts and demos."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_project_environment(project_root: Path) -> bool:
    """Load `.env` without overwriting variables supplied by the host."""
    return load_dotenv(project_root / ".env", override=False)
