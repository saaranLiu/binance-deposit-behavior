"""Check the frozen stratified sample against Etherscan public name tags."""
from concurrent.futures import ThreadPoolExecutor
import csv
from hashlib import sha256
from html import unescape
import json
from pathlib import Path
import re
import subprocess
import time
import argparse
from collections import defaultdict

HERE = Path(__file__).resolve().parent
TITLE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)
CHALLENGE = re.compile(r'just a moment|access denied|security verification|request blocked', re.I)


def lookup(address):
    url = f'https://etherscan.io/address/{address}'
    result = dict(address=address, source=url, status='unresolved')
    try:
        request = ['curl','--silent','--show-error','--location','--max-time','16',
                   '--write-out','\n%{http_code}',url]
        run = subprocess.run(request,capture_output=True,check=False,timeout=19)
        html, _, status = run.stdout.rpartition(b'\n')
        if status == b'429':
            time.sleep(15)
            run = subprocess.run(request,capture_output=True,check=False,timeout=19)
            html, _, status = run.stdout.rpartition(b'\n')
        result['http'] = int(status) if status.isdigit() else None
        result['sha256'] = sha256(html).hexdigest()
        document = html.decode(errors='replace')
        match = TITLE.search(document)
        if result['http'] != 200 or match is None:
            return result
        title = ' '.join(unescape(match.group(1)).split())
        if CHALLENGE.search(title) or address not in document.lower():
            return result
        label = title.split('|', 1)[0].split(': 0x', 1)[0].strip()
        result['name_tag'] = label if label.lower() != 'address' else ''
        if re.fullmatch(r'Binance\s+Deposit', label, re.I):
            result['status'] = 'confirmed'
        elif re.search(r'\bdeposit\b', label, re.I) and not re.search('Binance', label, re.I):
            result['status'] = 'other_venue'
    except subprocess.TimeoutExpired as exc:
        result['error'] = type(exc).__name__
    return result


def main():
    options = argparse.ArgumentParser()
    options.add_argument('--output', type=Path, default=HERE/'explorer_labels.jsonl')
    options.add_argument('--sample', choices=('label_sample','top','early'), default='label_sample')
    args = options.parse_args()
    with (HERE / 'event_audit.csv').open() as handle:
        rows = [json.loads(row['payload']) for row in csv.DictReader(handle)
                if row['section'] == args.sample]
    if args.sample == 'early':
        totals = defaultdict(float)
        for row in rows:
            if row['cohort_status'] == 'screened':
                totals[row['sender']] += row['usd']
        sample = sorted(totals,key=lambda key:(-totals[key],key))[:5]
        count = 5
    else:
        field, count = ('dst',252) if args.sample == 'label_sample' else ('sender',100)
        sample = [row[field] for row in rows]
    assert len(sample) == len(set(sample)) == count
    target = args.output
    completed = {}
    if target.exists():
        for line in target.read_text().splitlines():
            row = json.loads(line)
            if row.get('http') == 200:
                completed[row['address']] = row
    with ThreadPoolExecutor(max_workers=4) as pool, target.open('a') as out:
        for result in pool.map(lookup, (a for a in sample if a not in completed)):
            out.write(json.dumps(result, ensure_ascii=False) + '\n')
            out.flush()
    print(f'Recorded checks for {len(sample)} sampled addresses.')


if __name__ == '__main__':
    main()
