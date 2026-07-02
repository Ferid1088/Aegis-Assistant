import pytest

from rag.domain import ingestion_job_service
from rag.storage.sql.models import User


def _make_user(db_session):
    user = User(username="uploader")
    db_session.add(user)
    db_session.flush()
    return user


def test_create_job_defaults_to_queued(db_session):
    user = _make_user(db_session)
    job = ingestion_job_service.create_job(
        db_session, uploaded_by=user.id, filename="a.pdf", staged_path="/tmp/a.pdf", doc_version=None,
    )
    assert job.status == "queued"
    assert job.filename == "a.pdf"


def test_get_job_not_found_raises(db_session):
    import uuid
    with pytest.raises(ingestion_job_service.JobNotFound):
        ingestion_job_service.get_job(db_session, uuid.uuid4())


def test_mark_running_then_done_sets_fields(db_session):
    user = _make_user(db_session)
    job = ingestion_job_service.create_job(
        db_session, uploaded_by=user.id, filename="a.pdf", staged_path="/tmp/a.pdf", doc_version=None,
    )
    ingestion_job_service.mark_running(db_session, job)
    assert job.status == "running"

    ingestion_job_service.mark_done(db_session, job, logical_doc_id="ld1", indexed_count=12)
    assert job.status == "done"
    assert job.logical_doc_id == "ld1"
    assert job.indexed_count == 12


def test_mark_failed_sets_error_and_increments_retry_count(db_session):
    user = _make_user(db_session)
    job = ingestion_job_service.create_job(
        db_session, uploaded_by=user.id, filename="a.pdf", staged_path="/tmp/a.pdf", doc_version=None,
    )
    ingestion_job_service.mark_failed(db_session, job, error="boom")
    assert job.status == "failed"
    assert job.error == "boom"
    assert job.retry_count == 1
