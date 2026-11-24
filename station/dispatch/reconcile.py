from station.capture.claims import claim_lane_samples
from station.dispatch.lanes import (DispatchOutcome, read_lane_links, read_sample_outcome,
                                    read_ticket_outcome, record_lane_outcomes)
from station.probe.settlement import LaneSettlement, SettlementItem
from station.work.store import StationError, require_index, require_lane


def _validate_cut(cut):
    if not isinstance(cut, LaneSettlement) or not isinstance(cut.items, tuple):
        raise StationError('invalid_coverage', 'expected a LaneSettlement with a tuple of items')
    require_lane(cut.lane)
    require_index(cut.through, 'acceptance cutoff', minimum=0)
    by_acceptance = {}
    sequences = set()
    for item in cut.items:
        if not isinstance(item, SettlementItem):
            raise StationError('invalid_coverage', 'expected a SettlementItem')
        require_index(item.acceptance_id, 'acceptance_id')
        if item.acceptance_id in by_acceptance:
            raise StationError('invalid_coverage', 'acceptance occurs twice in the cut')
        by_acceptance[item.acceptance_id] = item
        if item.sequence is not None:
            require_index(item.sequence, 'sample sequence')
            if item.sequence in sequences:
                raise StationError('settlement_conflict', 'sample sequence occurs twice in the cut')
            sequences.add(item.sequence)
    return by_acceptance, sequences


def _verified_outcomes(db, cut, items):
    links = read_lane_links(db, cut.lane, cut.through)
    if len(links) != cut.through or {link.acceptance_id for link in links} != items.keys():
        raise StationError('invalid_coverage', f'cut does not cover the stated acceptances on {cut.lane}')
    outcomes = []
    for link in links:
        sequence = items[link.acceptance_id].sequence
        status = 'unsampled' if sequence is None else 'sampled'
        previous = read_ticket_outcome(db, link.ticket_id)
        if previous.status != 'awaiting_settlement' and (previous.status, previous.sequence) != (status, sequence):
            raise StationError('settlement_conflict', f'outcome changed for acceptance {link.acceptance_id}')
        if sequence is not None:
            owner = read_sample_outcome(db, cut.lane, sequence)
            if owner is not None and owner.link.acceptance_id != link.acceptance_id:
                raise StationError('settlement_conflict', f'{cut.lane}/{sequence} already has an acceptance')
        outcomes.append(DispatchOutcome(link, status, sequence))
    return tuple(outcomes)


def settle_lane(store, cut):
    items, sequences = _validate_cut(cut)
    with store.write() as db:
        outcomes = _verified_outcomes(db, cut, items)
        record_lane_outcomes(db, outcomes)
        claim_lane_samples(db, cut.lane, sequences)
        return outcomes
