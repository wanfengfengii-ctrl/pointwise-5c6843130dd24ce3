from fractions import Fraction

from tests.support import StationCase, rules, ticket


class WorkOrderTests(StationCase):
    def test_shift_reimport(self):
        s = self.station
        original = [ticket('R', 'right', 'Y'), ticket('A')]
        setup = s.open_shift('S', rules(), original)
        self.assertEqual(s.open_shift('S', rules(), original), setup)
        changed = [ticket('A', code='Z'), ticket('R', 'right', 'Y'), ticket('N')]
        self.rejects('shift_conflict', s.open_shift, 'S', rules(left=(2, 3)), changed)
        self.rejects('shift_conflict', s.open_shift, 'S', rules(), original[::-1])
        self.rejects('invalid_input', s.open_shift, 'bad', rules(right=(1, 0)), [ticket('N')])
        self.rejects('invalid_input', s.open_shift, 'bad', rules(), [ticket('N'), ticket('Z', 'front')])
        self.rejects('ticket_conflict', s.open_shift, 'bad', rules(), [ticket('N'), ticket('A')])
        s.reopen()
        saved = s.read_shift_setup('S')
        self.assertEqual(saved, setup)
        self.assertEqual([(row.ticket_id, row.position, row.lane, row.code) for row in saved.tickets],
                         [('R', 1, 'right', 'Y'), ('A', 2, 'left', 'X')])
        self.assertEqual((saved.ruleset.version, saved.ruleset.factor('left'), saved.ruleset.factor('right')),
                         ('film-v1', Fraction(1, 2), Fraction(1, 3)))
        self.rejects('unknown_ticket', s.dispatch_ticket, 'N', 'new')
        self.rejects('unknown_shift', s.read_shift_setup, 'bad')

    def test_dispatch_replay(self):
        s = self.station
        specs = [ticket('A'), ticket('B')]
        s.open_shift('S', rules(), specs)
        s.open_shift('S', rules(), specs)
        accepted = s.dispatch_ticket('A', 'dA')
        s.device.set_online(False)
        s.reopen()
        self.assertEqual(s.dispatch_ticket('A', 'dA'), accepted)
        self.assertEqual(s.dispatch_ticket('A', 'alias'), accepted)
        self.rejects('request_conflict', s.dispatch_ticket, 'B', 'dA')
        self.rejects('device_offline', s.device.settle, 'left')
        s.device.set_online(True)
        cut = s.device.settle('left')
        self.assertEqual([item.acceptance_id for item in cut.items], [accepted.acceptance.acceptance_id])
        self.assertEqual(s.dispatch_ticket('B', 'dB').acceptance.ordinal, 2)

    def test_lane_wait(self):
        s = self.station
        s.open_shift('S', rules(), [ticket('A'), ticket('R', 'right'), ticket('W')])
        s.device.set_lane_ready('left', False)
        waiting = s.dispatch_ticket('A', 'dA')
        self.assertEqual((waiting.status, waiting.acceptance), ('waiting', None))
        self.assertEqual(s.device.settle('left').items, ())
        self.assertEqual(s.dispatch_ticket('R', 'dR').status, 'accepted')
        self.assertEqual(s.dispatch_ticket('W', 'dW').status, 'waiting')
        self.assertEqual(s.cancel_ticket('W').ticket.state, 'withdrawn')
        self.assertEqual(s.read_cancellation_evidence('W').status, 'not_dispatched')
        self.rejects('withdrawn', s.dispatch_ticket, 'W', 'dW')
        s.reopen()
        self.assertEqual(s.dispatch_ticket('A', 'dA'), waiting)
        s.device.set_lane_ready('left', True)
        accepted = s.dispatch_ticket('A', 'dA')
        self.assertEqual(accepted.acceptance.ordinal, 1)
        self.assertEqual(s.dispatch_ticket('A', 'dA'), accepted)
        self.assertEqual(len(s.device.settle('left').items), 1)
