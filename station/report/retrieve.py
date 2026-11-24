from station.report.receipts import load_issued_result
from station.work.store import require_text


def read_result(store, result_id):
    require_text(result_id, 'result_id')
    with store.read() as db:
        return load_issued_result(db, result_id)
