from dataclasses import dataclass
import json

from station.work.rulesets import Ruleset, bind_shift_ruleset, read_shift_ruleset, validate_ruleset
from station.work.store import StationError, require_text
from station.work.tickets import Ticket, list_shift_tickets, register_shift_tickets, validate_ticket_specs


@dataclass(frozen=True)
class ShiftSetup:
    shift_id: str
    ruleset: Ruleset
    tickets: tuple[Ticket, ...]


def ensure_shift_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            shift_id TEXT PRIMARY KEY,
            import_spec TEXT NOT NULL
        )
    ''')


def require_shift(db, shift_id):
    require_text(shift_id, 'shift_id')
    row = db.execute('SELECT import_spec FROM shifts WHERE shift_id = ?', (shift_id,)).fetchone()
    if row is None:
        raise StationError('unknown_shift', f'unknown shift {shift_id}')
    return row['import_spec']


def read_shift_setup(db, shift_id):
    require_shift(db, shift_id)
    return ShiftSetup(shift_id, read_shift_ruleset(db, shift_id), list_shift_tickets(db, shift_id))


def open_shift(store, shift_id, ruleset, tickets):
    require_text(shift_id, 'shift_id')
    validated_rules = validate_ruleset(ruleset)
    validated_tickets = validate_ticket_specs(tickets)
    import_spec = json.dumps([validated_rules.version, validated_rules.left,
                              validated_rules.right, validated_tickets], ensure_ascii=False)
    with store.write() as db:
        existing = db.execute('SELECT import_spec FROM shifts WHERE shift_id = ?', (shift_id,)).fetchone()
        if existing is None:
            db.execute('INSERT INTO shifts VALUES (?, ?)', (shift_id, import_spec))
            bind_shift_ruleset(db, shift_id, validated_rules)
            register_shift_tickets(db, shift_id, validated_tickets)
        elif existing['import_spec'] != import_spec:
            raise StationError('shift_conflict', f'shift {shift_id} already has a different configuration')
        return read_shift_setup(db, shift_id)
