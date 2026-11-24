from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class FirstReceipt:
    receipt_id: str
    result_id: str
    request_id: str


@dataclass(frozen=True)
class IssuedResult:
    result_id: str
    ticket_id: str
    shift_id: str
    lane: str
    code: str
    sequence: int
    raw_value: int
    source: str
    ruleset_version: str
    micrometers: Fraction
    first_receipt: FirstReceipt


_RESULT_QUERY = '''
    SELECT i.*, r.receipt_id, r.request_id FROM issued_results i JOIN first_receipts r USING (result_id)
'''


def ensure_result_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS issued_results (
            result_id TEXT PRIMARY KEY,
            ticket_id TEXT NOT NULL UNIQUE REFERENCES tickets(ticket_id),
            shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
            lane TEXT NOT NULL,
            code TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            raw_value TEXT NOT NULL,
            source TEXT NOT NULL,
            ruleset_version TEXT NOT NULL,
            numerator TEXT NOT NULL,
            denominator TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS first_receipts (
            receipt_id TEXT PRIMARY KEY,
            result_id TEXT NOT NULL UNIQUE REFERENCES issued_results(result_id),
            request_id TEXT NOT NULL
        )
    ''')


def save_issued_result(db, result):
    db.execute('INSERT INTO issued_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
               (result.result_id, result.ticket_id, result.shift_id, result.lane, result.code,
                result.sequence, str(result.raw_value), result.source, result.ruleset_version,
                str(result.micrometers.numerator), str(result.micrometers.denominator)))
    receipt = result.first_receipt
    db.execute('INSERT INTO first_receipts VALUES (?, ?, ?)',
               (receipt.receipt_id, receipt.result_id, receipt.request_id))


def _result(row):
    if row is None:
        return None
    receipt = FirstReceipt(row['receipt_id'], row['result_id'], row['request_id'])
    micrometers = Fraction(int(row['numerator']), int(row['denominator']))
    return IssuedResult(row['result_id'], row['ticket_id'], row['shift_id'], row['lane'], row['code'],
                        row['sequence'], int(row['raw_value']), row['source'], row['ruleset_version'],
                        micrometers, receipt)


def load_issued_result(db, result_id):
    return _result(db.execute(_RESULT_QUERY + ' WHERE i.result_id = ?', (result_id,)).fetchone())


def read_ticket_result(db, ticket_id):
    return _result(db.execute(_RESULT_QUERY + ' WHERE i.ticket_id = ?', (ticket_id,)).fetchone())


def list_issued_results(db, shift_id):
    rows = db.execute(_RESULT_QUERY + ' WHERE i.shift_id = ?', (shift_id,))
    return tuple(_result(row) for row in rows)


def load_receipt(db, receipt_id):
    row = db.execute('SELECT * FROM first_receipts WHERE receipt_id = ?', (receipt_id,)).fetchone()
    return None if row is None else FirstReceipt(**dict(row))
