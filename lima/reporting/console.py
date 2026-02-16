"""
Console reporter — renders a DiagnosticReport as a formatted text table
to stdout (or any file-like stream). No external dependencies required.
"""
import sys
from datetime import datetime
from typing import TextIO
from .report import DiagnosticReport

_STATUS_SYMBOL = {
    'ok': ' OK ',
    'warning': 'WARN',
    'critical': 'CRIT',
    'unknown': ' ?? ',
    'OK': ' OK ',
    'WARNING': 'WARN',
    'CRITICAL': 'CRIT',
}

_COL_WIDTHS = {
    'sensor': 24,
    'value': 14,
    'unit': 10,
    'status': 6,
}


def _pad(text: str, width: int) -> str:
    return str(text)[:width].ljust(width)


def render(report: DiagnosticReport, stream: TextIO = sys.stdout):
    w = stream.write
    sep = '─' * 72

    w(f'\n{"═" * 72}\n')
    w(f'  BMW TDV6 DIAGNOSTIC REPORT\n')
    w(f'  Vehicle : {report.vehicle_id}\n')
    w(f'  Generated: {report.generated_at.strftime("%Y-%m-%d %H:%M:%S")} UTC\n')
    w(f'  Status   : [{_STATUS_SYMBOL.get(report.overall_status, "????")}] {report.overall_status}\n')
    w(f'  Faults   : {report.critical_count} critical / {report.warning_count} warning\n')
    w(f'{"═" * 72}\n\n')

    # Sensor readings table
    header = (
        f'  {"SENSOR":<24} {"VALUE":>12}  {"UNIT":<10} {"STATUS":>6}\n'
    )
    w(header)
    w(f'  {sep[2:]}\n')

    for reading in report.readings:
        val_str = (
            f'{reading.value:.2f}' if isinstance(reading.value, float) else str(reading.value)
        )
        status_sym = _STATUS_SYMBOL.get(reading.status, '????')
        w(
            f'  {_pad(reading.sensor_name, 24)} '
            f'{val_str:>12}  '
            f'{_pad(reading.unit, 10)} '
            f'[{status_sym}]\n'
        )
        for fc in reading.fault_codes:
            severity_tag = f'[{fc.severity.upper()[:4]:4}]'
            w(f'    {severity_tag}  {fc.code}  {fc.description}\n')

    if report.fault_codes:
        w(f'\n  {sep[2:]}\n')
        w(f'  FAULT CODE SUMMARY ({len(report.fault_codes)} total)\n')
        w(f'  {sep[2:]}\n')
        for fc in report.fault_codes:
            severity_tag = f'[{fc.severity.upper()[:4]:4}]'
            w(f'  {severity_tag}  {fc.code:<8}  {fc.description}\n')

    if report.notes:
        w(f'\n  Notes: {report.notes}\n')

    w(f'\n{"═" * 72}\n\n')
    stream.flush()
