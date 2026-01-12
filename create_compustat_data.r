# This script pulls in and creates basic Compustat measures (based on annual Compustat data)
library(tidyverse)
library(dbplyr) # for window_order()
library(farr)

# Set up WRDS object
db <- dbConnect(duckdb::duckdb())

compustat <-
  # Computstat
  load_parquet(db, "funda", "comp") |>
  # Impose date filter
  # Filter years after 2000
  filter(fyear >= 2000,
         # Impose filter to obtain unique gvkey-datadate records
         indfmt == 'INDL' & datafmt == 'STD',
         popsrc == 'D' & consol == 'C') |>
  # Create new variables
  mutate(sich = as.character(sich),
         # Convert 4 digit SIC code to 2 digits
         sic2 = substr(sich, 1, 2),
         # Create market capitalization/log size and book-to-mkt variables variable
         # Mkt Cap.
         mkt_cap = csho * abs(prcc_f),
         mkt_cap = if_else(mkt_cap <= 0, NA, mkt_cap),
         bv_ff = (coalesce(seq, ceq + pstk, at - lt) +
                    coalesce(txditc, txdb + itcb, 0) -
                    coalesce(pstkrv, pstkl, pstk, 0)),
         bv_ff = if_else(bv_ff > 0, bv_ff, NA_real_),
         bk_mkt = bv_ff / mkt_cap,
         # Create log variables
         ln_size = log(mkt_cap)) |>
  # Create lagged variables by gvkey
  # Order data by gvkey-date (to calculate lagged variables properly)
  # Operating accruals calculation
  # (This has been checked against the below sources).
  group_by(gvkey) |>
  window_order(gvkey, datadate) |>
  mutate(avg_at = (at + lag(at)) / 2,
         d_ca = act - lag(act),
         d_cash = che - lag(che),
         d_cl = lct - lag(lct),
         d_std = dlc - lag(dlc),
         d_tp = txp - lag(txp),
         # This is how the original Sloan (1996, TAR) calculates this
         acc_raw_bs = (d_ca - d_cash) - (d_cl - d_std - d_tp) - dp,
         # Calculate in accordance with Hribar and Collins (2002, JAR) if possible
         acc_raw = coalesce(ib - oancf, acc_raw_bs),
         acc = if_else(avg_at != 0, acc_raw / avg_at, NA),
         # This is also in accordance with Ball et al. (2016, JFE)
         # Percent accruals
         pctacc = case_when(
           is.na(oancf) & ib==0 ~ acc_raw_bs /.01,
           ib==0 ~ (ib - oancf) / .01,
           is.na(oancf) ~ acc_raw_bs / abs(ib),
           TRUE ~ if_else(ib != 0, (ib - oancf) / abs(ib), NA)),
         at = if_else(at <= 0, NA, at),
         at_lag1 = lag(at, n = 1),
         at_lag2 = lag(at, n = 2),
         # Calculate asset growth and
         asset_growth = (at - at_lag1) / at_lag1,
         roa = ib / (0.5 * (at + at_lag1))) |>
  ungroup() |>
  # Select necessary columns
  select(gvkey, sich, sic2, datadate, fyear, mkt_cap, bk_mkt, ln_size,
         asset_growth, roa, at, at_lag1, at_lag2, ib, acc, pctacc) |>
  # Rename mkt cap column
  rename(mkt_cap_comp = mkt_cap) |>
  # Select first entry in case of duplicates in Year-end
  group_by(gvkey, year(datadate)) |>
  window_order(gvkey, datadate) |>
  filter(row_number() == 1) |>
  ungroup() |>
  # Save data
  duckdb_to_parquet(name = "compustat_annual",
                    schema = "data", data_dir = ".")
