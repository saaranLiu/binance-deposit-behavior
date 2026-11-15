"""Recompute the reviewer-response estimates from aggregate BigQuery exports."""
from collections import defaultdict
from csv import DictReader, DictWriter
from json import loads, dumps
from math import sqrt
from pathlib import Path
from statistics import mean

import numpy as np

HERE = Path(__file__).resolve().parent
PHASES = {'joint': 1, 'halt': 1, '48h': 1, '7d': 2, '14d': 3, 'notice': 1, 'first40': 1}
AMOUNT = lambda row: row['usd'] / row['n']
RATE = lambda row: 100 * row['users'] / row['n']
LOOKBACK = 4


def read_summary():
    with (HERE / 'historical_summary.csv').open() as handle:
        rows = list(DictReader(handle))
    grouped = defaultdict(dict)
    for row in rows:
        k, phase, group = int(row.pop('k')), row.pop('phase'), row.pop('g')
        if k in grouped[phase, group]:
            raise ValueError(f'Duplicate summary cell: {(k, phase, group)}')
        grouped[phase, group][k] = {a: float(b) if b else None for a, b in row.items()}
    assert len(rows) == 17058 and all(set(grouped[phase, 'all']) == set(range(44)) for phase in PHASES)
    assert grouped['7d', 'all'][0]['n'] == 10483 and grouped['7d', 'all'][0]['users'] == 4800
    assert abs(grouped['7d', 'all'][0]['usd'] - 2303782464.108736) < .1
    return grouped


def donor_weeks(phase, k):
    start = k + PHASES[phase]
    return range(start, start + LOOKBACK)


def rank(event, placebos, *, upper=False):
    values = list(placebos.values())
    worse = sum(x >= event for x in values) if upper else sum(x <= event for x in values)
    return dict(event=event, rank=1+worse, n=len(values)+1, p=(1+worse)/(len(values)+1),
                range=[min(values), max(values)], interval=np.quantile(values,[.025,.975]).tolist(),
                placebo=placebos)


def rolling(weeks, phase, metric, *, ratio=False, upper=False):
    values = {}
    for k in weeks:
        donors = list(donor_weeks(phase, k))
        if (k != 0 and k < PHASES[phase]) or not all(j in weeks for j in donors):
            continue
        forecast = mean(metric(weeks[j]) for j in donors)
        observed = metric(weeks[k])
        if ratio and forecast <= 0:
            continue
        values[k] = 100 * (observed / forecast - 1) if ratio else observed - forecast
    return rank(values.pop(0), values, upper=upper)


def conditional_within(row):
    return 100 * row['below_positive_prior_median'] / row['positive_prior_median']


def amount_heterogeneity(grouped):
    return {
        phase: {g: {'n': weeks[0]['n'], 'event_pp': RATE(weeks[0]), 'event_usd_per_sender': AMOUNT(weeks[0]),
                    'amount': rolling(weeks,phase,AMOUNT,ratio=True) if weeks[0]['n'] and
                    all(k in weeks for k in donor_weeks(phase,0)) else None,
                    'part': rolling(weeks,phase,RATE) if all(k in weeks for k in donor_weeks(phase,0)) else None,
                    'history_pp':mean(RATE(weeks[k]) for k in donor_weeks(phase,0) if k in weeks),
                    'history_n':mean(weeks[k]['n'] for k in donor_weeks(phase,0) if k in weeks)}
                for (h,g),weeks in grouped.items() if h==phase and g.startswith(('tier:','roundtrip:','whale:'))}
        for phase in ('joint','halt','48h','7d','14d')
    }


def balance_weights(cells, target, donor):
    strata = sorted(cells)
    levels = np.array([tuple(int(x) for x in s.split(':')[1:]) for s in strata])
    n = np.array([cells[s].get(donor,{}).get('n',0) for s in strata])
    desired = np.array([cells[s].get(target,{}).get('n',0) for s in strata])
    f, q = n/n.sum(), desired/desired.sum()
    # Full-cell poststratification when the cross-classified cells have useful support.
    if np.all(n[q > 0] >= 5):
        return strata, q, 'cells', n
    # Raking is the entropy projection onto the three marginal histograms.
    weights = f.copy()
    margin_masks = []
    coarsened = False
    for i in range(3):
        partitions = [levels[:,i] == j for j in np.unique(levels[:,i])]
        while len(partitions)>1 and any(q[m].sum()>0 and f[m].sum()==0 for m in partitions):
            j = next(j for j,m in enumerate(partitions) if q[m].sum()>0 and f[m].sum()==0)
            adjacent = j-1 if j else j+1
            first, second = sorted((j, adjacent))
            partitions[first] = partitions[first] | partitions.pop(second)
            coarsened = True
        margin_masks.append(partitions)
    for _ in range(150):
        for partitions in margin_masks:
            for mask in partitions:
                goal, current = q[mask].sum(), weights[mask].sum()
                if current == 0 and goal > 0:
                    raise ValueError(f'Donor {donor} has no support for target {target}')
                if current:
                    weights[mask] *= goal/current
        error = max(abs(weights[m].sum()-q[m].sum()) for group in margin_masks for m in group)
        if error < 1e-8:
            return strata, weights, 'coarsened_entropy' if coarsened else 'entropy', n
    raise ValueError(f'Raking failed to converge: target {target}, donor {donor}')


def reweighted(grouped, phase):
    cells = {g:weeks for (p,g),weeks in grouped.items() if p==phase and g.startswith('cell:')}
    cohorts = grouped[phase,'all']
    forecasts, balance = {}, []
    for anchor in range(44):
        donors = list(donor_weeks(phase,anchor))
        if (anchor != 0 and anchor < PHASES[phase]) or max(donors)>43:
            continue
        predicted, predicted_rate = [], []
        for donor in donors:
            strata, weights, method, counts = balance_weights(cells,anchor,donor)
            rows = [cells[s].get(donor) for s in strata]
            weighted = lambda metric: sum(float(w)*metric(r) for r,w in zip(rows,weights) if r and w)
            predicted.append(weighted(AMOUNT))
            predicted_rate.append(weighted(RATE))
            if anchor == 0:
                row = dict(donor=donor,method=method,ess=1/sum(float(w*w/n) for w,n in zip(weights,counts) if n))
                for metric in ('pre_amount','pre_count','recency_h'):
                    ev, ref = cohorts[0], cohorts[donor]
                    old_sd=sqrt(max(0,(ev[metric+'_sq']-ev[metric]**2+ref[metric+'_sq']-ref[metric]**2)/2))
                    row[metric]=dict(event=ev[metric],raw=ref[metric],balanced=weighted(lambda r:r[metric]))
                    row[metric].update(raw_smd=(ev[metric]-ref[metric])/old_sd,
                                       adjusted_smd=(ev[metric]-row[metric]['balanced'])/old_sd)
                balance.append(row)
        forecasts[anchor]=(100*(AMOUNT(cohorts[anchor])/mean(predicted)-1),
                           RATE(cohorts[anchor])-mean(predicted_rate))
    return dict(amount=rank(forecasts[0][0],{k:v[0] for k,v in forecasts.items() if k}),
                participation=rank(forecasts[0][1],{k:v[1] for k,v in forecasts.items() if k}),balance=balance)


def export_table(name, rows):
    with (HERE/name).open('w',newline='') as handle:
        writer=DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def save_supplement(result):
    from datetime import date, timedelta
    anchor=date(2026,10,29)
    export_table('cohort_sizes.csv',[dict(week=k,anchor_utc=f'{anchor-timedelta(weeks=k)}T20:05:00Z',n=int(n))
                                      for k,n in sorted(result['cohort_sizes'].items())])
    export_table('balance.csv',[dict(window=p,donor=cell['donor'],method=cell['method'],
                                   effective_n=cell['ess'],variable=name,**cell[name])
                         for p,row in result['reweighted'].items() for cell in row['balance']
                         for name in ('pre_amount','pre_count','recency_h')])
    export_table('placebo_ranks.csv',[dict(window=p,outcome=outcome,event=v['event'],rank=v['rank'],
                                          total=v['n'],p=v['p'],placebo_min=v['range'][0],placebo_max=v['range'][1])
                                    for p,items in result['comparisons'].items() for outcome,v in items.items()])


def main():
    grouped=read_summary()
    comparisons={}
    for phase in PHASES:
        weeks=grouped[phase,'all']
        metrics = dict(usd=rolling(weeks,phase,AMOUNT,ratio=True), participation=rolling(weeks,phase,RATE),
                       median=rolling(weeks,phase,lambda r:r['median_active'],ratio=True),
                       asinh=rolling(weeks,phase,lambda r:r['asinh_mean']))
        if phase!='first40':
            metrics['winsor']=rolling(weeks,phase,lambda r:r['winsor_mean'],ratio=True)
        if phase in ('joint','halt','48h','7d'):
            # With equal counts of target and four baseline slots for every address,
            # this is algebraically the target-week OLS coefficient with address effects.
            for field,fn,upper in (
                  ('within_usd',lambda r:r['within_change'],False),
                  ('within_pct',lambda r:100*r['within_change']/r['within_base'],False),
                  ('below_own_median',lambda r:100*r['below_own_median'],True),
                  ('below_positive_own_median',conditional_within,True)):
                latest=43-max(PHASES[phase]+LOOKBACK-1,0)
                metrics[field]=rank(fn(weeks[0]),{k:fn(weeks[k]) for k in range(PHASES[phase],latest+1)},upper=upper)
        comparisons[phase]=metrics
    weights={phase: reweighted(grouped,phase) for phase in ('joint','halt','48h','7d')}
    freq={}
    for (phase,g),weeks in grouped.items():
        if phase=='7d' and g.startswith('freq:'):
            freq[g.split(':')[1]]={str(day):rolling(weeks,phase,lambda row:100*row['day'+str(day)]/row['n'])
                                 for day in (1,3,7)}
    strict={}
    weeks=grouped['7d','all']
    for prefix in ('days3','single','fast','strict'):
        strict[prefix] = dict(event=100*weeks[0][prefix+'_n']/weeks[0]['n'],
             historical=mean(100*weeks[k][prefix+'_n']/weeks[k]['n'] for k in donor_weeks('7d',0)),
             amount=rolling(weeks,'7d',lambda r:r[prefix+'_usd']/r['n'],ratio=True))
    result=dict(comparisons=comparisons,reweighted=weights,heterogeneity=amount_heterogeneity(grouped),
                frequency=freq,strict=strict,cohort_sizes={k:r['n'] for k,r in grouped['7d','all'].items()},
                migration={k:{g:int(v) for g,v in {'binance_only':r['users']-r['both'],'rival_only':r['rival']-r['both'],
                    'both':r['both'],'neither':r['n']-r['users']-r['rival']+r['both'],'bybit':r['bybit'],'n':r['n']}.items()}
                    for k,r in grouped['7d','all'].items()},
                absolute={p:g[0] for (p,cell),g in grouped.items() if cell=='all'})
    (HERE/'review_results.json').write_text(dumps(result,indent=2)+'\n')
    save_supplement(result)


if __name__=='__main__':
    main()
