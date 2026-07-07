"""Run Alembic migrations to head programmatically, so the app self-migrates on startup
instead of requiring a separate manual/deploy-time step.

Must be called via `asyncio.to_thread` (or otherwise off the running event loop): Alembic's
sync `command.upgrade` drives our async env.py via its own internal `asyncio.run(...)`, which
raises if called from inside an already-running event loop.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def run_migrations_to_head() -> None:
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "app" / "migrations"))
    command.upgrade(config, "head")
