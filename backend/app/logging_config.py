"""Central logging setup, called from app/main.py.

Two unrelated things silently disable our `app.*` module-level loggers on every startup, both
via `logging.config`'s default `disable_existing_loggers=True` (which disables every
already-instantiated logger not mentioned in the config being applied):

1. `fastapi dev`/uvicorn imports app.main (instantiating all `app.*` loggers via module-level
   `getLogger(__name__)` calls) before uvicorn builds its Config and runs its own
   configure_logging().
2. `run_migrations_to_head()` -> Alembic's env.py calls `fileConfig(alembic.ini)`, which runs
   later still and disables them again.

`disable_existing_loggers=False` on *our own* dictConfig call only stops that one call from
disabling anything -- it doesn't clear `.disabled` flags a previous call already set. So
configure_logging() must run again after migrations, and must explicitly re-enable, not just
configure.
"""

import logging
import logging.config


def configure_logging() -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "level": "INFO",
                },
            },
            "loggers": {
                "app": {"level": "INFO", "handlers": ["console"], "propagate": False},
            },
        }
    )

    for name, logger_obj in logging.root.manager.loggerDict.items():
        if name.startswith("app") and isinstance(logger_obj, logging.Logger):
            logger_obj.disabled = False
