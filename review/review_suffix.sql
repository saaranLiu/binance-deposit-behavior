excluded AS (
  SELECT CONCAT('0x',TO_HEX(SUBSTR(payload,pos,20))) AS sender
  FROM (SELECT FROM_BASE64(REPLACE('''__SCREEN_BYTES__''','\n','')) AS payload),
  UNNEST(GENERATE_ARRAY(1,BYTE_LENGTH(payload),20)) AS pos
), withdrawals AS (
  SELECT c.k,c.sender,COUNT(*) AS n
  FROM cohort c JOIN transfers t
    ON t.dst=c.sender AND t.ts>=TIMESTAMP_SUB(c.shock,INTERVAL 28 DAY) AND t.ts<c.shock
  WHERE t.src_role IN ('B','F')
  GROUP BY c.k,c.sender
), screened AS (
  SELECT c.*,w.n>0 AS roundtrip,
         CASE WHEN pre_amount<1000 THEN 0 WHEN pre_amount<10000 THEN 1 WHEN pre_amount<100000 THEN 2 WHEN pre_amount<1000000 THEN 3 ELSE 4 END AS amount_tier,
         CASE WHEN pre_count=2 THEN 0 WHEN pre_count<=5 THEN 1 WHEN pre_count<=20 THEN 2 ELSE 3 END AS count_tier,
         CASE WHEN recency_h<24 THEN 0 WHEN recency_h<72 THEN 1 ELSE 2 END AS recent_tier,
         ROW_NUMBER() OVER (PARTITION BY c.k ORDER BY pre_amount DESC,c.sender) <= CEIL(COUNT(*) OVER (PARTITION BY c.k)/100.0) AS whale
  FROM cohort c
  LEFT JOIN excluded e USING(sender)
  LEFT JOIN withdrawals w USING(k,sender)
  WHERE e.sender IS NULL
), windows AS (
  SELECT k, phase, lag_week,
    TIMESTAMP_SUB(start_at,INTERVAL (7*lag_week) DAY) AS start_at,
    TIMESTAMP_SUB(end_at,INTERVAL (7*lag_week) DAY) AS end_at
  FROM periods
  CROSS JOIN UNNEST([
    STRUCT('joint' AS phase,shock AS start_at,TIMESTAMP_ADD(reopen,INTERVAL 216 MINUTE) AS end_at),
    STRUCT('halt',TIMESTAMP_ADD(shock,INTERVAL 40 MINUTE),TIMESTAMP_SUB(reopen,INTERVAL 3 HOUR)),
    STRUCT('48h',TIMESTAMP_SUB(reopen,INTERVAL 3 HOUR),TIMESTAMP_ADD(reopen,INTERVAL 45 HOUR)),
    STRUCT('7d',reopen,TIMESTAMP_ADD(reopen,INTERVAL 7 DAY)),
    STRUCT('14d',reopen,TIMESTAMP_ADD(reopen,INTERVAL 14 DAY)),
    STRUCT('notice',TIMESTAMP_ADD(shock,INTERVAL 130 MINUTE),TIMESTAMP_ADD(reopen,INTERVAL 216 MINUTE)),
    STRUCT('first40',shock,TIMESTAMP_ADD(shock,INTERVAL 40 MINUTE))
  ])
  CROSS JOIN UNNEST(IF(phase='7d',[0,2,3,4,5],IF(phase IN ('joint','halt','48h'),[0,1,2,3,4],[0]))) AS lag_week
), observed AS (
  SELECT c.k,c.sender,l.venue,l.match_days,l.deposit_senders,l.fast_days,t.ts,
         CAST(t.amount/1000000 AS FLOAT64) AS usd
  FROM screened c JOIN transfers t
    ON t.src=c.sender AND t.ts>=TIMESTAMP_SUB(c.shock,INTERVAL 35 DAY)
    AND t.ts<TIMESTAMP_ADD(c.reopen,INTERVAL 14 DAY)
  JOIN prior_labels l ON l.k=c.k AND l.dst=t.dst
), amounts AS (
  SELECT t.k,t.sender,w.phase,w.lag_week,
    SUM(IF(t.venue='B',usd,0)) AS usd,
    SUM(IF(t.venue='B' AND t.match_days>=3,usd,0)) AS days3,
    SUM(IF(t.venue='B' AND t.deposit_senders=1,usd,0)) AS single_sender,
    SUM(IF(t.venue='B' AND t.fast_days>=2,usd,0)) AS fast,
    SUM(IF(t.venue='B' AND t.match_days>=3 AND t.deposit_senders=1 AND t.fast_days>=2,usd,0)) AS strict_all,
    SUM(IF(t.venue='Y',usd,0)) AS bybit,SUM(IF(t.venue='O',usd,0)) AS okx,
    MIN(IF(t.venue='B',TIMESTAMP_DIFF(t.ts,w.start_at,MINUTE),NULL)) AS first_minute
  FROM observed t JOIN windows w
    ON t.k=w.k AND t.ts>=w.start_at AND t.ts<w.end_at
  GROUP BY t.k,t.sender,w.phase,w.lag_week
), addresses AS (
  SELECT c.k,c.sender,w.phase,ANY_VALUE(c.amount_tier) AS amount_tier,
    ANY_VALUE(c.recent_tier) AS recent_tier,ANY_VALUE(c.count_tier) AS count_tier,
    ANY_VALUE(IFNULL(c.roundtrip,FALSE)) AS roundtrip,ANY_VALUE(c.whale) AS whale,
    ANY_VALUE(CAST(c.pre_amount AS FLOAT64)) AS pre_amount,
    ANY_VALUE(c.pre_count) AS pre_count,ANY_VALUE(c.recency_h) AS recency_h,
    SUM(IF(w.lag_week=0,IFNULL(a.usd,0),0)) AS usd,
    SUM(IF(w.lag_week=0,IFNULL(a.days3,0),0)) AS days3,
    SUM(IF(w.lag_week=0,IFNULL(a.single_sender,0),0)) AS single_sender,
    SUM(IF(w.lag_week=0,IFNULL(a.fast,0),0)) AS fast,
    SUM(IF(w.lag_week=0,IFNULL(a.strict_all,0),0)) AS strict_all,
    SUM(IF(w.lag_week=0,IFNULL(a.bybit,0),0)) AS bybit,
    SUM(IF(w.lag_week=0,IFNULL(a.okx,0),0)) AS okx,
    MIN(IF(w.lag_week=0,a.first_minute,NULL)) AS first_minute,
    ARRAY_AGG(IF(w.lag_week>0,IFNULL(a.usd,0),NULL) IGNORE NULLS ORDER BY IF(w.lag_week>0,IFNULL(a.usd,0),NULL)) AS past
  FROM screened c JOIN windows w USING(k)
  LEFT JOIN amounts a ON a.k=c.k AND a.sender=c.sender AND a.phase=w.phase AND a.lag_week=w.lag_week
  GROUP BY c.k,c.sender,w.phase
), expanded AS (
  SELECT a.*,g
  FROM addresses a, UNNEST(ARRAY_CONCAT(['all'],
    IF(phase IN ('joint','halt','48h','7d','14d'),[
      CONCAT('cell:',count_tier,':',recent_tier,':',amount_tier),
      CONCAT('tier:',amount_tier),CONCAT('roundtrip:',CAST(roundtrip AS STRING)),
      CONCAT('whale:',CAST(whale AS STRING)), CONCAT('freq:',CASE WHEN pre_count<=5 THEN '2-5' WHEN pre_count<=20 THEN '6-20' WHEN pre_count<100 THEN '21-99' ELSE '100+' END),
      CONCAT('tier_roundtrip:',amount_tier,':',CAST(roundtrip AS STRING)), CONCAT('tier_whale:',amount_tier,':',CAST(whale AS STRING))
    ],[]))) AS g
), quantiles AS (
  SELECT *,
    PERCENTILE_CONT(usd,0.99) OVER grp AS p99,
    PERCENTILE_CONT(IF(usd>0,usd,NULL),0.5 IGNORE NULLS) OVER grp AS median_active,
    IFNULL((past[SAFE_OFFSET(1)]+past[SAFE_OFFSET(2)])/2,0) AS prior_median,
    IFNULL((SELECT AVG(value) FROM UNNEST(past) AS value),0) AS prior_mean
  FROM expanded
  WINDOW grp AS (PARTITION BY k,phase,g)
), summary AS (
  SELECT k,phase,g,COUNT(*) AS n,COUNTIF(usd>0) AS users,SUM(usd) AS usd,
    AVG(LEAST(usd,p99)) AS winsor_mean,AVG(ASINH(usd)) AS asinh_mean,
    ANY_VALUE(median_active) AS median_active,
    AVG(usd-prior_mean) AS within_change,AVG(prior_mean) AS within_base,
    AVG(IF(usd<prior_median,1,0)) AS below_own_median,
    COUNTIF(prior_median>0) AS positive_prior_median,
    COUNTIF(usd<prior_median AND prior_median>0) AS below_positive_prior_median,
    AVG(pre_amount) AS pre_amount,AVG(POW(pre_amount,2)) AS pre_amount_sq,
    AVG(pre_count) AS pre_count,AVG(POW(pre_count,2)) AS pre_count_sq,
    AVG(recency_h) AS recency_h,AVG(POW(recency_h,2)) AS recency_h_sq,
    COUNTIF(days3>0) AS days3_n,SUM(days3) AS days3_usd,
    COUNTIF(single_sender>0) AS single_n,SUM(single_sender) AS single_usd,
    COUNTIF(fast>0) AS fast_n,SUM(fast) AS fast_usd,
    COUNTIF(strict_all>0) AS strict_n,SUM(strict_all) AS strict_usd,
    COUNTIF(bybit>0 OR okx>0) AS rival,COUNTIF(bybit>0) AS bybit,
    COUNTIF(usd>0 AND (bybit>0 OR okx>0)) AS both,
    COUNTIF(first_minute<1440) AS day1,COUNTIF(first_minute<4320) AS day3,
    COUNTIF(first_minute<10080) AS day7,COUNTIF(first_minute<20160) AS day14
  FROM quantiles
  GROUP BY k,phase,g
)
SELECT k,phase,g,n,users,usd,winsor_mean,asinh_mean,median_active,
 within_change,within_base,below_own_median,positive_prior_median,below_positive_prior_median,
 pre_amount,pre_amount_sq,pre_count,pre_count_sq,recency_h,recency_h_sq,
 days3_n,days3_usd,single_n,single_usd,fast_n,fast_usd,strict_n,strict_usd,
 rival,bybit,both,day1,day3,day7,day14
FROM summary ORDER BY k,phase,g
