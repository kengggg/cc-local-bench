"""Thai phone number utilities."""


def format_phone_number(input_str: str) -> str:
    """Convert a Thai phone number to canonical international format.

    Canonical format: '+66-XXX-XXX-XXX'
        (country code 66, plus 9 digits split into 3-3-3 groups, separated by hyphens)

    Accepted input forms (whitespace, dashes, parens, dots, and a leading '+' are stripped):
        - National format with leading 0:    '0812345678'      (10 digits total)
        - International with '+':             '+66812345678'   (12 chars)
        - International without '+':          '66812345678'    (11 digits)

    Examples:
        >>> format_phone_number('0812345678')
        '+66-812-345-678'
        >>> format_phone_number('+66 81 234 5678')
        '+66-812-345-678'

    Raises:
        ValueError: if the input cannot be parsed as a valid Thai phone number
                    (i.e. does not yield exactly 9 digits after the country code).
    """
    raise NotImplementedError("Implement me — see test_phone_utils.py for expected behaviour.")
