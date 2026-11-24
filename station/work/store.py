from contextlib import contextmanager
import sqlite3


LANES = ('left', 'right')
MAX_INDEX = (1 << 63) - 1


class StationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise StationError('invalid_input', f'{label} must be a nonblank string')
    return value


def require_lane(value):
    if value not in LANES:
        raise StationError('invalid_input', 'lane must be left or right')
    return value


def require_index(value, label, minimum=1):
    if type(value) is not int or not minimum <= value <= MAX_INDEX:
        raise StationError('invalid_input', f'{label} is outside the supported integer range')
    return value


def require_integer(value, label):
    if type(value) is not int:
        raise StationError('invalid_input', f'{label} must be an integer')
    return value


class StationStore:
    def __init__(self, path):
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys = ON')

    @contextmanager
    def _transaction(self, begin):
        self.connection.execute(begin)
        try:
            yield self.connection
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def read(self):
        return self._transaction('BEGIN')

    def write(self):
        return self._transaction('BEGIN IMMEDIATE')

    def close(self):
        self.connection.close()
