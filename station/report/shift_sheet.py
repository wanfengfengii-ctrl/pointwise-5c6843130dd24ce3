from dataclasses import dataclass
from fractions import Fraction

from station.report.receipts import IssuedResult, list_issued_results
from station.work.shifts import require_shift
from station.work.tickets import list_shift_tickets


@dataclass(frozen=True)
class ShiftSheet:
    shift_id: str
    results: tuple[IssuedResult, ...]
    count: int
    mean_micrometers: Fraction | None


def read_shift(store, shift_id):
    with store.read() as db:
        require_shift(db, shift_id)
        by_ticket = {result.ticket_id: result for result in list_issued_results(db, shift_id)}
        results = tuple(by_ticket[ticket.ticket_id] for ticket in list_shift_tickets(db, shift_id)
                        if ticket.ticket_id in by_ticket)
        count = len(results)
        mean = sum((result.micrometers for result in results), Fraction()) / count if count else None
        return ShiftSheet(shift_id, results, count, mean)
