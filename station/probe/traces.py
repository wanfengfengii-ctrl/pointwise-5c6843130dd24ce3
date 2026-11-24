from dataclasses import dataclass

from station.work.store import StationError, require_index, require_integer, require_lane, require_text


@dataclass(frozen=True)
class DeviceAcceptance:
    acceptance_id: int
    lane: str
    ordinal: int
    code: str


@dataclass(frozen=True)
class RawSample:
    lane: str
    code: str
    sequence: int
    raw_value: int
    source: str


def ensure_trace_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS probe_acceptances (
            acceptance_id INTEGER PRIMARY KEY,
            lane TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            code TEXT NOT NULL,
            UNIQUE (lane, ordinal)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS probe_samples (
            acceptance_id INTEGER NOT NULL UNIQUE REFERENCES probe_acceptances(acceptance_id),
            lane TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            raw_value TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY (lane, sequence)
        )
    ''')


def append_acceptance(db, lane, code):
    require_lane(lane)
    require_text(code, 'code')
    last = db.execute('SELECT max(ordinal) FROM probe_acceptances WHERE lane = ?', (lane,)).fetchone()[0]
    ordinal = require_index((last or 0) + 1, 'acceptance ordinal')
    inserted = db.execute('INSERT INTO probe_acceptances(lane, ordinal, code) VALUES (?, ?, ?)',
                          (lane, ordinal, code))
    return DeviceAcceptance(inserted.lastrowid, lane, ordinal, code)


def read_acceptance(db, acceptance_id):
    require_index(acceptance_id, 'acceptance_id')
    row = db.execute('SELECT * FROM probe_acceptances WHERE acceptance_id = ?', (acceptance_id,)).fetchone()
    if row is None:
        raise StationError('unknown_acceptance', f'unknown device acceptance {acceptance_id}')
    return DeviceAcceptance(**dict(row))


def append_sample(db, acceptance, raw_value, source, sequence=None):
    require_integer(raw_value, 'raw value')
    require_text(source, 'source')
    if db.execute('SELECT 1 FROM probe_samples WHERE acceptance_id = ?', (acceptance.acceptance_id,)).fetchone():
        raise StationError('already_sampled', f'acceptance {acceptance.acceptance_id} already sampled')
    lane = acceptance.lane
    last = db.execute('SELECT max(sequence) FROM probe_samples WHERE lane = ?', (lane,)).fetchone()[0] or 0
    sequence = require_index(last + 1 if sequence is None else sequence, 'sample sequence')
    if sequence <= last:
        raise StationError('sequence_conflict', f'sample sequence must advance on {lane}')
    db.execute('INSERT INTO probe_samples VALUES (?, ?, ?, ?, ?)',
               (acceptance.acceptance_id, lane, sequence, str(raw_value), source))
    return RawSample(lane, acceptance.code, sequence, raw_value, source)


def read_lane_executions(db, lane):
    rows = db.execute('''
        SELECT a.acceptance_id, a.lane, a.ordinal, a.code, s.sequence
        FROM probe_acceptances a LEFT JOIN probe_samples s USING (acceptance_id)
        WHERE a.lane = ? ORDER BY a.ordinal
    ''', (lane,))
    return tuple((DeviceAcceptance(row['acceptance_id'], row['lane'], row['ordinal'], row['code']),
                  row['sequence']) for row in rows)


def read_delivery(db, lane, sequence):
    require_lane(lane)
    require_index(sequence, 'sample sequence')
    row = db.execute('''
        SELECT a.code, s.raw_value, s.source
        FROM probe_samples s JOIN probe_acceptances a USING (acceptance_id)
        WHERE s.lane = ? AND s.sequence = ?
    ''', (lane, sequence)).fetchone()
    if row is None:
        raise StationError('unknown_sample', f'no device sample at {lane}/{sequence}')
    return RawSample(lane, row['code'], sequence, int(row['raw_value']), row['source'])
