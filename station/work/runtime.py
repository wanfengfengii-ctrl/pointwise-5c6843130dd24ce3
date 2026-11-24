import argparse
from dataclasses import asdict, is_dataclass
from fractions import Fraction
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from station.capture.claims import ensure_claim_schema
from station.capture.evidence import read_cancellation_evidence, read_ticket_evidence
from station.capture.identity import SampleKey
from station.capture.intake import accept_sample, read_arrival
from station.capture.pending import ensure_sample_schema
from station.dispatch.cancellations import cancel_ticket
from station.dispatch.lanes import ensure_dispatch_schema, read_dispatch_status
from station.dispatch.orders import dispatch_ticket
from station.dispatch.reconcile import settle_lane
from station.probe.device import ProbeDevice, ensure_device_schema
from station.probe.recording import load_recording, replay_recording
from station.probe.settlement import ensure_settlement_schema
from station.probe.traces import ensure_trace_schema
from station.report.issue import issue_ticket
from station.report.receipts import ensure_result_schema, load_receipt
from station.report.retrieve import read_result
from station.report.shift_sheet import read_shift
from station.work.requests import ensure_request_schema
from station.work.rulesets import ensure_ruleset_schema
from station.work.shifts import ensure_shift_schema, open_shift, read_shift_setup
from station.work.store import StationError, StationStore, require_index, require_lane, require_text
from station.work.tickets import ensure_ticket_schema, read_ticket


class Station:
    def __init__(self, path):
        self.path = path
        self._issue_failure = False
        self._connect()

    def _connect(self):
        store = StationStore(self.path)
        try:
            with store.write() as db:
                for ensure in (ensure_shift_schema, ensure_ruleset_schema, ensure_ticket_schema,
                               ensure_request_schema, ensure_trace_schema, ensure_settlement_schema,
                               ensure_device_schema, ensure_dispatch_schema, ensure_sample_schema,
                               ensure_claim_schema, ensure_result_schema):
                    ensure(db)
        except BaseException:
            store.close()
            raise
        self._store = store
        self.device = ProbeDevice(store)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self._store.close()

    def reopen(self):
        self.close()
        self._issue_failure = False
        self._connect()

    def play_recording(self, recording):
        return replay_recording(self, recording)

    def open_shift(self, shift_id, ruleset, tickets):
        return open_shift(self._store, shift_id, ruleset, tickets)

    def read_shift_setup(self, shift_id):
        with self._store.read() as db:
            return read_shift_setup(db, shift_id)

    def dispatch_ticket(self, ticket_id, request_id):
        return dispatch_ticket(self._store, self.device, ticket_id, request_id)

    def dispatch_status(self, ticket_id):
        with self._store.read() as db:
            read_ticket(db, ticket_id)
            return read_dispatch_status(db, ticket_id)

    def cancel_ticket(self, ticket_id):
        return cancel_ticket(self._store, ticket_id)

    def accept_sample(self, sample):
        return accept_sample(self._store, sample)

    def read_arrival(self, lane, sequence):
        key = SampleKey(require_lane(lane), require_index(sequence, 'sample sequence'))
        with self._store.read() as db:
            return read_arrival(db, key)

    def settle_lane(self, cut):
        return settle_lane(self._store, cut)

    def read_ticket_evidence(self, ticket_id):
        with self._store.read() as db:
            return read_ticket_evidence(db, ticket_id)

    def read_cancellation_evidence(self, ticket_id):
        with self._store.read() as db:
            return read_cancellation_evidence(db, ticket_id)

    def issue_ticket(self, ticket_id, request_id):
        return issue_ticket(self._store, ticket_id, request_id, self._before_issue_commit)

    def fail_next_issue(self):
        self._issue_failure = True

    def _before_issue_commit(self):
        if self._issue_failure:
            self._issue_failure = False
            raise StationError('issue_failed', 'the issue transaction was interrupted before commit')

    def read_shift(self, shift_id):
        return read_shift(self._store, shift_id)

    def read_result(self, result_id):
        return read_result(self._store, result_id)

    def read_receipt(self, receipt_id):
        require_text(receipt_id, 'receipt_id')
        with self._store.read() as db:
            return load_receipt(db, receipt_id)


def open_station(path):
    return Station(path)


def _json_value(value):
    if isinstance(value, Fraction):
        return str(value)
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f'unsupported JSON value {type(value).__name__}')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run a dual-probe shift recording')
    commands = parser.add_subparsers(dest='command', required=True)
    demo = commands.add_parser('demo', help='replay a recording in a fresh temporary station')
    demo.add_argument('recording', type=Path)
    options = parser.parse_args(argv)
    recording = load_recording(options.recording)
    with TemporaryDirectory(prefix='thickness-demo-') as workspace:
        with open_station(Path(workspace) / 'station.sqlite') as station:
            station.play_recording(recording)
            setup = station.read_shift_setup(recording.shift_id)
            sheet = station.read_shift(recording.shift_id)
            output = {
                'shift_sheet': sheet,
                'retrieved_results': [station.read_result(row.result_id) for row in sheet.results],
                'withdrawals': [station.read_cancellation_evidence(ticket.ticket_id)
                                for ticket in setup.tickets if ticket.state == 'withdrawn'],
            }
            print(json.dumps(output, default=_json_value, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
