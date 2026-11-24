from station.dispatch.lanes import read_dispatch_status, record_acceptance_link, record_lane_wait
from station.work.requests import read_request, record_request
from station.work.store import StationError
from station.work.tickets import read_ticket


def dispatch_ticket(store, device, ticket_id, request_id):
    with store.write() as db:
        ticket = read_ticket(db, ticket_id)
        previous = read_request(db, 'dispatch', request_id, ticket_id)
        if ticket.state == 'withdrawn':
            raise StationError('withdrawn', f'ticket {ticket_id} is withdrawn')
        status = read_dispatch_status(db, ticket_id)
        if previous is None:
            record_request(db, 'dispatch', request_id, ticket_id)
        if status is not None and status.acceptance is not None:
            return status
        acceptance = device.accept(ticket.lane, ticket.code, connection=db)
        if acceptance is None:
            return record_lane_wait(db, ticket)
        return record_acceptance_link(db, ticket, acceptance)
