from unittest.mock import patch

import pytest

from rag.domain import ingestion_job_service
from rag.storage.sql.models import User


def _make_job(db_session):
    user = User(username="uploader")
    db_session.add(user)
    db_session.flush()
    job = ingestion_job_service.create_job(
        db_session, uploaded_by=user.id, filename="a.pdf", staged_path="/tmp/a.pdf", doc_version=None,
    )
    return job


@patch("rag.worker.tasks.SessionLocal")
@patch("rag.worker.tasks.build_ingestion_graph")
def test_run_ingestion_success_marks_job_done(mock_build_graph, mock_session_local, db_session):
    mock_session_local.return_value = db_session
    job = _make_job(db_session)
    # Capture the id before the task runs: run_ingestion mutates and commits against
    # this same session, which expires other instances in its identity map (like
    # `job`), so we must hold the UUID value now rather than touch `job.id` later.
    job_uuid = job.id

    mock_graph = mock_build_graph.return_value
    mock_graph.invoke.return_value = {
        "status": "indexed", "indexed_count": 5,
        "doc_meta": type("M", (), {"logical_doc_id": "ld-1"})(),
    }

    from rag.worker.tasks import run_ingestion
    run_ingestion.run(str(job_uuid))

    refreshed = ingestion_job_service.get_job(db_session, job_uuid)
    assert refreshed.status == "done"
    assert refreshed.logical_doc_id == "ld-1"
    assert refreshed.indexed_count == 5


@patch("rag.worker.tasks.SessionLocal")
@patch("rag.worker.tasks.build_ingestion_graph")
def test_run_ingestion_graph_error_status_marks_job_failed(mock_build_graph, mock_session_local, db_session):
    mock_session_local.return_value = db_session
    job = _make_job(db_session)
    job_uuid = job.id

    mock_graph = mock_build_graph.return_value
    mock_graph.invoke.return_value = {"status": "error", "error": "File not found: /tmp/a.pdf"}

    from rag.worker.tasks import run_ingestion
    run_ingestion.run(str(job_uuid))

    refreshed = ingestion_job_service.get_job(db_session, job_uuid)
    assert refreshed.status == "failed"
    assert "File not found" in refreshed.error


@patch("rag.worker.tasks.SessionLocal")
@patch("rag.worker.tasks.build_ingestion_graph")
def test_run_ingestion_duplicate_skip_marks_job_done_with_no_new_content(mock_build_graph, mock_session_local, db_session):
    mock_session_local.return_value = db_session
    job = _make_job(db_session)
    job_uuid = job.id

    mock_graph = mock_build_graph.return_value
    mock_graph.invoke.return_value = {"status": "skipped (duplicate)"}

    from rag.worker.tasks import run_ingestion
    run_ingestion.run(str(job_uuid))

    refreshed = ingestion_job_service.get_job(db_session, job_uuid)
    assert refreshed.status == "done"
    assert refreshed.indexed_count is None


@patch("rag.worker.tasks.SessionLocal")
@patch("rag.worker.tasks.build_ingestion_graph")
def test_run_ingestion_unhandled_exception_marks_job_failed(mock_build_graph, mock_session_local, db_session):
    mock_session_local.return_value = db_session
    job = _make_job(db_session)
    job_uuid = job.id

    mock_graph = mock_build_graph.return_value
    mock_graph.invoke.side_effect = RuntimeError("pipeline exploded")

    from rag.worker.tasks import run_ingestion

    # run_ingestion.run(...) calls the task body directly, bypassing the broker, so
    # Celery's Task.request.called_directly is True. Under that condition self.retry()
    # does NOT raise celery.exceptions.Retry -- per Task.retry's source, it instead
    # calls raise_with_context(exc), re-raising the *original* exception (our
    # RuntimeError) with its context preserved. mark_failed runs before that raise
    # (it's the line right before `raise self.retry(...)`), so the DB assertion below
    # still proves mark_failed was called regardless of how the exception propagates.
    with pytest.raises(RuntimeError, match="pipeline exploded"):
        run_ingestion.run(str(job_uuid))

    refreshed = ingestion_job_service.get_job(db_session, job_uuid)
    assert refreshed.status == "failed"
    assert "pipeline exploded" in refreshed.error
