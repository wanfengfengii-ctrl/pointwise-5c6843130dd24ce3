from dataclasses import dataclass

from station.capture.claims import SampleClaim, claim_sample, read_sample_claim
from station.capture.identity import same_sample, validate_sample
from station.capture.pending import read_first_sample, record_first_sample
from station.probe.traces import RawSample
from station.work.store import StationError


@dataclass(frozen=True)
class Arrival:
    sample: RawSample
    claim: SampleClaim | None

    @property
    def status(self):
        return 'pending' if self.claim is None else 'claimed'


@dataclass(frozen=True)
class IntakeResult:
    arrival: Arrival
    duplicate: bool


def read_arrival(db, key):
    sample = read_first_sample(db, key)
    if sample is None:
        return None
    return Arrival(sample, read_sample_claim(db, key))


def accept_sample(store, sample):
    key = validate_sample(sample)
    with store.write() as db:
        previous = read_first_sample(db, key)
        if previous is None:
            record_first_sample(db, sample)
            return IntakeResult(Arrival(sample, claim_sample(db, sample)), False)
        if not same_sample(previous, sample):
            raise StationError('sample_conflict', f'a different sample was already received at {key.lane}/{key.sequence}')
        return IntakeResult(Arrival(previous, read_sample_claim(db, key)), True)
