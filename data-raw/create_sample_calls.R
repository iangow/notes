library(tidyverse)
library(DBI)
db <- dbConnect(RPostgres::Postgres())

calls <- tbl(db, Id(schema = "streetevents", table = "calls"))
sample_calls <-
  calls |>
  rename(ticker = company_ticker) |>
  filter(ticker %in% c("AAPL", "MSFT"),
         start_date > "2003-01-01",
         event_type == 1) |>
  mutate(start_date = as.character(start_date)) |>
  select(ticker, start_date) |>
  collect()

sample_calls |>
  arrange(ticker, start_date) |>
  write_csv("data/sample_calls.csv")
