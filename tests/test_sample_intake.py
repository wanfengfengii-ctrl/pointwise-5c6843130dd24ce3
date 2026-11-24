from dataclasses import replace

from tests.support import StationCase, rules, ticket


class SampleIntakeTests(StationCase):
    def test_duplicate_and_conflicting_sample(self):
        s = self.station
        s.open_shift('S', rules(), [ticket('A')])
        sample = self.take('A', 14, 'left/original', 40)
        first = s.accept_sample(sample)
        self.assertEqual(first.arrival.status, 'pending')
        self.assertFalse(first.duplicate)
        self.close_lane('left')
        duplicate = s.accept_sample(sample)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.arrival.claim.ticket_id, 'A')
        self.rejects('sample_conflict', s.accept_sample, replace(sample, raw_value=22))
        self.rejects('sample_conflict', s.accept_sample, replace(sample, code='Y'))
        s.reopen()
        self.assertEqual(s.read_arrival('left', 40), duplicate.arrival)
        self.assertEqual(s.read_ticket_evidence('A').sample, sample)
        self.assertEqual(s.issue_ticket('A', 'iA').source, 'left/original')
        self.assertEqual(s.read_shift('S').count, 1)

    def test_source_mismatch(self):
        s = self.station
        s.open_shift('S', rules(), [ticket('A')])
        sample = self.take('A', 14, 'left/original', 40)
        self.close_lane('left')
        received = s.accept_sample(sample).arrival
        self.rejects('sample_conflict', s.accept_sample, replace(sample, source='left/changed'))
        self.assertEqual(s.read_arrival('left', 40), received)
        self.assertEqual(s.issue_ticket('A', 'iA').source, 'left/original')

    def test_route_isolation(self):
        s = self.station
        s.open_shift('S', rules(), [ticket('A'), ticket('R', 'right')])
        left = self.take('A', 14, 'left/40', 40)
        right = self.take('R', 33, 'right/40', 40)
        self.assertFalse(s.accept_sample(left).duplicate)
        self.assertFalse(s.accept_sample(right).duplicate)
        self.close_lane('right')
        self.assertEqual(s.read_arrival('right', 40).claim.ticket_id, 'R')
        self.assertEqual(s.read_arrival('left', 40).status, 'pending')
        self.close_lane('left')
        self.assertEqual(s.read_arrival('left', 40).claim.ticket_id, 'A')
        self.assertEqual(s.read_arrival('left', 40).sample.raw_value, 14)
        self.assertEqual(s.read_arrival('right', 40).sample.raw_value, 33)

    def test_claim_conflict_rolls_back_whole_cut(self):
        s = self.station
        s.open_shift('S', rules(), [ticket('A'), ticket('B', code='Y')])
        a = self.take('A', 14, 'left/40', 40)
        b = self.take('B', 22, 'left/41', 41)
        s.accept_sample(a)
        s.accept_sample(replace(b, code='X'))
        cut = s.device.settle('left')
        self.rejects('sample_evidence_conflict', s.settle_lane, cut)
        self.assertEqual(s.read_arrival('left', 40).status, 'pending')
        self.assertEqual(s.read_ticket_evidence('A').status, 'awaiting_settlement')
        self.assertEqual(s.read_ticket_evidence('B').status, 'awaiting_settlement')
        self.assertEqual(s.read_shift('S').count, 0)
        self.assertIsNone(s.read_receipt('receipt:A'))
