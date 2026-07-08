from pathlib import Path
from unittest.mock import patch

import pytest

from rag.domain import ingestion_job_service
from rag.infra.stores.sql.models import User


def _make_job(db_session, tmp_path=None):
    user = User(username="uploader")
    db_session.add(user)
    db_session.flush()
    staged_path = "/tmp/a.pdf"
    if tmp_path is not None:
        staged_path = str(tmp_path / "a.pdf")
        Path(staged_path).write_bytes(b"%PDF-1.4 fake content")
    job = ingestion_job_service.create_job(
        db_session, uploaded_by=user.id, filename="a.pdf", staged_path=staged_path, doc_version=None,
    )
    return job


@patch("rag.worker.tasks.SessionLocal")
@patch("rag.worker.tasks.build_ingestion_graph")
def test_run_ingestion_success_marks_job_done(mock_build_graph, mock_session_local, db_session, tmp_path):
    mock_session_local.return_value = db_session
    job = _make_job(db_session, tmp_path)
    # Capture the id before the task runs: run_ingestion mutates and commits against
    # this same session, which expires other instances in its identity map (like
    # `job`), so we must hold the UUID value now rather than touch `job.id` later.
    job_uuid = job.id
    staged_path = job.staged_path

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
    assert not Path(staged_path).exists()


@patch("rag.worker.tasks.SessionLocal")
@patch("rag.worker.tasks.build_ingestion_graph")
def test_run_ingestion_graph_error_status_marks_job_failed(mock_build_graph, mock_session_local, db_session, tmp_path):
    mock_session_local.return_value = db_session
    job = _make_job(db_session, tmp_path)
    job_uuid = job.id
    staged_path = job.staged_path

    mock_graph = mock_build_graph.return_value
    mock_graph.invoke.return_value = {"status": "error", "error": "File not found: /tmp/a.pdf"}

    from rag.worker.tasks import run_ingestion
    run_ingestion.run(str(job_uuid))

    refreshed = ingestion_job_service.get_job(db_session, job_uuid)
    assert refreshed.status == "failed"
    assert "File not found" in refreshed.error
    assert not Path(staged_path).exists()


@patch("rag.worker.tasks.SessionLocal")
@patch("rag.worker.tasks.build_ingestion_graph")
def test_run_ingestion_duplicate_skip_marks_job_done_with_no_new_content(mock_build_graph, mock_session_local, db_session, tmp_path):
    mock_session_local.return_value = db_session
    job = _make_job(db_session, tmp_path)
    job_uuid = job.id
    staged_path = job.staged_path

    mock_graph = mock_build_graph.return_value
    mock_graph.invoke.return_value = {"status": "skipped (duplicate)"}

    from rag.worker.tasks import run_ingestion
    run_ingestion.run(str(job_uuid))

    refreshed = ingestion_job_service.get_job(db_session, job_uuid)
    assert refreshed.status == "done"
    assert refreshed.indexed_count is None
    assert not Path(staged_path).exists()


@patch("rag.worker.tasks.SessionLocal")
@patch("rag.worker.tasks.build_ingestion_graph")
def test_run_ingestion_unhandled_exception_with_retries_remaining_stays_running(
    mock_build_graph, mock_session_local, db_session, tmp_path,
):
    mock_session_local.return_value = db_session
    job = _make_job(db_session, tmp_path)
    job_uuid = job.id
    staged_path = job.staged_path

    mock_graph = mock_build_graph.return_value
    mock_graph.invoke.side_effect = RuntimeError("pipeline exploded")

    from rag.worker.tasks import run_ingestion

    # run_ingestion.run(...) calls the task body directly, bypassing the broker, so
    # Celery's Task.request.called_directly is True. Under that condition self.retry()
    # does NOT raise celery.exceptions.Retry -- per Task.retry's source, it instead
    # calls raise_with_context(exc), re-raising the *original* exception (our
    # RuntimeError) with its context preserved. record_retry_attempt runs before that
    # raise (it's the line right before `raise self.retry(...)`), so the DB assertion
    # below still proves record_retry_attempt was called regardless of how the
    # exception propagates.
    #
    # self.request.retries defaults to 0 when the task is invoked via .run() (no
    # request context is pushed, so Task.request falls back to a bare Context() whose
    # `retries` class attribute is 0), which is < max_retries=3, so this exercises the
    # "retries remain" branch: status must stay "running", not flip to "failed", and
    # the staged file must NOT be deleted (a retry needs to re-read it).
    with pytest.raises(RuntimeError, match="pipeline exploded"):
        run_ingestion.run(str(job_uuid))

    refreshed = ingestion_job_service.get_job(db_session, job_uuid)
    assert refreshed.status == "running"
    assert "pipeline exploded" in refreshed.error
    assert refreshed.retry_count == 1
    assert Path(staged_path).exists()


@patch("rag.worker.tasks.SessionLocal")
@patch("rag.worker.tasks.build_ingestion_graph")
def test_run_ingestion_unhandled_exception_with_retries_exhausted_marks_job_failed(
    mock_build_graph, mock_session_local, db_session, tmp_path,
):
    mock_session_local.return_value = db_session
    job = _make_job(db_session, tmp_path)
    job_uuid = job.id
    staged_path = job.staged_path

    mock_graph = mock_build_graph.return_value
    mock_graph.invoke.side_effect = RuntimeError("pipeline exploded")

    from rag.worker.tasks import run_ingestion

    # Simulate Celery having already retried this task 3 times (== max_retries=3),
    # i.e. this is the final allowed attempt. Task.push_request pushes a new Context
    # onto the task's request_stack, merging in the given kwargs (retries=3) over the
    # current request's __dict__; self.request then resolves to this pushed Context
    # for the duration of the call. pop_request() restores the prior state afterward,
    # mirroring how Celery's own worker trace pushes/pops requests around a task
    # invocation (celery/app/trace.py).
    run_ingestion.push_request(retries=3)
    try:
        run_ingestion.run(str(job_uuid))
    finally:
        run_ingestion.pop_request()

    refreshed = ingestion_job_service.get_job(db_session, job_uuid)
    assert refreshed.status == "failed"
    assert "pipeline exploded" in refreshed.error
    assert not Path(staged_path).exists()
    mock_graph.invoke.assert_called_once()
