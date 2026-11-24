from dataclasses import dataclass

from station.capture.identity import SampleKey, sample_key
from station.capture.pending import read_lane_arrivals
from station.dispatch.lanes import read_sample_outcome
from station.work.store import StationError


@dataclass(frozen=True)
class SampleClaim:
    key: SampleKey
    ticket_id: str
    acceptance_id: int


def ensure_claim_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS sample_claims (
            lane TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            ticket_id TEXT NOT NULL UNIQUE REFERENCES tickets(ticket_id),
            acceptance_id INTEGER NOT NULL UNIQUE,
            PRIMARY KEY (lane, sequence),
            FOREIGN KEY (lane, sequence) REFERENCES first_samples(lane, sequence)
        )
    ''')


def _claim(row):
    if row is None:
        return None
    return SampleClaim(SampleKey(row['lane'], row['sequence']), row['ticket_id'], row['acceptance_id'])


def read_sample_claim(db, key):
    row = db.execute('SELECT * FROM sample_claims WHERE lane = ? AND sequence = ?',
                     (key.lane, key.sequence)).fetchone()
    return _claim(row)


def read_ticket_claim(db, ticket_id):
    row = db.execute('SELECT * FROM sample_claims WHERE ticket_id = ?', (ticket_id,)).fetchone()
    return _claim(row)


def claim_sample(db, sample):
    key = sample_key(sample)
    existing = read_sample_claim(db, key)
    outcome = read_sample_outcome(db, key.lane, key.sequence)
    if outcome is None:
        return None
    link = outcome.link
    if (link.lane, link.code) != (sample.lane, sample.code):
        raise StationError('sample_evidence_conflict', f'code differs from verified execution at {key.lane}/{key.sequence}')
    claim = SampleClaim(key, link.ticket_id, link.acceptance_id)
    if existing is not None:
        if existing != claim:
            raise StationError('sample_evidence_conflict', 'verified evidence differs from the original claim')
        return existing
    if read_ticket_claim(db, link.ticket_id) is not None:
        raise StationError('sample_evidence_conflict', f'ticket {link.ticket_id} already has another sample')
    db.execute('INSERT INTO sample_claims VALUES (?, ?, ?, ?)',
               (key.lane, key.sequence, claim.ticket_id, claim.acceptance_id))
    return claim


def claim_lane_samples(db, lane, sequences):
    return tuple(claim_sample(db, sample) for sample in read_lane_arrivals(db, lane, sequences))
