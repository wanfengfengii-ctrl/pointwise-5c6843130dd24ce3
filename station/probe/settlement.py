from dataclasses import dataclass

from station.probe.traces import read_lane_executions
from station.work.store import StationError, require_index, require_lane


@dataclass(frozen=True)
class SettlementItem:
    acceptance_id: int
    sequence: int | None


@dataclass(frozen=True)
class LaneSettlement:
    lane: str
    through: int
    items: tuple[SettlementItem, ...]


def ensure_settlement_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS probe_outcomes (
            acceptance_id INTEGER PRIMARY KEY REFERENCES probe_acceptances(acceptance_id),
            sequence INTEGER
        )
    ''')


def read_device_outcome(db, acceptance_id):
    row = db.execute('SELECT sequence FROM probe_outcomes WHERE acceptance_id = ?', (acceptance_id,)).fetchone()
    if row is None:
        return None
    return SettlementItem(acceptance_id, row['sequence'])


def close_device_range(db, lane, through=None):
    require_lane(lane)
    executions = read_lane_executions(db, lane)
    if through is None:
        through = len(executions)
    require_index(through, 'acceptance cutoff', minimum=0)
    if through > len(executions):
        raise StationError('invalid_coverage', f'cut exceeds device acceptances on {lane}')
    items = []
    for acceptance, sequence in executions[:through]:
        actual = SettlementItem(acceptance.acceptance_id, sequence)
        previous = read_device_outcome(db, acceptance.acceptance_id)
        if previous is None:
            db.execute('INSERT INTO probe_outcomes VALUES (?, ?)', (actual.acceptance_id, actual.sequence))
        elif previous != actual:
            raise StationError('settlement_conflict', f'device outcome changed for {actual.acceptance_id}')
        items.append(actual)
    return LaneSettlement(lane, through, tuple(items))
