from dataclasses import dataclass
from sqlite3 import IntegrityError

from station.work.store import StationError


@dataclass(frozen=True)
class DispatchLink:
    ticket_id: str
    acceptance_id: int
    lane: str
    ordinal: int
    code: str


@dataclass(frozen=True)
class DispatchStatus:
    ticket_id: str
    lane: str
    status: str
    acceptance: DispatchLink | None = None


@dataclass(frozen=True)
class DispatchOutcome:
    link: DispatchLink
    status: str
    sequence: int | None


_LINK_FIELDS = 'l.ticket_id, l.acceptance_id, l.lane, l.ordinal, l.code'
_OUTCOMES = f'''
    SELECT {_LINK_FIELDS}, o.acceptance_id AS settled_id, o.sequence
    FROM dispatch_links l LEFT JOIN dispatch_outcomes o USING (acceptance_id)
'''


def ensure_dispatch_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS dispatch_waits (
            ticket_id TEXT PRIMARY KEY REFERENCES tickets(ticket_id),
            lane TEXT NOT NULL
        )
    ''')
    # A ticket normally has one current link. A probe swap retires the old
    # acceptance link and inserts a new generation on the opposite lane; the
    # retired row is retained so pre-swap settlement cuts keep their meaning.
    db.execute('''
        CREATE TABLE IF NOT EXISTS dispatch_links (
            ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id),
            acceptance_id INTEGER PRIMARY KEY,
            lane TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            code TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'current' CHECK (state IN ('current', 'retired')),
            UNIQUE (lane, ordinal)
        )
    ''')
    db.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS dispatch_links_one_current
        ON dispatch_links(ticket_id) WHERE state = 'current'
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS dispatch_outcomes (
            acceptance_id INTEGER PRIMARY KEY REFERENCES dispatch_links(acceptance_id),
            lane TEXT NOT NULL,
            sequence INTEGER,
            UNIQUE (lane, sequence)
        )
    ''')


def record_lane_wait(db, ticket):
    db.execute('INSERT OR IGNORE INTO dispatch_waits VALUES (?, ?)', (ticket.ticket_id, ticket.lane))
    return DispatchStatus(ticket.ticket_id, ticket.lane, 'waiting')


def clear_lane_wait(db, ticket_id):
    db.execute('DELETE FROM dispatch_waits WHERE ticket_id = ?', (ticket_id,))


def record_acceptance_link(db, ticket, acceptance):
    if (ticket.lane, ticket.code) != (acceptance.lane, acceptance.code):
        raise StationError('acceptance_conflict', 'acceptance lane or code differs from the ticket')
    link = DispatchLink(ticket.ticket_id, acceptance.acceptance_id, acceptance.lane,
                        acceptance.ordinal, acceptance.code)
    try:
        db.execute('''
            INSERT INTO dispatch_links(ticket_id, acceptance_id, lane, ordinal, code, state)
            VALUES (?, ?, ?, ?, ?, 'current')
        ''', (link.ticket_id, link.acceptance_id, link.lane, link.ordinal, link.code))
    except IntegrityError as exc:
        raise StationError('acceptance_conflict', 'acceptance or ticket is already bound') from exc
    clear_lane_wait(db, ticket.ticket_id)
    return DispatchStatus(ticket.ticket_id, ticket.lane, 'accepted', link)


def replace_link_for_swap(db, ticket_id, acceptance):
    """Retire the ticket's current link and bind a swap credential."""
    db.execute("UPDATE dispatch_links SET state = 'retired' WHERE ticket_id = ? AND state = 'current'",
               (ticket_id,))
    link = DispatchLink(ticket_id, acceptance.acceptance_id, acceptance.lane,
                        acceptance.ordinal, acceptance.code)
    db.execute('''
        INSERT INTO dispatch_links(ticket_id, acceptance_id, lane, ordinal, code, state)
        VALUES (?, ?, ?, ?, ?, 'current')
    ''', (link.ticket_id, link.acceptance_id, link.lane, link.ordinal, link.code))
    return link


def read_dispatch_status(db, ticket_id):
    row = db.execute(
        f"SELECT {_LINK_FIELDS} FROM dispatch_links l WHERE l.ticket_id = ? AND l.state = 'current'",
        (ticket_id,)).fetchone()
    if row is not None:
        link = DispatchLink(**dict(row))
        return DispatchStatus(ticket_id, link.lane, 'accepted', link)
    waiting = db.execute('SELECT lane FROM dispatch_waits WHERE ticket_id = ?', (ticket_id,)).fetchone()
    if waiting is not None:
        return DispatchStatus(ticket_id, waiting['lane'], 'waiting')
    return None


def read_lane_links(db, lane, through):
    # Every generation is returned: a settlement prefix is defined by the
    # device acceptance order, which still includes swapped-out executions.
    rows = db.execute(f'''
        SELECT {_LINK_FIELDS}
        FROM dispatch_links l WHERE l.lane = ? AND l.ordinal <= ? ORDER BY l.ordinal
    ''', (lane, through))
    return tuple(DispatchLink(**dict(row)) for row in rows)


def _outcome(row):
    if row is None:
        return None
    link = DispatchLink(row['ticket_id'], row['acceptance_id'], row['lane'], row['ordinal'], row['code'])
    if row['settled_id'] is None:
        return DispatchOutcome(link, 'awaiting_settlement', None)
    sequence = row['sequence']
    return DispatchOutcome(link, 'unsampled' if sequence is None else 'sampled', sequence)


def read_ticket_outcome(db, ticket_id):
    row = db.execute(_OUTCOMES + " WHERE l.ticket_id = ? AND l.state = 'current'",
                     (ticket_id,)).fetchone()
    return _outcome(row)


def read_acceptance_outcome(db, acceptance_id):
    row = db.execute(_OUTCOMES + ' WHERE l.acceptance_id = ?', (acceptance_id,)).fetchone()
    return _outcome(row)


def read_sample_outcome(db, lane, sequence):
    row = db.execute(_OUTCOMES + ' WHERE o.lane = ? AND o.sequence = ?', (lane, sequence)).fetchone()
    return _outcome(row)


def record_lane_outcomes(db, outcomes):
    db.executemany('''
        INSERT INTO dispatch_outcomes(acceptance_id, lane, sequence) VALUES (?, ?, ?)
        ON CONFLICT(acceptance_id) DO NOTHING
    ''', ((outcome.link.acceptance_id, outcome.link.lane, outcome.sequence) for outcome in outcomes))
