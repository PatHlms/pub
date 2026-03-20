"""
Regression test infrastructure: snapshot helpers and pytest options.
"""
import json
from pathlib import Path

import pytest


SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
FIXTURES_DIR  = Path(__file__).parent / "fixtures"

# Fields excluded from snapshot comparison — they change on every run.
_VOLATILE_FIELDS = frozenset({"harvested_at"})


def load_fixture(name: str) -> dict:
    """Load a raw API response fixture by site name."""
    path = FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text())


def records_to_snapshot(records) -> list[dict]:
    """Serialise parsed records, stripping volatile fields."""
    out = []
    for r in records:
        d = r.to_dict()
        for f in _VOLATILE_FIELDS:
            d.pop(f, None)
        out.append(d)
    return out


def assert_matches_snapshot(actual_records, snapshot_name: str, update: bool = False) -> None:
    """
    Compare actual parsed records against a stored snapshot.

    Pass --update-snapshots on the pytest command line to regenerate.
    If the snapshot file does not exist yet, it is created automatically
    and the test is marked xfail so the diff is visible.
    """
    actual = records_to_snapshot(actual_records)
    snapshot_path = SNAPSHOTS_DIR / f"{snapshot_name}.json"

    if update or not snapshot_path.exists():
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(actual, indent=2, ensure_ascii=False) + "\n")
        if not update:
            pytest.xfail(f"Snapshot created at {snapshot_path} — re-run to verify")
        return

    expected = json.loads(snapshot_path.read_text())
    assert actual == expected, _diff_message(actual, expected, snapshot_name)


def _diff_message(actual: list, expected: list, name: str) -> str:
    if len(actual) != len(expected):
        return (
            f"Snapshot '{name}': record count changed "
            f"(got {len(actual)}, expected {len(expected)})"
        )
    for i, (a, e) in enumerate(zip(actual, expected)):
        diffs = {k for k in (set(a) | set(e)) if a.get(k) != e.get(k)}
        if diffs:
            return (
                f"Snapshot '{name}' record[{i}] fields differ: {sorted(diffs)}\n"
                f"  actual:   { {k: a.get(k) for k in sorted(diffs)} }\n"
                f"  expected: { {k: e.get(k) for k in sorted(diffs)} }"
            )
    return f"Snapshot '{name}' differs (unknown field)"


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Regenerate regression snapshot files.",
    )


@pytest.fixture
def update_snapshots(request) -> bool:
    return request.config.getoption("--update-snapshots")
