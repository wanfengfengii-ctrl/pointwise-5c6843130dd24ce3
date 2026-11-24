from dataclasses import dataclass

from station.dispatch.lanes import DispatchOutcome, clear_lane_wait, read_ticket_outcome
from station.work.tickets import Ticket, withdraw_ticket


@dataclass(frozen=True)
class CancellationStatus:
    ticket: Ticket
    outcome: DispatchOutcome | None


def cancel_ticket(store, ticket_id):
    with store.write() as db:
        ticket = withdraw_ticket(db, ticket_id)
        if ticket.state == 'withdrawn':
            clear_lane_wait(db, ticket_id)
        return CancellationStatus(ticket, read_ticket_outcome(db, ticket_id))
