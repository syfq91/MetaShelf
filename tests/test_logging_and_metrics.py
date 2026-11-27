"""Tests for structured JSON logging, log level setting, and /metrics endpoint."""

import json
import logging
from pathlib import Path

from fastapi.testclient import TestClient

from metashelf.config import Settings
from metashelf.db.models import Item, Job, Library
from metashelf.logging_config import JsonFormatter, configure_logging
from metashelf.main import create_app


def test_json_formatter_and_configure_logging() -> None:
    configure_logging(log_level="DEBUG", log_format="json")
    assert logging.getLogger().level == logging.DEBUG

    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="metashelf.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    parsed = json.loads(formatter.format(record))
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "metashelf.test"
    assert parsed["message"] == "hello world"
    assert "timestamp" in parsed

    # Restore INFO default
    configure_logging(log_level="INFO", log_format="json")


async def test_metrics_endpoint_reports_counts(tmp_path: Path) -> None:
    media_root = tmp_path / "movies"
    media_root.mkdir()
    app_settings = Settings(
        config_dir=tmp_path / "config",
        media_roots=str(media_root),
        log_level="WARNING",
    )
    app = create_app(settings=app_settings)
    assert logging.getLogger().level == logging.WARNING

    with TestClient(app) as client:
        async with app.state.session_factory() as session:
            lib = Library(name="Movies", type="movie", root_path=str(media_root))
            session.add(lib)
            await session.flush()
            session.add(
                Item(
                    library_id=lib.id,
                    kind="movie",
                    rel_path="A/A.mkv",
                    title="A",
                )
            )
            session.add(Job(type="scan_library", payload_json="{}", status="done"))
            await session.commit()

        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert "metashelf_libraries_total 1" in resp.text
        assert 'metashelf_items_total{kind="movie"} 1' in resp.text
        assert 'metashelf_jobs_total{status="done"} 1' in resp.text
