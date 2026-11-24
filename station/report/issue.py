from station.capture.evidence import read_ticket_evidence
from station.report.calibration import calibrate_micrometers
from station.report.receipts import (FirstReceipt, IssuedResult, load_issued_result,
                                     read_ticket_result, save_issued_result)
from station.work.requests import read_request, record_request
from station.work.rulesets import read_shift_ruleset
from station.work.store import StationError
from station.work.tickets import finalize_ticket, read_ticket


def issue_ticket(store, ticket_id, request_id, before_commit=None):
    with store.write() as db:
        ticket = read_ticket(db, ticket_id)
        previous = read_request(db, 'issue', request_id, ticket_id)
        if previous is not None:
            return load_issued_result(db, previous.reference)
        if ticket.state == 'finalized':
            result = read_ticket_result(db, ticket_id)
            record_request(db, 'issue', request_id, ticket_id, result.result_id)
            return result
        evidence = read_ticket_evidence(db, ticket_id)
        if evidence.status == 'unsampled':
            raise StationError('unsampled', f'ticket {ticket_id} did not produce a sample')
        if evidence.sample is None:
            raise StationError('evidence_pending', f'ticket {ticket_id} is {evidence.status}')
        sample = evidence.sample
        ruleset = read_shift_ruleset(db, ticket.shift_id)
        micrometers = calibrate_micrometers(sample.raw_value, ruleset.factor(ticket.lane))
        result_id = f'result:{ticket_id}'
        receipt = FirstReceipt(f'receipt:{ticket_id}', result_id, request_id)
        result = IssuedResult(result_id, ticket_id, ticket.shift_id, sample.lane, sample.code,
                              sample.sequence, sample.raw_value, sample.source, ruleset.version,
                              micrometers, receipt)
        save_issued_result(db, result)
        finalize_ticket(db, ticket_id)
        record_request(db, 'issue', request_id, ticket_id, result_id)
        if before_commit is not None:
            before_commit()
        return result
