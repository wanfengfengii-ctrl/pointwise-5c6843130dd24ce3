from station.capture.identity import SampleKey, sample_key
from station.probe.traces import RawSample


def ensure_sample_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS first_samples (
            lane TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            code TEXT NOT NULL,
            raw_value TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY (lane, sequence)
        )
    ''')


def record_first_sample(db, sample):
    key = sample_key(sample)
    db.execute('INSERT INTO first_samples VALUES (?, ?, ?, ?, ?)',
               (key.lane, key.sequence, sample.code, str(sample.raw_value), sample.source))


def read_first_sample(db, key):
    row = db.execute('''
        SELECT code, raw_value, source FROM first_samples WHERE lane = ? AND sequence = ?
    ''', (key.lane, key.sequence)).fetchone()
    if row is None:
        return None
    return RawSample(key.lane, row['code'], key.sequence, int(row['raw_value']), row['source'])


def read_lane_arrivals(db, lane, sequences):
    for sequence in sorted(sequences):
        sample = read_first_sample(db, SampleKey(lane, sequence))
        if sample is not None:
            yield sample
