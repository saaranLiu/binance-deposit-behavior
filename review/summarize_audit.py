"""Summarize the event audit and separate external label coverage from agreement."""
import argparse
from collections import Counter, defaultdict
from csv import DictReader
from json import dumps, loads
from math import sqrt
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def read_export(name):
    output = defaultdict(list)
    with (HERE / name).open() as handle:
        for row in DictReader(handle):
            output[row['section']].append(loads(row['payload']))
    return output


def wilson(successes, n, z=1.959963984540054):
    rate = successes / n
    center = (rate+z*z/(2*n))/(1+z*z/n)
    half = z*sqrt(rate*(1-rate)/n+z*z/(4*n*n))/(1+z*z/n)
    return [max(0, center-half), min(1, center+half)]


def summarize_labels(sample, evidence):
    tally = defaultdict(Counter)
    for row in sample:
        key = (row['days'], row['size'])
        tally[key]['population'] = row['stratum_population']
        tally[key]['sampled'] += 1
        tally[key][evidence.get(row['dst'], 'unresolved')] += 1
    confirmed = sum(c['confirmed'] for c in tally.values())
    other = sum(c['other_venue'] for c in tally.values())
    population = sum(c['population'] for c in tally.values())
    bound = lambda field: sum(c['population']*c[field]/c['sampled'] for c in tally.values())/population
    return dict(confirmed=confirmed, conflicting=other, unresolved=len(sample)-confirmed-other,
                agreement_among_explicit_labels=confirmed/(confirmed+other) if confirmed+other else None,
                wilson_95_among_explicit=wilson(confirmed,confirmed+other) if confirmed+other else None,
                weighted_coverage_bounds=[bound('confirmed'),1-bound('other_venue')],
                strata=[dict(days=d,size=s,**counts) for (d,s),counts in sorted(tally.items())])


def read_public_tags(name):
    source = HERE/name
    if not source.is_file():
        return {}
    by_address = {row['address']:row for row in map(loads,source.read_text().splitlines())}
    return {address:row['name_tag'] for address,row in by_address.items() if row.get('name_tag')}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--labels', type=Path, default=HERE/'explorer_labels.jsonl')
    args=p.parse_args()
    ins=read_export('event_audit.csv')
    verification=read_export('validation.csv')
    phases=ins['freeze']
    first=defaultdict(float)
    minute=defaultdict(float)
    status=defaultdict(float)
    for row in ins['early']:
        status[row['cohort_status']]+=row['usd']
        if row['cohort_status']=='screened':
            first[row['sender']]+=row['usd']
            minute[row['minute']]+=row['usd']
            assert row['src_role'] is None
    assert len(first)==127 and abs(sum(first.values())-27836549.496265)<.1
    early=dict(senders=len(first), qualified_amount=sum(first.values()),
               excluded_amount=status['excluded'], top_five_share=sum(sorted(first.values(),reverse=True)[:5])/sum(first.values()),
               amount_by_minute={i:minute[i] for i in range(40)})
    early['top_five_public_tag_categories'] = sorted(read_public_tags('early_labels.jsonl').values())
    freeze={}
    for phase in ('48h','7d'):
        cells={r['k']:r for r in phases if r['phase']==phase}
        reference=[cells[k] for k in range(102,109)]
        evt=cells[100]
        freeze[phase]=dict(n=evt['n'],active=evt['users'],participation_pct=100*evt['users']/evt['n'],
                           history_participation_pct=100*mean(r['users']/r['n'] for r in reference),
                           amount_diff_pct=100*((float(evt['usd'])/evt['n']) /
                                                mean(float(r['usd'])/r['n'] for r in reference)-1))
    by_address={}
    if args.labels.is_file():
        for line in args.labels.read_text().splitlines():
            try:
                row=loads(line)
            except ValueError:
                continue
            by_address[row['address']]=row['status']
    summary=dict(early=early,late_freeze=freeze,
         audit=summarize_labels(ins['label_sample'],by_address),reverse=ins['label_reverse'][0],
         top100=dict(observed_prior_contracts=len(verification['contract']),
                     public_name_tags=len(read_public_tags('whale_labels.jsonl')),
                     incoming=sum(r['incoming_binance_wallet']>0 for r in ins['top']),
                     any_rival=sum(r['named_rivals']>0 for r in ins['top']),
                     both_rivals=sum(r['named_rivals']==2 for r in ins['top'])),
         delay=ins['delays'],coverage=verification['coverage'])
    (HERE/'audit_results.json').write_text(dumps(summary,indent=2)+'\n')


if __name__=='__main__':
    main()
