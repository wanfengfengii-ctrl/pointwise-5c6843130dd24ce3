"""Run the project's checks from the repository root.

This keeps the original unittest regression and additionally replays the
pre-swap probe exchange trajectory together with its rejection boundaries.
"""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


def run_unittest_suite():
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    if suite.countTestCases():
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        print('No tests discovered in tests/', file=sys.stderr)
        result = unittest.TestResult()
    for status, failed_cases in (
        ('FAIL', (test for test, _ in result.failures)),
        ('ERROR', (test for test, _ in result.errors)),
        ('UNEXPECTED_SUCCESS', result.unexpectedSuccesses),
    ):
        for test in failed_cases:
            print(f'{status} {test.id()}')
    successful = result.testsRun > 0 and result.wasSuccessful()
    print(f'TEST SUMMARY total={result.testsRun} failures={len(result.failures)} '
          f'errors={len(result.errors)} skipped={len(result.skipped)} '
          f'expected_failures={len(result.expectedFailures)} '
          f'unexpected_successes={len(result.unexpectedSuccesses)} '
          f'result={"PASS" if successful else "FAIL"}')
    return successful


def run_swap_verification():
    # Imported lazily so unittest discovery/collection never depends on the
    # root-level fixture being importable during test module imports.
    import probe_swap_case
    from station.work.runtime import open_station

    with TemporaryDirectory(prefix='check-probe-swap-') as folder:
        root = Path(folder)
        with open_station(root / 'main.sqlite') as station:
            probe_swap_case.swap_case(station)
        for boundary in ('sampled', 'settled', 'commit'):
            with open_station(root / f'{boundary}.sqlite') as station:
                probe_swap_case.boundary_case(station, boundary)
    print('SWAP SUMMARY result=PASS '
          'trajectory="P,A,B,N -> 4,7,7,9" boundaries="sampled,settled,commit"')
    return True


def main():
    unit_ok = run_unittest_suite()
    try:
        swap_ok = run_swap_verification()
    except BaseException:
        import traceback
        traceback.print_exc()
        print('SWAP SUMMARY result=FAIL')
        swap_ok = False
    if unit_ok and swap_ok:
        print('CHECK PROJECT result=PASS')
        return 0
    print('CHECK PROJECT result=FAIL')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
