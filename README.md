# Binance deposit behavior

Aggregate Ethereum deposit outcomes around the October 2026 Binance incident, plus the queries and scripts that build them. Timestamps are UTC. Amounts are USDT and USDC face values.

## Files

| Path | Contents |
| --- | --- |
| `review/historical_summary.csv` | 17,058 exported BigQuery rows from 44 weekly cohorts. Cohort totals, group totals, robust outcomes, and covariate moments. |
| `review/review_results.json` | Forecasts, event ranks, 2.5th and 97.5th placebo percentiles, group gaps, and rival-exchange use. |
| `review/cohort_sizes.csv`, `review/balance.csv`, `review/placebo_ranks.csv` | Supplementary tables written by `analyze_review.py`. |
| `review/review_query.sql`, `review/review_suffix.sql` | Executed BigQuery query for the weekly series. Address-level contrasts are aggregated in BigQuery. |
| `review/audit_query.sql`, `review/audit_suffix.sql` | Event audit and the address sample. |
| `review/validation_template.sql`, `review/build_validation_query.py` | Template and builder for contract-deployment and late-window coverage checks. |
| `review/audit_results.json` | Minute-by-minute initial amounts, concentration, later eligibility, label coverage, address profile, and sweep delays. |
| `review/analyze_review.py` | Recompute comparisons from `historical_summary.csv`. |
| `review/summarize_audit.py`, `review/check_explorer_labels.py` | Summarize an audit export and check public explorer name tags. |

Per-address case records are not stored in this repository. `check_explorer_labels.py`, `build_validation_query.py`, and `summarize_audit.py` expect those exports locally when the address checks are repeated.

## Recompute the aggregate results

Requires Python 3 and NumPy.

```sh
python3 -B review/analyze_review.py
```

The script reads `review/historical_summary.csv` and rewrites `review/review_results.json`, `review/cohort_sizes.csv`, `review/balance.csv`, and `review/placebo_ranks.csv`.

## Repeat the address checks

Run `review/audit_query.sql` and save the export as `review/event_audit.csv`. Then build and run the coverage query:

```sh
python3 -B review/build_validation_query.py
```

Save that query's export as `review/validation.csv`. Check public name tags and write the audit summary:

```sh
python3 -B review/check_explorer_labels.py
python3 -B review/summarize_audit.py
```

`summarize_audit.py` also reads `review/explorer_labels.jsonl` when that file is present. Optional tag lists are `review/early_labels.jsonl` and `review/whale_labels.jsonl`.

## Sample and comparisons

The target population is the eligible address cohort, including zero-amount addresses. Anchors are Thursday 20:05 UTC from January 1 through October 29, 2026. The query reads earlier logs back to November 27, 2025 for lagged outcomes and enrollment. Destination labels come from the applicable pre-anchor transactions for each cohort. Registry inclusion dates and label-generation dates are different. Two named venue seeds in the archived registry have registry dates after January 1 and before the August start used in the earlier window.

Weeks are indexed backward from October 29. The joint, halt, and 48-hour targets use the preceding four weeks. For the seven-day target the donor offsets are two through five, because the closest seven-day window can cross the target anchor. The fourteen-day offsets are three through six. A placebo eligible for an outcome needs an outcome window that ends before the incident and four available donors. The one-sided empirical rank is one plus the number of historical deficits at least as severe, divided by the number of eligible windows including the event. The share below the own median ranks in the upper tail. Rolling comparisons overlap, so the ranks describe historical extremeness.

Amount balancing weights donors separately to the target cohort. Cross-classified cells are used when each target cell has at least five donor addresses. Otherwise the marginal distributions are matched by iterative proportional fitting. Adjacent categories are pooled when a marginal level is unsupported. Standardized mean differences use the same pooled unweighted standard deviation before and after balancing. The closest four clean seven-day donors average 10,488 addresses, next to the event cohort of 10,483. Annual historical panels range from 1,457 to 11,076 addresses.

Amount winsorization caps the 99th percentile within each cohort and window, including zeros. The address fixed-effect coefficient uses a balanced target slot and four baseline slots per eligible sender, with the same target label set. It equals the average target-minus-own-baseline difference. The historic placebo repeats enrollment and estimation. Self-comparisons can still reflect eligibility that selects addresses with a more recent deposit, which is why they are ranked against the historical placebo distribution.

Pre-anchor amount tiers use amounts in the 28-day lookback. The top percentile is ranked separately before each anchor. A round-trip address has an observed positive USDT or USDC receipt from a known Binance hot-wallet seed before the anchor. The label is an on-chain pattern. It does not establish account ownership. Prior contract deployments are historical observations, not a complete account classification.

The label sample has 28 destinations in each of nine cells: matching dates of 2, 3–5, and 6 or more, crossed with prior matched dollars under 10,000, 10,000–100,000, and 100,000 or more. Destinations are drawn by a fixed salted hash. Public Etherscan name tags corroborate 238 addresses. The other 14 have an accessible page without an explicit venue label. The confirmation share weighted by stratum population is 94.5 percent. Unlabeled cases stay unresolved.

Screening uses the archived Spellbook and incident lists, including the archived Elliptic blocklist.

## Provenance

- Long historical export: 17,058 BigQuery rows.
- Event and label audit: 641 BigQuery rows, stored here only as aggregates in `review/audit_results.json`.
- Public contract and coverage check: 21 BigQuery rows. The latest indexed stablecoin transfer in the fourteen-day window is 08:59:59 UTC on November 15.
- Sources: [Google Cloud Ethereum tables](https://docs.cloud.google.com/blockchain-analytics/docs/example-ethereum), [Dune seed registry](https://github.com/duneanalytics/spellbook/blob/main/dbt_subprojects/hourly_spellbook/models/_sector/cex/addresses/chains/cex_evms_addresses.sql), [Etherscan](https://etherscan.io/), [FBI advisory](https://www.fbi.gov/investigate/cyber/alerts/2026/north-korea-responsible-for-6-billion-binance-attack).
