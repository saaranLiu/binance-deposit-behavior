excluded AS (
  SELECT CONCAT('0x',TO_HEX(SUBSTR(payload,pos,20))) AS sender
  FROM (SELECT FROM_BASE64(REPLACE('''__SCREEN_BYTES__''','\n','')) AS payload),
  UNNEST(GENERATE_ARRAY(1,BYTE_LENGTH(payload),20)) AS pos
), screened AS (
  SELECT c.* FROM cohort c LEFT JOIN excluded e USING(sender) WHERE e.sender IS NULL
), freeze AS (
  SELECT c.k, COUNT(DISTINCT c.sender) AS n, p.phase,
    COUNT(DISTINCT IF(t.ts IS NOT NULL,c.sender,NULL)) AS users,
    IFNULL(SUM(t.amount)/1000000,0) AS usd
  FROM screened c CROSS JOIN
  UNNEST([STRUCT('48h' AS phase,TIMESTAMP_SUB(c.reopen,INTERVAL 3 HOUR) AS lo,TIMESTAMP_ADD(c.reopen,INTERVAL 45 HOUR) AS hi),
          STRUCT('7d',c.reopen,TIMESTAMP_ADD(c.reopen,INTERVAL 7 DAY))]) p
  LEFT JOIN (SELECT c.k,a.ts,a.src,a.amount FROM periods c JOIN transfers a
    ON a.ts>=TIMESTAMP_SUB(c.reopen,INTERVAL 3 HOUR) AND a.ts<TIMESTAMP_ADD(c.reopen,INTERVAL 7 DAY)
    JOIN prior_labels l ON l.k=c.k AND a.dst=l.dst AND l.venue='B') t
    ON t.k=c.k AND t.src=c.sender AND t.ts>=p.lo AND t.ts<p.hi
  GROUP BY c.k,p.phase
), early AS (
  SELECT TIMESTAMP_DIFF(t.ts,c.shock,MINUTE) AS minute,t.src AS sender,t.dst AS deposit,
   CAST(t.amount/1000000 AS FLOAT64) AS usd,t.tx,t.idx,
   IF(e.sender IS NULL,'screened','excluded') AS cohort_status,t.src_role
  FROM cohort c JOIN transfers t ON c.sender=t.src AND t.ts>=c.shock AND t.ts<TIMESTAMP_ADD(c.shock,INTERVAL 40 MINUTE)
  JOIN prior_labels l ON l.k=c.k AND l.dst=t.dst AND l.venue='B'
  LEFT JOIN excluded e ON e.sender=c.sender
  WHERE c.k=0
), label_amounts AS (
  SELECT l.dst,l.match_days,l.deposit_senders,l.fast_days,
    SUM(CAST(p.amount/1000000 AS FLOAT64)) AS prior_usd
  FROM prior_labels l JOIN prior_paths p ON p.k=l.k AND p.dst=l.dst
  WHERE l.k=0 AND l.venue='B'
  GROUP BY l.dst,l.match_days,l.deposit_senders,l.fast_days
), label_strata AS (
  SELECT *,CASE WHEN match_days=2 THEN '2' WHEN match_days<=5 THEN '3-5' ELSE '6+' END AS days,
   CASE WHEN prior_usd<10000 THEN 'lt10k' WHEN prior_usd<100000 THEN '10k-100k' ELSE '100k+' END AS size
  FROM label_amounts
), label_sample AS (
  SELECT *,COUNT(*) OVER (PARTITION BY days,size) AS stratum_population
  FROM label_strata QUALIFY ROW_NUMBER() OVER (PARTITION BY days,size ORDER BY FARM_FINGERPRINT(CONCAT('review-v1:',dst)),dst)<=28
), reverse_checks AS (
  SELECT l.dst,COUNTIF(t.ts IS NOT NULL) AS outgoing,
    COUNTIF(t.ts IS NOT NULL AND t.dst_role IN ('Y','O')) AS other_seed,
    COUNTIF(t.ts IS NOT NULL AND IFNULL(t.dst_role,'') NOT IN ('B','F','N')) AS outside_binance_seeds
  FROM label_strata l LEFT JOIN transfers t
    ON l.dst=t.src AND t.ts>=TIMESTAMP '2026-10-01 20:05:00+00' AND t.ts<TIMESTAMP '2026-11-08 09:00:00+00'
  GROUP BY l.dst
), top_addresses AS (
  SELECT c.sender,CAST(c.pre_amount AS FLOAT64) AS pre_usd,c.pre_count
  FROM screened c WHERE c.k=0
  QUALIFY ROW_NUMBER() OVER (ORDER BY pre_amount DESC,sender)<=100
), profile AS (
  SELECT c.sender,c.pre_usd,c.pre_count,
    COUNTIF(t.dst=c.sender AND t.src_role IN ('B','F')) AS incoming_binance_wallet,
    COUNT(DISTINCT IF(t.src=c.sender AND l.venue IN ('Y','O'),l.venue,NULL)) AS named_rivals,
    COUNTIF(t.src=c.sender AND l.venue IN ('Y','O')) AS rival_transfers
  FROM top_addresses c LEFT JOIN transfers t
    ON (t.dst=c.sender OR t.src=c.sender) AND t.ts>=TIMESTAMP '2026-10-01 20:05:00+00' AND t.ts<TIMESTAMP '2026-10-29 20:05:00+00'
  LEFT JOIN prior_labels l ON l.k=0 AND t.dst=l.dst
  GROUP BY c.sender,c.pre_usd,c.pre_count
), delays AS (
 SELECT w.k,IF(p.role='N','new','existing') AS wallet_role,
   COUNT(*) AS matches,APPROX_QUANTILES(TIMESTAMP_DIFF(p.swept,p.ts,MINUTE),100)[OFFSET(10)] AS p10_minutes,
   APPROX_QUANTILES(TIMESTAMP_DIFF(p.swept,p.ts,MINUTE),100)[OFFSET(50)] AS p50_minutes,
   APPROX_QUANTILES(TIMESTAMP_DIFF(p.swept,p.ts,MINUTE),100)[OFFSET(90)] AS p90_minutes
 FROM broad_paths p JOIN periods w ON p.ts>=w.reopen AND p.ts<TIMESTAMP_ADD(w.reopen,INTERVAL 7 DAY)
 JOIN screened c ON c.k=w.k AND p.src=c.sender
 WHERE w.k BETWEEN 0 AND 2 AND p.venue='B'
 GROUP BY w.k,wallet_role
)
SELECT 'freeze' AS section,TO_JSON_STRING(f) AS payload FROM freeze f
UNION ALL SELECT 'early',TO_JSON_STRING(e) FROM early e
UNION ALL SELECT 'label_sample',TO_JSON_STRING(s) FROM label_sample s
UNION ALL SELECT 'label_reverse',TO_JSON_STRING(STRUCT(COUNT(*) AS n,COUNTIF(outgoing>0) AS outgoing,
  COUNTIF(other_seed>0) AS rival_seed,COUNTIF(outside_binance_seeds>0) AS outside_seeds)) FROM reverse_checks
UNION ALL SELECT 'top',TO_JSON_STRING(t) FROM profile t
UNION ALL SELECT 'delays',TO_JSON_STRING(d) FROM delays d
ORDER BY section,payload
