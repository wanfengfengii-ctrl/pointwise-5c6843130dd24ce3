from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import json

from station.work.runtime import open_station
from station.work.store import StationError

SHIFT = "probe-swap"
REQUEST = "swap-1"


def prepare(station):
    rules = {"version": "film-v1", "factors": {"left": [1, 2], "right": [1, 3]}}
    tickets = [{"ticket_id": name, "lane": lane, "code": code} for name, lane, code in (
        ("P", "left", "P"), ("A", "left", "X"), ("B", "right", "X"), ("N", "left", "X"),
    )]
    station.open_shift(SHIFT, rules, tickets)
    p, a, b = (station.dispatch_ticket(name, f"d-{name}").acceptance for name in ("P", "A", "B"))
    station.device.sample(p.acceptance_id, 8, "left/P", 10)
    station.accept_sample(station.device.deliver("left", 10))
    old_cut = station.device.settle("left", p.ordinal)
    station.settle_lane(old_cut)
    return a, b, old_cut, station.issue_ticket("P", "i-P")


def rejects(call, *args):
    try:
        call(*args)
    except StationError:
        return
    raise AssertionError(f"{call.__name__} accepted {args!r}")


def settle(station, lane):
    station.settle_lane(station.device.settle(lane))


def v1_case(station):
    a, b, _, _ = prepare(station)
    for link, value in ((a, 21), (b, 14)):
        packet = station.device.sample(link.acceptance_id, value, f"{link.lane}/V1", 20)
        station.accept_sample(packet)
        settle(station, link.lane)
        station.issue_ticket(link.ticket_id, f"i-{link.ticket_id}")
    sheet = station.read_shift(SHIFT)
    assert tuple((row.ticket_id, row.micrometers) for row in sheet.results) == (
        ("P", Fraction(4)), ("A", Fraction(21, 2)), ("B", Fraction(14, 3)),
    ), sheet
    return sheet


def swap_case(station):
    a, b, old_cut, earlier_result = prepare(station)
    station.fail_next_swap()
    rejects(station.swap_probes, REQUEST, "A", "B")
    assert station.dispatch_status("A").acceptance == a
    assert station.dispatch_status("B").acceptance == b
    pair = station.swap_probes(REQUEST, "A", "B")
    assert set(pair) == {"A", "B"}
    assert (pair["A"]["lane"], pair["B"]["lane"]) == ("right", "left")
    rejects(station.swap_probes, REQUEST, "B", "A")
    rejects(station.swap_probes, "another-swap", "A", "B")
    for original in (a, b):
        rejects(station.device.sample, original.acceptance_id, 99, "queued-old", 20)

    station.device.sample(pair["A"]["credential"], 21, "right/A", 20)
    station.device.sample(pair["B"]["credential"], 14, "left/B", 20)
    rejects(station.device.sample, pair["B"]["credential"], 98, "repeat-B", 21)
    n = station.dispatch_ticket("N", "d-N").acceptance
    station.device.sample(n.acceptance_id, 18, "left/N", 21)
    station.accept_sample(station.device.deliver("left", 20))
    station.settle_lane(old_cut)
    partial = station.device.settle("left", a.ordinal)
    station.settle_lane(partial)
    b_is_covered = any(item.sequence == 20 for item in partial.items)
    expected_status = "received" if b_is_covered else "awaiting_settlement"
    assert station.read_ticket_evidence("B").status == expected_status
    settle(station, "right")
    assert station.read_ticket_evidence("A").status == "awaiting_sample"
    station.accept_sample(station.device.deliver("right", 20))
    station.accept_sample(station.device.deliver("left", 21))
    settle(station, "left")
    station.settle_lane(old_cut)

    for name in ("B", "N", "A"):
        station.issue_ticket(name, f"i-{name}")
    sheet = station.read_shift(SHIFT)
    assert tuple((r.ticket_id, r.lane, r.sequence, r.raw_value, r.source, r.micrometers)
                 for r in sheet.results) == (
        ("P", "left", 10, 8, "left/P", Fraction(4)),
        ("A", "right", 20, 21, "right/A", Fraction(7)),
        ("B", "left", 20, 14, "left/B", Fraction(7)),
        ("N", "left", 21, 18, "left/N", Fraction(9)),
    ), sheet
    assert (sheet.count, sheet.mean_micrometers) == (4, Fraction(27, 4))
    assert sheet.results[0] == earlier_result
    assert tuple(t.lane for t in station.read_shift_setup(SHIFT).tickets) == (
        "left", "left", "right", "left",
    )
    station.device.set_online(False)
    station.reopen()
    assert station.swap_probes(REQUEST, "A", "B") == pair
    assert station.read_shift(SHIFT) == sheet
    retrieved = []
    for expected in sheet.results:
        actual = station.read_result(expected.result_id)
        assert actual == expected
        assert station.read_receipt(actual.first_receipt.receipt_id) == expected.first_receipt
        retrieved.append(actual)
    return {"early_cut": old_cut.through, "partial_cut": partial.through,
            "b_at_partial_cut": expected_status, "shift": sheet, "offline_results": retrieved}


def boundary_case(station, boundary):
    a, b, _, _ = prepare(station)
    if boundary == "sampled":
        station.device.sample(a.acceptance_id, 21, "not-delivered", 20)
    elif boundary == "settled":
        station.device.settle("left", a.ordinal)
    else:
        station.fail_next_swap()
    assert station.read_ticket_evidence("A").status == "awaiting_settlement"
    rejects(station.swap_probes, REQUEST, "A", "B")
    assert station.dispatch_status("A").acceptance == a
    assert station.dispatch_status("B").acceptance == b
    if boundary == "commit":
        station.device.sample(a.acceptance_id, 14, "still-left", 20)
    station.device.sample(b.acceptance_id, 21, "still-right", 20)


def encode(value):
    return str(value) if isinstance(value, Fraction) else asdict(value)


def main():
    parser = argparse.ArgumentParser(description="Replay the two-probe swap fixture")
    parser.add_argument("mode", choices=("v1", "verify", "demo"))
    mode = parser.parse_args().mode
    with TemporaryDirectory(prefix="film-swap-") as folder:
        root = Path(folder)
        with open_station(root / "main.sqlite") as station:
            output = v1_case(station) if mode == "v1" else swap_case(station)
        if mode == "verify":
            for boundary in ("sampled", "settled", "commit"):
                with open_station(root / f"{boundary}.sqlite") as station:
                    boundary_case(station, boundary)
    print(json.dumps(output, default=encode, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
