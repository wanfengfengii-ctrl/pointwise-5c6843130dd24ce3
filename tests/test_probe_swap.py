from fractions import Fraction

from station.work.store import StationError
from tests.support import StationCase, rules, ticket


class ProbeSwapTests(StationCase):
    def _pair(self, request_id='sw', lanes_ready=True):
        s = self.station
        s.open_shift('S', rules(), [ticket('P', 'left', 'P'), ticket('A'), ticket('B', 'right', 'X')])
        p = s.dispatch_ticket('P', 'dP').acceptance
        a = s.dispatch_ticket('A', 'dA').acceptance
        b = s.dispatch_ticket('B', 'dB').acceptance
        s.device.sample(p.acceptance_id, 8, 'left/P', 10)
        s.accept_sample(s.device.deliver('left', 10))
        cut = s.device.settle('left', p.ordinal)
        s.settle_lane(cut)
        s.issue_ticket('P', 'iP')
        return a, b, s.swap_probes(request_id, 'A', 'B')

    def test_swap_converts_with_actual_probe_factors(self):
        s = self.station
        a, b, pair = self._pair()
        self.assertEqual((pair['A']['lane'], pair['B']['lane']), ('right', 'left'))
        self.assertIsInstance(pair['A']['credential'], int)
        # old credentials are dead
        with self.assertRaises(StationError):
            s.device.sample(a.acceptance_id, 99, 'old', 20)
        with self.assertRaises(StationError):
            s.device.sample(b.acceptance_id, 99, 'old', 20)
        # new credentials produce the two 7 um values
        s.device.sample(pair['A']['credential'], 21, 'right/A', 20)
        s.device.sample(pair['B']['credential'], 14, 'left/B', 20)
        s.accept_sample(s.device.deliver('left', 20))
        s.accept_sample(s.device.deliver('right', 20))
        s.settle_lane(s.device.settle('left'))
        s.settle_lane(s.device.settle('right'))
        s.issue_ticket('A', 'iA')
        s.issue_ticket('B', 'iB')
        rows = {r.ticket_id: r for r in s.read_shift('S').results}
        self.assertEqual((rows['A'].lane, rows['A'].micrometers), ('right', Fraction(7)))
        self.assertEqual((rows['B'].lane, rows['B'].micrometers), ('left', Fraction(7)))
        # registered ticket lanes / original order are preserved
        self.assertEqual(tuple(t.lane for t in s.read_shift_setup('S').tickets),
                         ('left', 'left', 'right'))

    def test_swap_replay_conflict_and_once_only(self):
        s = self.station
        a, b, pair = self._pair('req')
        self.assertEqual(s.swap_probes('req', 'A', 'B'), pair)
        self.rejects('request_conflict', s.swap_probes, 'req', 'B', 'A')
        with self.assertRaises(StationError):
            s.swap_probes('other', 'B', 'A')
        s.reopen()
        self.assertEqual(s.swap_probes('req', 'A', 'B'), pair)

    def test_device_sampled_rejects_whole_swap(self):
        s = self.station
        s.open_shift('S', rules(), [ticket('A'), ticket('B', 'right')])
        a = s.dispatch_ticket('A', 'dA').acceptance
        b = s.dispatch_ticket('B', 'dB').acceptance
        s.device.sample(a.acceptance_id, 21, 'not-delivered', 20)
        self.rejects('already_sampled', s.swap_probes, 'sw', 'A', 'B')
        self.assertEqual(s.dispatch_status('A').acceptance, a)
        self.assertEqual(s.dispatch_status('B').acceptance, b)

    def test_device_settled_rejects_even_before_import(self):
        s = self.station
        s.open_shift('S', rules(), [ticket('A'), ticket('B', 'right')])
        a = s.dispatch_ticket('A', 'dA').acceptance
        b = s.dispatch_ticket('B', 'dB').acceptance
        s.device.settle('left', a.ordinal)
        self.rejects('execution_closed', s.swap_probes, 'sw', 'A', 'B')
        self.assertEqual(s.dispatch_status('A').acceptance, a)
        self.assertEqual(s.dispatch_status('B').acceptance, b)

    def test_commit_failure_leaves_no_half_swap(self):
        s = self.station
        s.open_shift('S', rules(), [ticket('A'), ticket('B', 'right')])
        a = s.dispatch_ticket('A', 'dA').acceptance
        b = s.dispatch_ticket('B', 'dB').acceptance
        s.fail_next_swap()
        self.rejects('swap_failed', s.swap_probes, 'sw', 'A', 'B')
        self.assertEqual(s.dispatch_status('A').acceptance, a)
        self.assertEqual(s.dispatch_status('B').acceptance, b)
        # original executions remain usable after rollback
        s.device.sample(a.acceptance_id, 14, 'still-left', 20)
        s.device.sample(b.acceptance_id, 21, 'still-right', 20)

    def test_retired_cut_never_marks_ticket_unsampled(self):
        s = self.station
        a, b, pair = self._pair()
        cut = s.device.settle('left', a.ordinal)
        s.settle_lane(cut)
        self.assertNotEqual(s.read_ticket_evidence('A').status, 'unsampled')
        self.rejects('evidence_pending', s.issue_ticket, 'A', 'iA')
        # replay the same cut without conflict
        s.settle_lane(cut)

    def test_cancel_after_swap_uses_actual_probe_factor(self):
        s = self.station
        a, b, pair = self._pair()
        s.device.sample(pair['A']['credential'], 21, 'right/A', 30)
        s.accept_sample(s.device.deliver('right', 30))
        s.settle_lane(s.device.settle('right'))
        s.cancel_ticket('A')
        ev = s.read_cancellation_evidence('A')
        self.assertEqual((ev.status, ev.sample.lane, ev.micrometers),
                         ('received', 'right', Fraction(7)))
        self.assertEqual(s.read_arrival('right', 30).claim.ticket_id, 'A')

    def test_paused_lane_still_swaps_accepted_qualifications(self):
        s = self.station
        s.open_shift('S', rules(), [ticket('A'), ticket('B', 'right')])
        s.dispatch_ticket('A', 'dA')
        s.dispatch_ticket('B', 'dB')
        s.device.set_lane_ready('left', False)
        s.device.set_lane_ready('right', False)
        pair = s.swap_probes('sw', 'A', 'B')
        s.device.sample(pair['A']['credential'], 21, 'right/A', 1)
        s.device.sample(pair['B']['credential'], 14, 'left/B', 1)

    def test_offline_new_swap_rejected_but_replay_served(self):
        s = self.station
        a, b, pair = self._pair('req')
        s.device.set_online(False)
        self.assertEqual(s.swap_probes('req', 'A', 'B'), pair)
        self.rejects('device_offline', s.swap_probes, 'brand-new', 'A', 'B')
