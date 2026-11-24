from dataclasses import dataclass, replace
from fractions import Fraction

from station.capture.claims import read_ticket_claim
from station.capture.pending import read_first_sample
from station.dispatch.lanes import read_ticket_outcome
from station.probe.traces import RawSample
from station.report.calibration import calibrate_micrometers
from station.work.rulesets import read_shift_ruleset
from station.work.store import StationError
from station.work.tickets import read_ticket


@dataclass(frozen=True)
class TicketEvidence:
    ticket_id: str
    status: str
    acceptance_id: int | None = None
    sequence: int | None = None
    sample: RawSample | None = None
    micrometers: Fraction | None = None


def _evidence(db, ticket):
    outcome = read_ticket_outcome(db, ticket.ticket_id)
    if outcome is None:
        return TicketEvidence(ticket.ticket_id, 'not_dispatched')
    acceptance_id = outcome.link.acceptance_id
    if outcome.status != 'sampled':
        return TicketEvidence(ticket.ticket_id, outcome.status, acceptance_id)
    claim = read_ticket_claim(db, ticket.ticket_id)
    if claim is None:
        return TicketEvidence(ticket.ticket_id, 'awaiting_sample', acceptance_id, outcome.sequence)
    sample = read_first_sample(db, claim.key)
    return TicketEvidence(ticket.ticket_id, 'received', acceptance_id, outcome.sequence, sample)


def read_ticket_evidence(db, ticket_id):
    ticket = read_ticket(db, ticket_id)
    if ticket.state == 'withdrawn':
        raise StationError('withdrawn', f'ticket {ticket_id} is withdrawn')
    return _evidence(db, ticket)


def read_cancellation_evidence(db, ticket_id):
    ticket = read_ticket(db, ticket_id)
    if ticket.state != 'withdrawn':
        raise StationError('not_withdrawn', f'ticket {ticket_id} is not withdrawn')
    evidence = _evidence(db, ticket)
    if evidence.sample is None:
        return evidence
    # Cancellation evidence is converted with the probe that actually took
    # the sample, which can differ from the registered lane after a swap.
    factor = read_shift_ruleset(db, ticket.shift_id).factor(evidence.sample.lane)
    return replace(evidence, micrometers=calibrate_micrometers(evidence.sample.raw_value, factor))
