import json
import logging
from pathlib import Path
from typing import Any

import filelock

log = logging.getLogger(__name__)

_LOCK_TIMEOUT = 5
_STATE_FILENAME = "seen_ids.json"


class DataReader:
    """
    Polls alf's flat-file data directory for new AuctionRecord JSON.

    alf writes records to:
        {data_dir}/{manufacturer}/{model}/{YYYY-MM-DD}/auctions.json

    Each auctions.json is a JSON array of AuctionRecord dicts. DataReader
    scans the entire data_dir tree on every poll(), compares record IDs
    against the persisted seen-ID set, and returns only unseen records.

    The seen-ID set is persisted to {state_dir}/seen_ids.json so that
    ralf survives restarts without reprocessing historical records.
    """

    def __init__(self, data_dir: str, state_dir: str) -> None:
        self._data_dir  = Path(data_dir)
        self._state_dir = Path(state_dir)
        self._state_file = self._state_dir / _STATE_FILENAME
        self._lock_file  = self._state_dir / f"{_STATE_FILENAME}.lock"
        self._seen_ids: set[str] = self._load_seen_ids()
        log.info(
            "DataReader initialised — data_dir=%s  seen=%d IDs",
            self._data_dir,
            len(self._seen_ids),
        )

    def poll(self) -> list[dict[str, Any]]:
        """
        Scan the data directory and return all records not previously seen.

        Thread-safe against alf writing to the same files (reads are
        non-destructive; alf uses filelock per auctions.json).
        """
        if not self._data_dir.exists():
            log.warning("data_dir %s does not exist — no records", self._data_dir)
            return []

        auction_files = list(self._data_dir.rglob("auctions.json"))
        log.debug("DataReader poll: found %d auction file(s)", len(auction_files))

        new_records: list[dict[str, Any]] = []

        for path in auction_files:
            try:
                records = self._read_file(path)
            except Exception as exc:
                log.warning("Could not read %s: %s — skipping", path, exc)
                continue

            for record in records:
                rid = record.get("id")
                if rid and rid not in self._seen_ids:
                    new_records.append(record)
                    self._seen_ids.add(rid)

        if new_records:
            log.info("DataReader: %d new record(s) from %d file(s)", len(new_records), len(auction_files))
            self._persist_seen_ids()
        else:
            log.debug("DataReader: no new records (checked %d file(s))", len(auction_files))

        return new_records

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _read_file(self, path: Path) -> list[dict[str, Any]]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            log.warning("Unexpected format in %s — expected list, got %s", path, type(data).__name__)
            return []
        return data

    def _load_seen_ids(self) -> set[str]:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        if not self._state_file.exists():
            return set()
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data) if isinstance(data, list) else set()
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not load seen_ids from %s: %s — starting fresh", self._state_file, exc)
            return set()

    def _persist_seen_ids(self) -> None:
        try:
            with filelock.FileLock(str(self._lock_file), timeout=_LOCK_TIMEOUT):
                with open(self._state_file, "w", encoding="utf-8") as f:
                    json.dump(sorted(self._seen_ids), f)
        except filelock.Timeout:
            log.error("Lock timeout persisting seen_ids — state may be slightly stale")
        except OSError as exc:
            log.error("Could not persist seen_ids: %s", exc)
