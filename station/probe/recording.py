from dataclasses import dataclass
import json
from pathlib import Path

from station.work.store import StationError


@dataclass(frozen=True)
class Recording:
    shift_id: str
    ruleset: dict
    tickets: tuple[dict, ...]
    events: tuple[tuple, ...]


def load_recording(path):
    with Path(path).open(encoding='utf-8') as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or set(data) != {'shift', 'events'}:
        raise StationError('invalid_recording', 'recording needs shift and events')
    setup = data['shift']
    if not isinstance(setup, dict) or set(setup) != {'id', 'ruleset', 'tickets'}:
        raise StationError('invalid_recording', 'shift needs id, ruleset and tickets')
    if not isinstance(setup['tickets'], list) or not isinstance(data['events'], list):
        raise StationError('invalid_recording', 'tickets and events must be arrays')
    events = []
    labels = set()
    for event in data['events']:
        if (not isinstance(event, list) or len(event) < 2
                or not all(isinstance(value, str) and value for value in event[:2])):
            raise StationError('invalid_recording', 'each event needs a step name and an action')
        if event[0] in labels:
            raise StationError('invalid_recording', f'duplicate step {event[0]}')
        labels.add(event[0])
        events.append(tuple(event))
    return Recording(setup['id'], setup['ruleset'], tuple(setup['tickets']), tuple(events))


def replay_recording(station, recording):
    station.open_shift(recording.shift_id, recording.ruleset, recording.tickets)

    def sample(ticket_id, raw_value, source, sequence=None):
        dispatch = station.dispatch_status(ticket_id)
        if dispatch is None or dispatch.acceptance is None:
            raise StationError('invalid_recording', f'no accepted dispatch for {ticket_id}')
        return station.device.sample(dispatch.acceptance.acceptance_id, raw_value, source, sequence)

    def deliver(lane, sequence):
        return station.accept_sample(station.device.deliver(lane, sequence))

    def settle(lane, through=None):
        return station.settle_lane(station.device.settle(lane, through))

    def try_issue(ticket_id, request_id, expected_code):
        try:
            station.issue_ticket(ticket_id, request_id)
        except StationError as exc:
            if exc.code == expected_code:
                return exc.code
            raise
        raise StationError('unexpected_issue', f'{ticket_id} signed while expecting {expected_code}')

    handlers = {
        'dispatch': station.dispatch_ticket,
        'sample': sample,
        'deliver': deliver,
        'settle': settle,
        'cancel': station.cancel_ticket,
        'withdrawal': station.read_cancellation_evidence,
        'evidence': station.read_ticket_evidence,
        'issue': station.issue_ticket,
        'try_issue': try_issue,
        'fail_issue': station.fail_next_issue,
        'swap': station.swap_probes,
        'swap_probes': station.swap_probes,
        'fail_swap': station.fail_next_swap,
        'arrival': station.read_arrival,
        'result': station.read_result,
        'receipt': station.read_receipt,
        'sheet': lambda: station.read_shift(recording.shift_id),
        'online': lambda enabled: station.device.set_online(enabled),
        'lane_ready': lambda lane, ready: station.device.set_lane_ready(lane, ready),
        'reopen': station.reopen,
    }
    observed = {}
    for label, action, *args in recording.events:
        handler = handlers.get(action)
        if handler is None:
            raise StationError('invalid_recording', f'{label} names unknown action {action}')
        try:
            observed[label] = handler(*args)
        except Exception as exc:
            exc.add_note(f'recording step {label} ({action})')
            raise
    return observed
