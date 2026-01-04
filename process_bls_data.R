library(tidyverse)

db <- DBI::dbConnect(duckdb::duckdb())

bls_data <-
  farr::load_parquet(db, "bls_all_*", schema = "bls") |>
  mutate(industry_code =
           case_when(industry_code == "31-33" ~ "31",
                     industry_code == "44-45" ~ "44",
                     industry_code == "48-49" ~ "48",
                     .default = industry_code),
         industry_code = as.integer(industry_code)) |>
  filter(industry_code < 100) |>
  # and for now just keep the ownership codes for
  # - (a) total employment levels -- own_code = 0; and
  # - (b) total private sector employment -- own_code = 5
  filter(own_code %in% c(0, 5)) |>
  system_time()

bls_data

duckdb_to_parquet <- function(df, name, schema, data_dir = NULL) {

  db <- dbplyr::remote_con(df)

  if (is.null(data_dir)) data_dir <- Sys.getenv("DATA_DIR")
  data_dir <- file.path(data_dir, schema)

  table_sql <- dbplyr::sql_render(df)
  pq_path <- path.expand(file.path(data_dir,
                                   stringr::str_c(name, ".parquet")))

  sql <- stringr::str_glue("COPY ({table_sql}) ",
                           "TO '{pq_path}' (FORMAT parquet)")

  DBI::dbExecute(db, sql)
  tbl(db, stringr::str_glue("read_parquet('{pq_path}')"))
}

bls_state <-
  bls_data |>
  filter(agglvl_code > 49, agglvl_code < 60) |>
  duckdb_to_parquet(name = "bls_state", schema = "bls") |>
  system_time()

bls_state

bls_county <-
  bls_data |>
  filter(agglvl_code > 69, agglvl_code < 80) |>
  duckdb_to_parquet(name = "bls_county", schema = "bls") |>
  system_time()

bls_county

bls_national <-
  bls_data |>
  filter(agglvl_code == 10) |>
  duckdb_to_parquet(name = "bls_national", schema = "bls") |>
  system_time()

bls_national
