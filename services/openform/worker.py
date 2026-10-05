"""Durable authoring worker; model calls run outside database transactions."""
import argparse
import sys

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from openform.config import Settings
from openform.database import DatabaseNotReady, build_engine, probe_database
from openform.jobs.runner import dispatch_engine, serve


def preflight(settings: Settings) -> bool:
    engine = build_engine(settings)
    try:
        probe_database(engine)
        return True
    except (SQLAlchemyError, DatabaseNotReady):
        return False
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenForm worker 环境检查")
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if not arguments.check:
        settings = Settings()
        engine, dispatcher = build_engine(settings), dispatch_engine(settings)
        try:
            probe_database(engine)
            serve(engine, dispatcher, settings)
        finally:
            dispatcher.dispose()
            engine.dispose()
        return 0
    try:
        ready = preflight(Settings())
    except (ValidationError, OSError, ValueError):
        ready = False
    print("worker preflight ready" if ready else "worker preflight unavailable")
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
