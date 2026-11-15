SELECT 'contract' AS section,TO_JSON_STRING(STRUCT(address)) AS payload
FROM `bigquery-public-data.crypto_ethereum.contracts`
WHERE block_timestamp < TIMESTAMP '2026-10-29 20:05:00+00' AND address IN (__ADDRESSES__)
GROUP BY address
UNION ALL
SELECT 'coverage',TO_JSON_STRING(STRUCT(MIN(DATE(block_timestamp)) AS day,MAX(block_timestamp) AS last_utc,MIN(block_timestamp) AS first_utc,COUNT(*) AS transfers))
FROM `bigquery-public-data.goog_blockchain_ethereum_mainnet_us.token_transfers`
WHERE block_timestamp>=TIMESTAMP '2026-11-08 09:00:00+00' AND block_timestamp<TIMESTAMP '2026-11-15 09:00:00+00'
AND address IN ('0xdac17f958d2ee523a2206206994597c13d831ec7','0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48')
GROUP BY DATE(block_timestamp)
ORDER BY section,payload
