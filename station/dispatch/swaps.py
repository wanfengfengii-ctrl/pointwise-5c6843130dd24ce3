from station.dispatch.lanes import read_dispatch_status, replace_link_for_swap
from station.probe.settlement import read_device_outcome
from station.work.store import StationError, require_text
from station.work.tickets import read_ticket


def ensure_swap_schema(db):
    # One durable result per swap request; replayed by request number even
    # while the device is stopped or after a reopen.
    db.execute('''
        CREATE TABLE IF NOT EXISTS probe_swap_requests (
            request_id TEXT PRIMARY KEY,
            left_ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id),
            right_ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id),
            left_credential INTEGER NOT NULL,
            right_credential INTEGER NOT NULL
        )
    ''')
    # A ticket appears in at most one successful swap.
    db.execute('''
        CREATE TABLE IF NOT EXISTS probe_swap_members (
            ticket_id TEXT PRIMARY KEY REFERENCES tickets(ticket_id),
            request_id TEXT NOT NULL REFERENCES probe_swap_requests(request_id),
            old_acceptance_id INTEGER NOT NULL,
            new_acceptance_id INTEGER NOT NULL UNIQUE
        )
    ''')


def _replay_pair(db, request_id, left_ticket_id, right_ticket_id):
    row = db.execute('SELECT * FROM probe_swap_requests WHERE request_id = ?',
                     (request_id,)).fetchone()
    if row is None:
        return None
    if row['left_ticket_id'] != left_ticket_id or row['right_ticket_id'] != right_ticket_id:
        raise StationError('request_conflict',
                           f'swap request {request_id} already names different tickets')
    return {
        row['left_ticket_id']: {'lane': 'right', 'credential': row['left_credential']},
        row['right_ticket_id']: {'lane': 'left', 'credential': row['right_credential']},
    }


def _accepted_link_on_side(db, ticket, side):
    if ticket.state == 'withdrawn':
        raise StationError('withdrawn', f'ticket {ticket.ticket_id} is withdrawn')
    if ticket.state != 'active':
        raise StationError('ineligible_ticket',
                           f'ticket {ticket.ticket_id} is not eligible for a probe swap')
    status = read_dispatch_status(db, ticket.ticket_id)
    if status is None or status.acceptance is None:
        raise StationError('swap_ineligible',
                           f'ticket {ticket.ticket_id} has no accepted device execution')
    link = status.acceptance
    if link.lane != side:
        raise StationError('swap_ineligible',
                           f'ticket {ticket.ticket_id} is not accepted on the {side} probe')
    return link


def _assert_execution_pristine(db, link):
    # Device-side facts are authoritative: a sample or settlement may not
    # have reached the station yet, but the swap must still be refused.
    sampled = db.execute('SELECT 1 FROM probe_samples WHERE acceptance_id = ?',
                         (link.acceptance_id,)).fetchone()
    if sampled is not None:
        raise StationError('already_sampled',
                           f'execution {link.acceptance_id} was already sampled by the device')
    if read_device_outcome(db, link.acceptance_id) is not None:
        raise StationError('execution_closed',
                           f'execution {link.acceptance_id} was already settled by the device')


def swap_probes(store, device, request_id, left_ticket_id, right_ticket_id, before_commit=None):
    require_text(request_id, 'request_id')
    require_text(left_ticket_id, 'left_ticket_id')
    require_text(right_ticket_id, 'right_ticket_id')
    with store.write() as db:
        # Idempotent replay (and same-number/different-parameter rejection)
        # must work without an online device.
        pair = _replay_pair(db, request_id, left_ticket_id, right_ticket_id)
        if pair is not None:
            return pair

        # A new request is adjudicated by the online device.
        device.assert_online(db)

        left_ticket = read_ticket(db, left_ticket_id)
        right_ticket = read_ticket(db, right_ticket_id)
        if left_ticket.ticket_id == right_ticket.ticket_id:
            raise StationError('invalid_input', 'a probe swap needs two distinct tickets')
        if left_ticket.shift_id != right_ticket.shift_id:
            raise StationError('swap_conflict', 'the two tickets belong to different shifts')
        if left_ticket.code != right_ticket.code:
            raise StationError('swap_conflict', 'the two tickets have different read codes')

        left_link = _accepted_link_on_side(db, left_ticket, 'left')
        right_link = _accepted_link_on_side(db, right_ticket, 'right')

        for ticket_id in (left_ticket.ticket_id, right_ticket.ticket_id):
            prior_swap = db.execute('SELECT 1 FROM probe_swap_members WHERE ticket_id = ?',
                                    (ticket_id,)).fetchone()
            if prior_swap is not None:
                raise StationError('swap_conflict',
                                   f'ticket {ticket_id} already completed a probe swap')

        _assert_execution_pristine(db, left_link)
        _assert_execution_pristine(db, right_link)

        # Deliver the new pair of credentials on the opposite probes. Lane
        # pause does not apply to these already-accepted qualifications.
        left_new = device.accept_swap_credential('right', left_ticket.code, db)
        right_new = device.accept_swap_credential('left', right_ticket.code, db)

        # Revoke both old credentials on the device. Marking the executions
        # closed-unsampled makes late old instructions fail and cannot block
        # later device settlements (the outcome stays sequence-less).
        db.execute('INSERT INTO probe_outcomes(acceptance_id, sequence) VALUES (?, NULL)',
                   (left_link.acceptance_id,))
        db.execute('INSERT INTO probe_outcomes(acceptance_id, sequence) VALUES (?, NULL)',
                   (right_link.acceptance_id,))

        replace_link_for_swap(db, left_ticket.ticket_id, left_new)
        replace_link_for_swap(db, right_ticket.ticket_id, right_new)

        db.execute('INSERT INTO probe_swap_requests VALUES (?, ?, ?, ?, ?)',
                   (request_id, left_ticket.ticket_id, right_ticket.ticket_id,
                    left_new.acceptance_id, right_new.acceptance_id))
        db.execute('INSERT INTO probe_swap_members VALUES (?, ?, ?, ?)',
                   (left_ticket.ticket_id, request_id,
                    left_link.acceptance_id, left_new.acceptance_id))
        db.execute('INSERT INTO probe_swap_members VALUES (?, ?, ?, ?)',
                   (right_ticket.ticket_id, request_id,
                    right_link.acceptance_id, right_new.acceptance_id))

        pair = {
            left_ticket.ticket_id: {'lane': left_new.lane, 'credential': left_new.acceptance_id},
            right_ticket.ticket_id: {'lane': right_new.lane, 'credential': right_new.acceptance_id},
        }
        if before_commit is not None:
            before_commit()
        return pair
