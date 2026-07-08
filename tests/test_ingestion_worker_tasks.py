import uuid
from unittest.mock import MagicMock, patch

import pytest

from rag.domain import ingestion_job_service
from rag.infra.stores.sql.models import User
from rag.worker.tasks import run_ingestion


@pytest.fixture()
def job(db_session, tmp_path):
    user = User(username="uploader")
    db_session.add(user)
    db_session.flush()
    db_session.commit()
    return ingestion_job_service.create_job(
        db_session, uploaded_by=user.id, filename="a.pdf", staged_path=str(tmp_path / "a.pdf"),
        doc_version=None, department="Finance", document_type="invoice", access_level=["FIN_L1", "FIN_L2"],
    )


@patch("rag.worker.tasks.SessionLocal")
@patch("rag.worker.tasks.build_ingestion_graph")
def test_run_ingestion_threads_metadata_into_graph_state(mock_build_graph, mock_session_local, db_session, job, tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    mock_session_local.return_value = db_session
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {"status": "converted", "doc_meta": None, "indexed_count": 0}
    mock_build_graph.return_value = mock_graph

    run_ingestion.run(str(job.id))

    called_state = mock_graph.invoke.call_args[0][0]
    assert called_state["department"] == "Finance"
    assert called_state["document_type"] == "invoice"
    assert called_state["access_level"] == ["FIN_L1", "FIN_L2"]
