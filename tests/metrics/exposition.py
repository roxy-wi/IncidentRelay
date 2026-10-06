from prometheus_client.parser import text_string_to_metric_families


def parse_exposition(body):
    """Parse an exposition body (str or bytes) into name -> family."""

    if isinstance(body, bytes):
        body = body.decode()

    families = {}

    for family in text_string_to_metric_families(body):
        families[family.name] = family

    return families


def sample_value(source, name, labels):
    """Value of one sample, None when it is absent.

    source is a families mapping from parse_exposition() or a raw body.
    Lookup is by sample name, which for counters carries a _total
    suffix that the family name drops.
    """

    families = source if isinstance(source, dict) else parse_exposition(source)

    value = None

    for family in families.values():
        for sample in family.samples:
            if sample.name == name and sample.labels == labels:
                value = sample.value

    return value
