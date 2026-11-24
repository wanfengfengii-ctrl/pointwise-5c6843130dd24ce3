from fractions import Fraction

from station.probe.settlement import LaneSettlement, SettlementItem
from tests.support import StationCase, rules, scenario, ticket


class CaptureHandoffTests(StationCase):
    def test_cancel_after_capture(self):
        s = self.station
        run = self.play('cancel_late')
        self.assertEqual(run['withdraw_a'].ticket.state, 'withdrawn')
        self.assertNotEqual(run['send_a'].acceptance.acceptance_id, run['send_b'].acceptance.acceptance_id)
        self.assertEqual(run['first'].arrival.status, 'pending')
        self.assertEqual(run['early_issue'], 'evidence_pending')
        self.assertIsNone(run['early_result'])
        self.assertIsNone(run['early_receipt'])
        self.assertEqual(run['early_sheet'].count, 0)
        self.assertEqual(run['b_waits'].status, 'awaiting_sample')
        a, b, sheet = run['a'], run['b'], run['sheet']
        self.assertEqual((a.status, a.sample.raw_value, a.sample.source, a.micrometers),
                         ('received', 14, 'left/40', Fraction(7)))
        self.assertEqual(a.acceptance_id, run['send_a'].acceptance.acceptance_id)
        self.assertEqual((b.ticket_id, b.sequence, b.raw_value, b.source, b.micrometers),
                         ('B', 41, 22, 'left/41', Fraction(11)))
        self.assertEqual(b.first_receipt.request_id, 'iB')
        self.assertEqual(s.read_receipt('receipt:B'), b.first_receipt)
        self.assertEqual(s.read_result('result:B'), b)
        self.rejects('withdrawn', s.issue_ticket, 'A', 'iA')
        self.assertIsNone(s.read_receipt('receipt:A'))
        self.assertEqual((sheet.results, sheet.count, sheet.mean_micrometers), ((b,), 1, Fraction(11)))
        scenario('cancel_late', {'raw_by_sequence': {'40': 14, '41': 22}, 'factor': '1/2'},
                 {'A': ['7', 'left/40'], 'B': ['11', 'left/41']},
                 {'A': [str(a.micrometers), a.sample.source], 'B': [str(b.micrometers), b.source]},
                 {'tickets': ['B'], 'count': 1, 'mean': '11', 'receipt': 'iB'},
                 {'tickets': [row.ticket_id for row in sheet.results], 'count': sheet.count,
                  'mean': str(sheet.mean_micrometers), 'receipt': b.first_receipt.request_id},
                 ['station/dispatch/reconcile.py', 'station/capture/claims.py', 'station/report/issue.py'],
                 '结清把 40 归 A、41 归 B；14 与 22 分别折半，撤单票排除出班表。')

    def test_cancel_before_capture(self):
        s = self.station
        run = self.play('cancel_unsampled')
        self.assertEqual(run['unknown_a'].status, 'awaiting_settlement')
        self.assertEqual(run['first'].arrival.status, 'pending')
        self.assertEqual(run['early_issue'], 'evidence_pending')
        self.assertEqual([(item.link.ticket_id, item.status) for item in run['part']], [('A', 'unsampled')])
        self.assertEqual(run['a'].status, 'unsampled')
        self.assertIsNone(run['a'].sample)
        self.assertIsNone(run['a'].micrometers)
        self.assertEqual(run['still_pending'].status, 'pending')
        self.assertEqual(run['b_after_part'].status, 'awaiting_settlement')
        self.assertEqual(run['early_again'], 'evidence_pending')
        self.assertIsNone(run['early_receipt'])
        self.assertEqual([(item.link.ticket_id, item.status, item.sequence) for item in run['complete']],
                         [('A', 'unsampled', None), ('B', 'sampled', 40)])
        self.assertEqual((run['b'].micrometers, run['b'].source), (Fraction(11), 'left/40'))
        self.assertEqual(run['b'].first_receipt.request_id, 'iB')
        self.assertEqual(run['sheet'].results, (run['b'],))
        self.rejects('execution_closed', s.device.sample, run['send_a'].acceptance.acceptance_id, 14, 'left/late')
        self.assertEqual(self.close_lane('left', 1), run['part'])

    def test_pending_lane_reopen(self):
        s = self.station
        run = self.play('reopen')
        self.assertEqual(run['left_first'].arrival.status, 'pending')
        self.assertEqual(run['left_second'].arrival.status, 'pending')
        self.assertEqual(run['left_waits'], 'evidence_pending')
        self.assertEqual(run['while_waiting'].results, (run['r'],))
        self.assertEqual((run['r'].micrometers, run['r'].source), (Fraction(7), 'right/40'))
        self.assertEqual(run['stored_pending'], run['left_second'].arrival)
        resolved = run['resolved_before_replay']
        self.assertEqual((resolved.status, resolved.sample.sequence, resolved.sample.source),
                         ('received', 41, 'left/41'))
        for name, ticket_id in (('replay_a', 'A'), ('replay_b', 'B')):
            self.assertTrue(run[name].duplicate)
            self.assertEqual(run[name].arrival.claim.ticket_id, ticket_id)
        self.assertEqual(run['failed_issue'], 'issue_failed')
        self.assertEqual(run['after_failure'].results, (run['r'],))
        self.assertIsNone(run['failed_receipt'])
        self.assertIsNone(run['failed_result'])
        self.assertEqual(run['offline_r'], run['r'])
        self.assertEqual(run['offline_b'], run['b'])
        self.assertEqual(run['offline_b'].first_receipt.request_id, 'iB')
        self.assertEqual((run['a'].micrometers, run['a'].sample.source), (Fraction(7), 'left/40'))
        self.assertEqual((run['b'].micrometers, run['b'].source), (Fraction(11), 'left/41'))
        self.assertEqual((run['sheet'].results, run['sheet'].count, run['sheet'].mean_micrometers),
                         ((run['r'], run['b']), 2, Fraction(9)))
        self.rejects('device_offline', s.device.settle, 'left')

    def test_settlement_first(self):
        s = self.station
        s.open_shift('S', rules(), [ticket('A'), ticket('B')])
        a = self.take('A', 14, 'left/40', 40)
        s.cancel_ticket('A')
        self.close_lane('left', 1)
        evidence = s.read_cancellation_evidence('A')
        self.assertEqual((evidence.status, evidence.sequence, evidence.sample), ('awaiting_sample', 40, None))
        s.reopen()
        b = self.take('B', 22, 'left/41', 41)
        self.assertEqual(s.accept_sample(a).arrival.claim.ticket_id, 'A')
        self.rejects('evidence_pending', s.issue_ticket, 'B', 'iB')
        self.assertIsNone(s.read_receipt('receipt:B'))
        self.close_lane('left')
        self.assertEqual(s.read_ticket_evidence('B').status, 'awaiting_sample')
        self.assertEqual(s.accept_sample(b).arrival.claim.ticket_id, 'B')
        result = s.issue_ticket('B', 'iB')
        note = s.read_cancellation_evidence('A')
        self.assertEqual((note.sample.raw_value, note.sample.source, note.micrometers),
                         (14, 'left/40', Fraction(7)))
        self.assertEqual((result.raw_value, result.source, result.micrometers, result.first_receipt.request_id),
                         (22, 'left/41', Fraction(11), 'iB'))
        self.assertEqual(s.read_shift('S').results, (result,))

    def test_reverse_delivery(self):
        s = self.station
        s.open_shift('S', rules(), [ticket('A'), ticket('B')])
        self.take('A', 14, 'left/40', 40)
        s.cancel_ticket('A')
        self.take('B', 22, 'left/41', 41)
        self.assertEqual(s.accept_sample(s.device.deliver('left', 41)).arrival.status, 'pending')
        self.assertEqual(s.accept_sample(s.device.deliver('left', 40)).arrival.status, 'pending')
        self.rejects('evidence_pending', s.issue_ticket, 'B', 'iB')
        self.close_lane('left')
        a = s.read_cancellation_evidence('A')
        b = s.issue_ticket('B', 'iB')
        self.assertEqual((a.sample.raw_value, a.sample.source, a.micrometers), (14, 'left/40', Fraction(7)))
        self.assertEqual((b.raw_value, b.source, b.micrometers), (22, 'left/41', Fraction(11)))
        self.assertEqual(s.read_receipt('receipt:B'), b.first_receipt)
        self.assertEqual(s.read_shift('S').results, (b,))

    def test_conflicting_cut(self):
        s = self.station
        s.open_shift('S', rules(), [ticket('A'), ticket('B'), ticket('R', 'right')])
        a = self.take('A', 14, 'left/40', 40)
        s.cancel_ticket('A')
        original = self.close_lane('left', 1)[0]
        b = self.take('B', 22, 'left/41', 41)
        s.accept_sample(b)
        valid = s.device.settle('left')
        a_item, b_item = valid.items
        right = s.dispatch_ticket('R', 'dR').acceptance
        self.rejects('invalid_coverage', s.settle_lane,
                     LaneSettlement('left', 2, (a_item, SettlementItem(right.acceptance_id, 41))))
        self.rejects('invalid_coverage', s.settle_lane, LaneSettlement('left', 2, (a_item,)))
        self.rejects('settlement_conflict', s.settle_lane,
                     LaneSettlement('left', 2, (SettlementItem(a_item.acceptance_id, 42), b_item)))
        self.rejects('settlement_conflict', s.settle_lane,
                     LaneSettlement('left', 2, (a_item, SettlementItem(b_item.acceptance_id, 40))))
        self.assertEqual(s.read_arrival('left', 41).status, 'pending')
        self.assertEqual(self.close_lane('left', 1), (original,))
        self.assertEqual(s.read_shift('S').results, ())
        s.settle_lane(valid)
        s.accept_sample(a)
        self.assertEqual(s.read_cancellation_evidence('A').sample.source, 'left/40')
        self.assertEqual(s.issue_ticket('B', 'iB').source, 'left/41')

    def test_finalized_cancel(self):
        run = self.play('cancel_late')
        s = self.station
        finalized = s.cancel_ticket('B')
        self.assertEqual(finalized.ticket.state, 'finalized')
        self.assertEqual(s.read_result(run['b'].result_id), run['b'])
        self.assertEqual(s.read_receipt('receipt:B'), run['b'].first_receipt)
        self.assertEqual(s.issue_ticket('B', 'iB'), run['b'])
        self.rejects('not_withdrawn', s.read_cancellation_evidence, 'B')
        self.rejects('unknown_ticket', s.cancel_ticket, 'unknown')
