# G10 Real Policy-Stance Shift Campaign

Campaign 9 is one predeclared test of changing central-bank restrictiveness. It
is not a carry strategy and does not assume that a high interest-rate currency
must appreciate.

At each common month-end, the policy rate is reduced by timestamp-valid annual
CPI inflation. The foreign real-policy rate is compared with the US real-policy
rate, and the three-month change in that differential is measured. A currency
is active only when the absolute shift is at least 25 basis points and its
three-month spot return confirms the same direction. Active currencies are
equally weighted for the next month.

The only cost cases are 10 and 20 basis points round trip. The locked controls
reverse direction, use one-month-stale information, and permute currency labels
with a fixed hash. No threshold, lookback, confirmation, or holding-period sweep
is permitted after results are inspected.

The ECB source motivates the relationship between expected tightening and
currency appreciation, but this campaign does not reproduce its sovereign
yield-curve factor. It is a deliberately simpler policy-rate replication and
is labelled accordingly.

All inputs are public, account-free BIS and OECD data. The campaign has no
trading credentials, order authority, or downstream activation permission.
