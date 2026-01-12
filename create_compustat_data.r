# This script pulls in and creates basic Compustat measures (based on annual Compustat data)
library(tidyverse)
library(RPostgres)
library(lubridate)

# Set up WRDS object
wrds <- dbConnect(Postgres(),
                  host='wrds-pgdata.wharton.upenn.edu',
                  port=9737,
                  user='iangow',
                  # password='PASSWORD',
                  dbname='wrds',
                  sslmode='require')

# Computstat
compustat <- tbl(wrds, sql("SELECT * FROM comp.funda"))

# Impose date filter
compustat <- compustat %>%
  filter(fyear >= 2000) # Filter years after 2000

# Impose filter to obtain unique gvkey-datadate records
compustat <- compustat %>%
  filter(indfmt == 'INDL' & datafmt == 'STD' & popsrc == 'D' & consol == 'C')  %>%
  collect()

# Create Compustat dataset to merge #####################################################
# Create new variables
compustat <- compustat %>%
  # Convert 4 digit SIC code to 2 digits
  mutate(sich = as.character(sich)) %>%
  mutate(sic2 = substr(sich, 1, 2)) %>%
  # Create market capitalization/log size and book-to-mkt variables variable
  # Mkt Cap.
  mutate(mkt_cap = csho*abs(prcc_f),
         mkt_cap = if_else(as.numeric(mkt_cap) <= 0, as.numeric(NA), mkt_cap)) %>%
  mutate(
  bv_ff = (coalesce(seq, ceq + pstk, at - lt) + coalesce(txditc, txdb + itcb, 0) -
             coalesce(pstkrv, pstkl, pstk, 0)),
  bv_ff = if_else(bv_ff > 0, bv_ff, NA_real_),
      bk_mkt = bv_ff/mkt_cap) %>%
  # Create log variabes
  mutate(ln_size = log(mkt_cap))

# Create lagged variables by gvkey
# Order data by gvkey-date (to calculate lagged variables properly)
compustat <- compustat %>%
  arrange(gvkey, datadate)

# Operating accruals calculation (This has been checked against the below sources).
compustat <- compustat %>%
  group_by(gvkey) %>%
mutate(acc= coalesce(
  # Calculate in accordinace with Hribar and Collins (2002, JAR) if possible.
  (ib-oancf) /  ((at+lag(at))/2),
  # This is how the original Sloan (1996, TAR) calculates this.
  # This is also in accordance with Ball et al. (2016, JFE)
  ((act-lag(act) - (che-lag(che))) - ((lct-lag(lct))-(dlc-lag(dlc))-(txp-lag(txp))) - dp)/  ((at+lag(at))/2))) %>%

  # Percent accurals
  mutate(pctacc = case_when(
    is.na(oancf) & ib==0 ~ (	(act-lag(act) - (che-lag(che))) - (  (lct-lag(lct))-(dlc-lag(dlc))-(txp-lag(txp))-dp ) )/.01,
    ib==0 ~ (ib-oancf)/.01,
    is.na(oancf) ~ (	(act-lag(act) - (che-lag(che))) - (  (lct-lag(lct))-(dlc-lag(dlc))-(txp-lag(txp))-dp ) )/abs(ib),
    TRUE~ (ib-oancf)/abs(ib)
  )) %>%
  ungroup()

# Create lagged assets measures
compustat <- compustat %>%
  mutate(at = if_else(at <= 0, as.numeric(NA), at)) %>%
  arrange(gvkey, datadate) %>%
  group_by(gvkey) %>%
  # Take lags
  mutate(at_lag1 = lag(at, n = 1),
         at_lag2 = lag(at, n = 2)) %>%
  ungroup() %>%
  # Calculate asset growth and
  mutate(asset_growth = (at - at_lag1)/at_lag1,
         roa = ib/(0.5*(at+at_lag1)))

# Select necessary columns
compustat <- compustat %>%
  select(gvkey, sich, sic2, datadate, fyear, mkt_cap, bk_mkt, ln_size, asset_growth, roa, at, at_lag1, at_lag2, ib, acc, pctacc)

# Rename mkt cap column
compustat <- compustat %>%
  rename(mkt_cap_comp = mkt_cap)

# Select first entry in case of duplicates in Year-end
compustat <- compustat %>%
  arrange(gvkey, datadate) %>%
  group_by(gvkey, year(datadate)) %>%
  slice(1) %>%
  ungroup()

# Save data
saveRDS(compustat, file = 'compustat_annual.RDS')

