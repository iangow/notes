system.time(source("get_bls_data_orig.R"))

get_bls_data <- function(year, schema = "bls", data_dir = NULL,
                         raw_data_dir = NULL) {

  data_dir <- file.path(Sys.getenv("DATA_DIR"), schema)
  if (!dir.exists(data_dir)) dir.create(data_dir, recursive = TRUE)

  raw_data_dir <- file.path(Sys.getenv("RAW_DATA_DIR"), schema)
  if (!dir.exists(raw_data_dir)) dir.create(raw_data_dir, recursive = TRUE)

  url <- stringr::str_glue("https://data.bls.gov/cew/data/files/{year}",
                  "/csv/{year}_annual_singlefile.zip")
  t <- file.path(raw_data_dir, basename(url))
  if (!file.exists(t)) download.file(url, t)

  pq_path <- stringr::str_c("bls_all_", year, ".parquet")
  readr::read_csv(t, show_col_types = FALSE, guess_max = 100000) |>
    arrow::write_parquet(sink = file.path(data_dir, pq_path))
  return(TRUE)
}

system.time(lapply(2001:2003L, get_bls_data))

get_bls_data_duckdb <- function(year) {

  data_dir <- file.path(Sys.getenv("DATA_DIR"), schema)
  if (!dir.exists(data_dir)) dir.create(data_dir, recursive = TRUE)

  raw_data_dir <- file.path(Sys.getenv("RAW_DATA_DIR"), schema)
  if (!dir.exists(raw_data_dir)) dir.create(raw_data_dir, recursive = TRUE)

  url <- stringr::str_glue("https://data.bls.gov/cew/",
                           "data/files/{year}",
                           "/csv/{year}_annual_singlefile.zip")
  t <- path.expand(file.path(raw_data_dir, basename(url)))
  if (!file.exists(t)) download.file(url, t)

  csv_file <- unzip(t)

  pq_path <- stringr::str_c("bls_all_", year, ".parquet")
  pq_path <- path.expand(file.path(data_dir, pq_path))
  db <- DBI::dbConnect(duckdb::duckdb())

  sql <- stringr::str_glue("COPY (SELECT * FROM read_csv('{csv_file}')) ",
                           "TO '{pq_path}' (FORMAT parquet)")

  res <- DBI::dbExecute(db, sql)
  DBI::dbDisconnect(db)
  unlink(csv_file)
  res
}


system.time(lapply(2001:2019L, get_bls_data_duckdb))
