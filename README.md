# Binance deposit behavior replication

Replication materials for *Deposits after a Security Breach: Evidence from a Cryptocurrency Exchange*.

Download and extract [the replication archive](trust-anonymous-replication.zip). It includes the 17,058 aggregate observations across 44 weekly cohorts, BigQuery queries, Python code, aggregate audit results, and sources for the paper's figures and tables. The archive includes its own README with the data definitions and query instructions.

From the extracted directory, use Python with NumPy and PyMuPDF, and TeX Live with Linux Libertine and acmart.

```sh
python3 -B review/analyze_review.py
python3 -B review/plot_review.py
cd paper
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```
