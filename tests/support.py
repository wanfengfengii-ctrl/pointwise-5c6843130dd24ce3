import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from station.probe.recording import load_recording
from station.work.runtime import open_station
from station.work.store import StationError


SAMPLES = Path(__file__).resolve().parents[1] / 'samples'


def ticket(ticket_id, lane='left', code='X'):
    return {'ticket_id': ticket_id, 'lane': lane, 'code': code}


def rules(left=(1, 2), right=(1, 3), version='film-v1'):
    return {'version': version, 'factors': {'left': list(left), 'right': list(right)}}


def scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual, code_paths, oracle):
    record = {'case_id': case_id, 'input': inputs, 'expected': expected, 'actual': actual,
              'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
              'code_paths': code_paths, 'oracle': oracle}
    print('POINTWISE_SCENARIO ' + json.dumps(record, ensure_ascii=False, sort_keys=True))


class StationCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='thickness-test-')
        self.addCleanup(directory.cleanup)
        self.station = open_station(Path(directory.name) / 'station.sqlite')
        self.addCleanup(self.station.close)

    def play(self, name):
        return self.station.play_recording(load_recording(SAMPLES / f'{name}.json'))

    def take(self, ticket_id, raw_value, source, sequence):
        dispatch = self.station.dispatch_ticket(ticket_id, f'dispatch-{ticket_id}')
        self.assertEqual(dispatch.status, 'accepted')
        return self.station.device.sample(dispatch.acceptance.acceptance_id, raw_value, source, sequence)

    def close_lane(self, lane, through=None):
        return self.station.settle_lane(self.station.device.settle(lane, through))

    def rejects(self, code, call, *args):
        with self.assertRaises(StationError) as caught:
            call(*args)
        self.assertEqual(caught.exception.code, code)
