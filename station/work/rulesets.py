from dataclasses import dataclass
from fractions import Fraction

from station.work.store import LANES, StationError, require_integer, require_lane, require_text


@dataclass(frozen=True)
class Ruleset:
    version: str
    left: tuple[int, int]
    right: tuple[int, int]

    def factor(self, lane):
        require_lane(lane)
        return Fraction(*getattr(self, lane))


def ensure_ruleset_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS shift_rules (
            shift_id TEXT PRIMARY KEY REFERENCES shifts(shift_id),
            version TEXT NOT NULL,
            left_numerator TEXT NOT NULL,
            left_denominator TEXT NOT NULL,
            right_numerator TEXT NOT NULL,
            right_denominator TEXT NOT NULL
        )
    ''')


def validate_ruleset(spec):
    if not isinstance(spec, dict) or set(spec) != {'version', 'factors'}:
        raise StationError('invalid_input', 'a ruleset needs version and factors')
    version = require_text(spec['version'], 'ruleset version')
    factors = spec['factors']
    if not isinstance(factors, dict) or set(factors) != set(LANES):
        raise StationError('invalid_input', 'ruleset must cover both lanes')
    components = []
    for lane in LANES:
        pair = factors[lane]
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise StationError('invalid_input', f'{lane} factor needs two integers')
        numerator = require_integer(pair[0], f'{lane} numerator')
        denominator = require_integer(pair[1], f'{lane} denominator')
        if denominator == 0:
            raise StationError('invalid_input', f'{lane} denominator must be nonzero')
        components.append((numerator, denominator))
    return Ruleset(version, *components)


def bind_shift_ruleset(db, shift_id, ruleset):
    factors = tuple(str(value) for value in (*ruleset.left, *ruleset.right))
    db.execute('INSERT INTO shift_rules VALUES (?, ?, ?, ?, ?, ?)', (shift_id, ruleset.version, *factors))


def read_shift_ruleset(db, shift_id):
    row = db.execute('SELECT * FROM shift_rules WHERE shift_id = ?', (shift_id,)).fetchone()
    if row is None:
        raise StationError('unknown_shift', f'no ruleset for shift {shift_id}')
    return Ruleset(row['version'], (int(row['left_numerator']), int(row['left_denominator'])),
                   (int(row['right_numerator']), int(row['right_denominator'])))
