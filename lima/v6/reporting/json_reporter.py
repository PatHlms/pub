"""
JSON reporter — serialises a DiagnosticReport to JSON,
either as a string, to a file, or streamed as newline-delimited JSON (NDJSON).
"""
import json
import sys
from pathlib import Path
from typing import Optional, TextIO
from .report import DiagnosticReport


def to_json(report: DiagnosticReport, indent: int = 2) -> str:
    return json.dumps(report.to_dict(), indent=indent, default=str)


def write_json(report: DiagnosticReport, path: str | Path, indent: int = 2):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(report, indent=indent), encoding='utf-8')


def stream_ndjson(report: DiagnosticReport, stream: TextIO = sys.stdout):
    """Write one JSON object per reading (newline-delimited), suitable for log ingestion."""
    base = {
        'vehicle_id': report.vehicle_id,
        'generated_at': report.generated_at.isoformat(),
        'overall_status': report.overall_status,
    }
    for reading in report.readings:
        record = {**base, **reading.to_dict()}
        stream.write(json.dumps(record, default=str) + '\n')
    stream.flush()
