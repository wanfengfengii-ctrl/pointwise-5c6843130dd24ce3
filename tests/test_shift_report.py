from fractions import Fraction

from tests.support import StationCase, rules, scenario, ticket


class ShiftReportTests(StationCase):
    def test_standard_shift(self):
        run = self.play('standard')
        s = self.station
        sheet = run['sheet']
        self.assertEqual((run['left'].micrometers, run['right'].micrometers), (Fraction(7), Fraction(11)))
        self.assertEqual(sheet.results, (run['left'], run['right']))
        self.assertEqual([(row.ticket_id, row.source, row.raw_value, row.ruleset_version) for row in sheet.results],
                         [('L', 'left/40', 14, 'film-v1'), ('R', 'right/40', 33, 'film-v1')])
        self.assertEqual((sheet.count, sheet.mean_micrometers), (2, Fraction(9)))
        self.assertEqual(run['left'].first_receipt.request_id, 'iL')
        self.assertEqual(run['right'].first_receipt.request_id, 'iR')
        self.assertEqual(s.read_result('result:L'), run['left'])
        self.assertEqual(s.read_result('result:R'), run['right'])
        scenario('normal', {'counts': [14, 33], 'factors': ['1/2', '1/3'], 'issue_order': ['R', 'L']},
                 ['7', '11'], [str(row.micrometers) for row in sheet.results],
                 {'count': 2, 'mean': '9', 'order': ['L', 'R'], 'sources': ['left/40', 'right/40']},
                 {'count': sheet.count, 'mean': str(sheet.mean_micrometers),
                  'order': [row.ticket_id for row in sheet.results], 'sources': [row.source for row in sheet.results]},
                 ['station/report/calibration.py', 'station/report/issue.py', 'station/report/shift_sheet.py'],
                 '14 除以 2、33 除以 3；平均为 (7 + 11) / 2；依导入票序列出。')

    def test_exact_fraction(self):
        s = self.station
        s.open_shift('F', rules(left=(1, 3), right=(2, 3)), [ticket('L'), ticket('R', 'right')])
        left = self.take('L', 1, 'left/one', 1)
        right = self.take('R', 1, 'right/one', 1)
        s.accept_sample(left)
        s.accept_sample(right)
        self.close_lane('left')
        self.close_lane('right')
        self.assertEqual(s.issue_ticket('L', 'iL').micrometers, Fraction(1, 3))
        self.assertEqual(s.issue_ticket('R', 'iR').micrometers, Fraction(2, 3))
        s.reopen()
        sheet = s.read_shift('F')
        self.assertEqual(tuple(row.micrometers for row in sheet.results), (Fraction(1, 3), Fraction(2, 3)))
        self.assertEqual((sheet.count, sheet.mean_micrometers), (2, Fraction(1, 2)))
        scenario('normal.exact_fraction', {'counts': [1, 1], 'factors': ['1/3', '2/3']},
                 ['1/3', '2/3'], [str(row.micrometers) for row in sheet.results],
                 {'count': 2, 'mean': '1/2'}, {'count': sheet.count, 'mean': str(sheet.mean_micrometers)},
                 ['station/report/calibration.py', 'station/report/receipts.py', 'station/report/shift_sheet.py'],
                 '两个读数乘固定系数，分子和为 3，均值等于 1 除以 2。')

    def test_empty_shift(self):
        s = self.station
        s.open_shift('E', rules(), [])
        sheet = s.read_shift('E')
        self.assertEqual((sheet.results, sheet.count, sheet.mean_micrometers), ((), 0, None))
        self.rejects('unknown_shift', s.read_shift, 'M')
        self.assertIsNone(s.read_result('result:M'))

    def test_issue_order(self):
        s = self.station
        run = self.play('standard')
        self.assertEqual(s.issue_ticket('R', 'other-R'), run['right'])
        self.rejects('request_conflict', s.issue_ticket, 'L', 'iR')
        self.assertEqual([(row.ticket_id, row.source, row.first_receipt.request_id)
                          for row in s.read_shift('regular').results],
                         [('L', 'left/40', 'iL'), ('R', 'right/40', 'iR')])
        self.assertEqual((run['sheet'].count, run['sheet'].mean_micrometers), (2, Fraction(9)))

    def test_failed_issue_and_offline_read(self):
        s = self.station
        s.open_shift('S', rules(), [ticket('A'), ticket('B')])
        a = self.take('A', 14, 'left/40', 40)
        b = self.take('B', 22, 'left/41', 41)
        s.accept_sample(a)
        s.accept_sample(b)
        self.close_lane('left')
        old = s.issue_ticket('A', 'iA')
        s.fail_next_issue()
        self.rejects('issue_failed', s.issue_ticket, 'B', 'iB')
        evidence = s.read_ticket_evidence('B')
        self.assertEqual((evidence.status, evidence.sample), ('received', b))
        self.assertEqual(s.read_shift_setup('S').tickets[1].state, 'active')
        failed_result = s.read_result('result:B')
        failed_receipt = s.read_receipt('receipt:B')
        failed_sheet = s.read_shift('S')
        self.assertIsNone(failed_result)
        self.assertIsNone(failed_receipt)
        self.assertEqual((failed_sheet.results, failed_sheet.count), ((old,), 1))
        s.reopen()
        result = s.issue_ticket('B', 'iB')
        self.assertEqual(s.issue_ticket('B', 'iB'), result)
        self.assertEqual(result.first_receipt.request_id, 'iB')
        self.assertEqual(s.read_shift_setup('S').tickets[1].state, 'finalized')
        s.device.set_online(False)
        s.reopen()
        self.rejects('device_offline', s.device.deliver, 'left', 41)
        offline = s.read_result(result.result_id)
        self.assertEqual(offline, result)
        self.assertEqual((offline.raw_value, offline.micrometers, offline.source, offline.ruleset_version),
                         (22, Fraction(11), 'left/41', 'film-v1'))
        self.assertEqual(s.read_receipt(result.first_receipt.receipt_id), result.first_receipt)
        self.assertEqual(s.read_result(old.result_id), old)
        sheet = s.read_shift('S')
        self.assertEqual((sheet.results, sheet.count, sheet.mean_micrometers), ((old, result), 2, Fraction(9)))
        scenario('rollback', {'ticket': 'B', 'raw': 22, 'factor': '1/2', 'request': 'iB'},
                 {'failed_result': None, 'failed_receipt': None, 'failed_count': 1},
                 {'failed_result': failed_result, 'failed_receipt': failed_receipt, 'failed_count': failed_sheet.count},
                 {'offline_value': '11', 'source': 'left/41', 'receipt': 'iB', 'count': 2},
                 {'offline_value': str(offline.micrometers), 'source': offline.source,
                  'receipt': offline.first_receipt.request_id, 'count': sheet.count},
                 ['station/report/issue.py', 'station/report/receipts.py', 'station/report/retrieve.py'],
                 '首次只保有已签 A；B 的 22 折半，原请求续签后两张正式票都可核。')
