from contextlib import nullcontext

from station.probe.settlement import close_device_range, read_device_outcome
from station.probe.traces import append_acceptance, append_sample, read_acceptance, read_delivery
from station.work.store import LANES, StationError, require_lane, require_text


def ensure_device_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS probe_power (
            device INTEGER PRIMARY KEY CHECK(device = 1),
            online INTEGER NOT NULL CHECK(online IN (0, 1))
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS probe_lanes (
            lane TEXT PRIMARY KEY,
            ready INTEGER NOT NULL CHECK(ready IN (0, 1))
        )
    ''')
    db.execute('INSERT OR IGNORE INTO probe_power VALUES (1, 1)')
    db.executemany('INSERT OR IGNORE INTO probe_lanes VALUES (?, 1)', ((lane,) for lane in LANES))


def _online(db):
    return bool(db.execute('SELECT online FROM probe_power WHERE device = 1').fetchone()[0])


def _require_online(db):
    if not _online(db):
        raise StationError('device_offline', 'probe device is offline')


def _check_switch(value):
    if type(value) is not bool:
        raise StationError('invalid_input', 'device controls require a boolean')


class ProbeDevice:
    def __init__(self, store):
        self._store = store

    def set_online(self, enabled):
        _check_switch(enabled)
        with self._store.write() as db:
            db.execute('UPDATE probe_power SET online = ? WHERE device = 1', (enabled,))

    def set_lane_ready(self, lane, ready):
        require_lane(lane)
        _check_switch(ready)
        with self._store.write() as db:
            db.execute('UPDATE probe_lanes SET ready = ? WHERE lane = ?', (ready, lane))

    def accept(self, lane, code, *, connection=None):
        require_lane(lane)
        require_text(code, 'code')
        transaction = self._store.write() if connection is None else nullcontext(connection)
        with transaction as db:
            ready = db.execute('SELECT ready FROM probe_lanes WHERE lane = ?', (lane,)).fetchone()[0]
            if not _online(db) or not ready:
                return None
            return append_acceptance(db, lane, code)

    def sample(self, acceptance_id, raw_value, source, sequence=None):
        with self._store.write() as db:
            _require_online(db)
            acceptance = read_acceptance(db, acceptance_id)
            if read_device_outcome(db, acceptance_id) is not None:
                raise StationError('execution_closed', f'acceptance {acceptance_id} is closed')
            return append_sample(db, acceptance, raw_value, source, sequence)

    def deliver(self, lane, sequence):
        with self._store.read() as db:
            _require_online(db)
            return read_delivery(db, lane, sequence)

    def settle(self, lane, through=None):
        with self._store.write() as db:
            _require_online(db)
            return close_device_range(db, lane, through)
