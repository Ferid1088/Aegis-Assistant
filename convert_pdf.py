"""CLI wrapper. The real implementation lives in rag/convert_pdf.py so it's importable
as a genuine package module regardless of how a process is invoked -- a bare top-level
`import convert_pdf` only works when the repo root happens to be on sys.path (true for
`python convert_pdf.py` and under pytest, NOT true for installed console-script entry
points like `celery`)."""

import sys
from pathlib import Path

from rag.convert_pdf import convert

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convert_pdf.py <path.pdf>")
        sys.exit(1)
    convert(Path(sys.argv[1]))
