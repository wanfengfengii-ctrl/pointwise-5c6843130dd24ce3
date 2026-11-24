from dataclasses import dataclass
from sqlite3 import IntegrityError

from station.work.store import StationError, require_lane, require_text


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    shift_id: str
    position: int
    lane: str
    code: str
    state: str


def ensure_ticket_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
            position INTEGER NOT NULL,
            lane TEXT NOT NULL,
            code TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('active', 'withdrawn', 'finalized')),
            UNIQUE (shift_id, position)
        )
    ''')


def validate_ticket_specs(tickets):
    if not isinstance(tickets, (list, tuple)):
        raise StationError('invalid_input', 'tickets must be an ordered list')
    specifications = []
    seen = set()
    for spec in tickets:
        if not isinstance(spec, dict) or set(spec) != {'ticket_id', 'lane', 'code'}:
            raise StationError('invalid_input', 'a ticket needs ticket_id, lane and code')
        ticket_id = require_text(spec['ticket_id'], 'ticket_id')
        if ticket_id in seen:
            raise StationError('ticket_conflict', f'duplicate ticket {ticket_id} in shift')
        specifications.append((ticket_id, require_lane(spec['lane']), require_text(spec['code'], 'code')))
        seen.add(ticket_id)
    return tuple(specifications)


def register_shift_tickets(db, shift_id, specifications):
    try:
        db.executemany('''
            INSERT INTO tickets(ticket_id, shift_id, position, lane, code, state)
            VALUES (?, ?, ?, ?, ?, 'active')
        ''', ((ticket_id, shift_id, position, lane, code)
              for position, (ticket_id, lane, code) in enumerate(specifications, 1)))
    except IntegrityError as exc:
        raise StationError('ticket_conflict', 'a ticket is already registered') from exc


def read_ticket(db, ticket_id):
    require_text(ticket_id, 'ticket_id')
    row = db.execute('SELECT * FROM tickets WHERE ticket_id = ?', (ticket_id,)).fetchone()
    if row is None:
        raise StationError('unknown_ticket', f'unknown ticket {ticket_id}')
    return Ticket(**dict(row))


def list_shift_tickets(db, shift_id):
    rows = db.execute('SELECT * FROM tickets WHERE shift_id = ? ORDER BY position', (shift_id,))
    return tuple(Ticket(**dict(row)) for row in rows)


def withdraw_ticket(db, ticket_id):
    ticket = read_ticket(db, ticket_id)
    if ticket.state == 'active':
        db.execute("UPDATE tickets SET state = 'withdrawn' WHERE ticket_id = ?", (ticket_id,))
        return read_ticket(db, ticket_id)
    return ticket


def finalize_ticket(db, ticket_id):
    updated = db.execute("UPDATE tickets SET state = 'finalized' WHERE ticket_id = ? AND state = 'active'",
                         (ticket_id,))
    if updated.rowcount != 1:
        raise StationError('ineligible_ticket', f'ticket {ticket_id} cannot be finalized')
