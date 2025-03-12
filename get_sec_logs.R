library(DBI)
library(tidyverse)
library(httr2)         # request(), req_*(), resp_body_html()
library(rvest)
options(HTTPUserAgent = "iandgow@fastmail.com")

get_log_files <- function(year) {

  sec_url <- str_c("https://www.sec.gov/files/edgar", year, ".html")

  resp <-
    request(sec_url) |>
    req_user_agent(getOption("HTTPUserAgent")) |>
    req_perform() |>
    resp_body_html() |>
    html_elements("body")

  urls <-
    resp |>
    html_elements("a") |>
    html_attr("href") |>
    as.character(x = _)

  urls
}

get_zip_filename <- function(url, schema = "sec_logs") {
  file_name <- str_replace(url, "^.*Public-EDGAR-log-file-data/(.*\\.zip)$",
                           "\\1")
  file.path(Sys.getenv("RAW_DATA_DIR"), schema, file_name)
}

get_pq_filename <- function(url, schema = "sec_logs") {
  file_name <- str_replace(url, "^.*Public-EDGAR-log-file-data/(.*)\\.zip$",
                           "\\1.parquet")
  file.path(Sys.getenv("DATA_DIR"), schema, file_name)
}

process_csv <- function(csv_file, pq_file) {
  if (!dir.exists(dirname(pq_file))) dir.create(dirname(pq_file),
                                                recursive = TRUE)
  # CASE WHEN cik = '' THEN NULL ELSE cik END AS
  db <- dbConnect(duckdb::duckdb(), dbdir = "sec_logs.duckdb")

  dbExecute(db, "SET memory_limit = '24GB'")

  sql <- paste0(
    "
    COPY (
    WITH
    csv_raw AS (
      SELECT *
      FROM read_csv('", csv_file, "',
                            header = true,
                            quote = '\"',
                            columns = {
                              'time': 'TEXT',
                              'uri_path': 'TEXT'},
                            null_padding=true)),

    fix_time AS (
      SELECT trim(replace(time, '\"', '')) AS time, uri_path,
        regexp_extract(uri_path, 'data/([0-9]{1,10})/', 1) AS cik,
        regexp_extract(uri_path, '([0-9]{10})-[0-9]{2}-[0-9]{6}', 1) AS cik_alt
      FROM csv_raw),

    convert_time AS (
      SELECT strptime(time, '%Y-%m-%dT%H:%M:%S.%f%z') AS time,
        uri_path, cik, cik_alt
      FROM fix_time
      WHERE (time != ''))

    SELECT time, uri_path,
      (CASE
        WHEN cik = '' AND cik_alt = '' THEN NULL
        WHEN cik = '' THEN cik_alt
        ELSE cik END)::bigint AS cik
    FROM convert_time
    ORDER BY cik) TO '", pq_file, "' (FORMAT 'parquet', ROW_GROUP_SIZE 10000)")
  res <- dbExecute(db, sql)
  dbDisconnect(db)
}

log_to_pq <- function(url, schema = "sec_logs") {
  temp_zip <- get_zip_filename(url)
  if (!dir.exists(dirname(temp_zip))) dir.create(dirname(temp_zip),
                                                 recursive = TRUE)
  if (!file.exists(temp_zip)) download.file(url, temp_zip)

  pq_file <- get_pq_filename(url, schema = schema)
  if (!file.exists(pq_file)) {
    csv_file <- unzip(temp_zip)
    res <- process_csv(csv_file, pq_file)
    unlink(csv_file)
    res
  }
}

logs <- get_log_files(2024)

# One file doesn't work!
lapply(logs[!str_detect(logs, "log20240424.zip")], log_to_pq)
