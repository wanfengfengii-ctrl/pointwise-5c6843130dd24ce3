from dataclasses import dataclass

from station.work.store import StationError, require_text


@dataclass(frozen=True)
class RequestRecord:
    ticket_id: str
    reference: str | None


def ensure_request_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            operation TEXT NOT NULL,
            request_id TEXT NOT NULL,
            ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id),
            reference TEXT,
            PRIMARY KEY (operation, request_id)
        )
    ''')


def read_request(db, operation, request_id, ticket_id):
    require_text(request_id, 'request_id')
    row = db.execute('''
        SELECT ticket_id, reference FROM requests WHERE operation = ? AND request_id = ?
    ''', (operation, request_id)).fetchone()
    if row is None:
        return None
    if row['ticket_id'] != ticket_id:
        raise StationError('request_conflict', f'{operation} request {request_id} names a different ticket')
    return RequestRecord(**dict(row))


def record_request(db, operation, request_id, ticket_id, reference=None):
    previous = read_request(db, operation, request_id, ticket_id)
    if previous is None:
        db.execute('INSERT INTO requests VALUES (?, ?, ?, ?)',
                   (operation, request_id, ticket_id, reference))
    elif previous.reference != reference:
        raise StationError('request_conflict', f'{operation} request {request_id} has a different reference')
