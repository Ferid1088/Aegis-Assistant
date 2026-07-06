"""Proves task_postrun's decrement handler only fires on a terminal task state.

Celery's task_postrun signal fires after every task execution attempt --
including ones that end via a Retry exception (state="RETRY") -- not just
the final one. There is only ever a single INCR per job (at upload time), so
decrementing on every postrun (including retries) would drift the per-user
queued-ingestion counter negative for any job that retries.
"""

from types import SimpleNamespace
from unittest.mock import patch

from rag.worker.celery_app import _decrement_ingestion_queue_count


def _sender():
    return SimpleNamespace(name="rag.worker.tasks.run_ingestion")


_JOB_ID = "11111111-1111-1111-1111-111111111111"


@patch("rag.worker.celery_app.decrement_queued_ingestion")
@patch("rag.worker.celery_app.get_job")
@patch("rag.worker.celery_app.SessionLocal")
def test_does_not_decrement_on_retry_state(mock_session_local, mock_get_job, mock_decrement):
    mock_get_job.return_value = SimpleNamespace(uploaded_by="user-1")

    _decrement_ingestion_queue_count(sender=_sender(), args=[_JOB_ID], state="RETRY")

    mock_decrement.assert_not_called()


@patch("rag.worker.celery_app.decrement_queued_ingestion")
@patch("rag.worker.celery_app.get_job")
@patch("rag.worker.celery_app.SessionLocal")
def test_decrements_on_success_state(mock_session_local, mock_get_job, mock_decrement):
    mock_get_job.return_value = SimpleNamespace(uploaded_by="user-1")

    _decrement_ingestion_queue_count(sender=_sender(), args=[_JOB_ID], state="SUCCESS")

    mock_decrement.assert_called_once_with("user-1")


@patch("rag.worker.celery_app.decrement_queued_ingestion")
@patch("rag.worker.celery_app.get_job")
@patch("rag.worker.celery_app.SessionLocal")
def test_decrements_on_failure_state(mock_session_local, mock_get_job, mock_decrement):
    mock_get_job.return_value = SimpleNamespace(uploaded_by="user-1")

    _decrement_ingestion_queue_count(sender=_sender(), args=[_JOB_ID], state="FAILURE")

    mock_decrement.assert_called_once_with("user-1")


@patch("rag.worker.celery_app.decrement_queued_ingestion")
@patch("rag.worker.celery_app.get_job")
@patch("rag.worker.celery_app.SessionLocal")
def test_does_not_decrement_for_unrelated_task(mock_session_local, mock_get_job, mock_decrement):
    other_sender = SimpleNamespace(name="rag.worker.tasks.some_other_task")

    _decrement_ingestion_queue_count(sender=other_sender, args=[_JOB_ID], state="SUCCESS")

    mock_decrement.assert_not_called()
    mock_get_job.assert_not_called()
