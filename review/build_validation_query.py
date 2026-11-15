"""Rebuild the executed public coverage and contract check from the event audit."""
import csv
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent


def main():
    with (HERE/'event_audit.csv').open() as handle:
        addresses = [json.loads(r['payload'])['sender'] for r in csv.DictReader(handle)
                     if r['section']=='top']
    assert len(set(addresses)) == 100 and all(re.fullmatch('0x[0-9a-f]{40}', a) for a in addresses)
    source = (HERE/'validation_template.sql').read_text()
    (HERE/'validation.sql').write_text(source.replace('__ADDRESSES__', ','.join(f"'{a}'" for a in addresses)))


if __name__ == '__main__':
    main()
