def test_convert_pdf_importable_as_rag_package_module():
    """This is the regression guard for the bug this task fixes: convert_pdf must be
    importable via the rag package (rag.infra.docling), not just as a bare top-level
    module that only works when the repo root happens to be on sys.path. Celery's
    installed console-script entry point does NOT add the invocation directory to
    sys.path, so a bare `import convert_pdf` fails there even though it works under
    pytest (which explicitly adds the repo root) and under `python run_ingest.py`
    (which Python does automatically for the script's own directory)."""
    from rag.infra.docling import convert

    assert callable(convert)


def test_ingestion_graph_module_imports_convert_pdf_from_rag_package():
    """Confirms rag/pipelines/ingestion/nodes.py's import was actually updated, not just
    that a parallel copy exists at rag.infra.docling while the real call site still uses
    the old, broken bare import."""
    import inspect

    import rag.pipelines.ingestion.nodes as ingestion_module

    source = inspect.getsource(ingestion_module)
    assert "from rag.infra.docling import" in source
    assert "from convert_pdf import" not in source
