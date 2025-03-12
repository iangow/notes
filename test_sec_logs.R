library(DBI)
library(tidyverse)
library(farr)

db <- dbConnect(duckdb::duckdb())

load_parquet <- function(conn, table, schema = "",
                         data_dir = Sys.getenv("DATA_DIR")) {
  file_path <- file.path(data_dir, schema,
                         paste0(table, ".parquet"))
  df_sql <- paste0("SELECT * FROM read_parquet('", file_path, "',
                   filename = true)")
  dplyr::tbl(conn, dplyr::sql(df_sql))
}

log_files <-
  load_parquet(db, table = "*/*/log*", schema = "sec_logs") |>
  mutate(date = as.Date(strptime(regexp_extract(filename, 'log([0-9]{8})', 1L),
                                 '%Y%m%d'))) |>
  select(-filename)

log_files |>
  count(date) |>
  arrange(date) |>
  collect() |>
  system_time()

subset_log_files <- function(one_cik) {
  log_files |>
    filter(cik == one_cik) |>
    compute()
}

tesla <- subset_log_files(1420590) |> system_time()
tesla |> count()
tesla |> count(date, sort = TRUE)
