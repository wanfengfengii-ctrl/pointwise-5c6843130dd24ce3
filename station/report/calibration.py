from fractions import Fraction


def calibrate_micrometers(raw_value: int, factor: Fraction) -> Fraction:
    return raw_value * factor
