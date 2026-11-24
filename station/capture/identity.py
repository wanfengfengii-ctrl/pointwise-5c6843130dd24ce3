from dataclasses import dataclass

from station.probe.traces import RawSample
from station.work.store import StationError, require_index, require_integer, require_lane, require_text


@dataclass(frozen=True)
class SampleKey:
    lane: str
    sequence: int


def sample_key(sample):
    return SampleKey(sample.lane, sample.sequence)


def validate_sample(sample):
    if not isinstance(sample, RawSample):
        raise StationError('invalid_input', 'expected a RawSample')
    require_lane(sample.lane)
    require_index(sample.sequence, 'sample sequence')
    require_text(sample.code, 'code')
    require_integer(sample.raw_value, 'raw value')
    require_text(sample.source, 'source')
    return sample_key(sample)


def same_sample(left, right):
    return (sample_key(left) == sample_key(right)
            and (left.code, left.raw_value, left.source) == (right.code, right.raw_value, right.source))
