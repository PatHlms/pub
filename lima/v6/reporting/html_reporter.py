"""
HTML reporter — generates a self-contained HTML diagnostic report.
No external dependencies; uses inline CSS.
"""
from pathlib import Path
from .report import DiagnosticReport, SensorReading

_STATUS_COLOUR = {
    'ok': '#2ecc71',
    'warning': '#f39c12',
    'critical': '#e74c3c',
    'unknown': '#95a5a6',
}

_SEVERITY_COLOUR = {
    'info': '#3498db',
    'warning': '#f39c12',
    'critical': '#e74c3c',
}


def _status_badge(status: str) -> str:
    colour = _STATUS_COLOUR.get(status.lower(), '#95a5a6')
    return f'<span style="background:{colour};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.85em;">{status.upper()}</span>'


def _fault_rows(reading: SensorReading) -> str:
    if not reading.fault_codes:
        return ''
    rows = []
    for fc in reading.fault_codes:
        colour = _SEVERITY_COLOUR.get(fc.severity, '#95a5a6')
        rows.append(
            f'<tr style="background:#1a1a2e;">'
            f'<td colspan="3" style="padding:4px 12px 4px 32px;font-size:0.85em;color:{colour};">'
            f'&#x26A0; <strong>{fc.code}</strong> — {fc.description}'
            f'</td></tr>'
        )
    return '\n'.join(rows)


def generate_html(report: DiagnosticReport) -> str:
    overall_colour = _STATUS_COLOUR.get(report.overall_status.lower(), '#95a5a6')

    reading_rows = []
    for r in report.readings:
        val_str = f'{r.value:.2f}' if isinstance(r.value, float) else str(r.value)
        reading_rows.append(
            f'<tr>'
            f'<td>{r.sensor_name}</td>'
            f'<td style="text-align:right;font-family:monospace;">{val_str}</td>'
            f'<td>{r.unit}</td>'
            f'<td>{_status_badge(r.status)}</td>'
            f'</tr>'
            + _fault_rows(r)
        )

    fault_section = ''
    if report.fault_codes:
        fault_rows = ''.join(
            f'<tr>'
            f'<td style="color:{_SEVERITY_COLOUR.get(fc.severity, "#fff")};">{fc.code}</td>'
            f'<td>{fc.description}</td>'
            f'<td>{_status_badge(fc.severity)}</td>'
            f'</tr>'
            for fc in report.fault_codes
        )
        fault_section = f'''
        <h2>Fault Code Summary</h2>
        <table>
            <thead><tr><th>Code</th><th>Description</th><th>Severity</th></tr></thead>
            <tbody>{fault_rows}</tbody>
        </table>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BMW TDV6 Diagnostic Report — {report.vehicle_id}</title>
<style>
  body {{ font-family: -apple-system, monospace; background: #0d0d1a; color: #e0e0e0; padding: 24px; }}
  h1, h2 {{ color: #a0c4ff; }}
  .summary {{ background: #16213e; border-left: 4px solid {overall_colour}; padding: 16px; margin-bottom: 24px; border-radius: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; }}
  th {{ background: #16213e; color: #a0c4ff; padding: 8px 12px; text-align: left; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #1e2a4a; }}
  tr:hover {{ background: #16213e; }}
</style>
</head>
<body>
<h1>BMW TDV6 Diagnostic Report</h1>
<div class="summary">
  <strong>Vehicle:</strong> {report.vehicle_id}<br>
  <strong>Generated:</strong> {report.generated_at.strftime("%Y-%m-%d %H:%M:%S")} UTC<br>
  <strong>Overall Status:</strong> {_status_badge(report.overall_status)}<br>
  <strong>Faults:</strong> {report.critical_count} critical / {report.warning_count} warning
  {f"<br><strong>Notes:</strong> {report.notes}" if report.notes else ""}
</div>

<h2>Sensor Readings</h2>
<table>
  <thead><tr><th>Sensor</th><th>Value</th><th>Unit</th><th>Status</th></tr></thead>
  <tbody>{"".join(reading_rows)}</tbody>
</table>
{fault_section}
</body>
</html>'''


def write_html(report: DiagnosticReport, path: str | Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_html(report), encoding='utf-8')
