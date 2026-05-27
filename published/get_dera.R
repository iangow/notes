library(httr2)         # request(), req_*(), resp_body_html()
library(rvest)
library(tidyverse)
library(DBI)
library(arrow)

if (!grepl("@", getOption("HTTPUserAgent"))) {
  stop(paste0('You should run `options(HTTPUserAgent = "your_name@email.com")`',
              " before running this script."))
}

if (Sys.getenv("DATA_DIR") == "") {
  stop(paste0('You should run `Sys.setenv(DATA_DIR = "some_dir")`',
              " before running this script."))
}

# Get information on available zip files ----
sec_url <- "https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets"

resp <-
  request(sec_url) |>
  req_user_agent(getOption("HTTPUserAgent")) |>
  req_perform() |>
  resp_body_html() |>
  html_elements("body")

get_last_modified <- function(url) {
  resp <-
    request(url) |>
    req_method("HEAD") |>
    req_user_agent(getOption("HTTPUserAgent")) |>
    req_perform()

  headers <- resp |> resp_headers()
  headers[["last-modified"]]
}

get_file_modified_date <- function(file) {
  url <- str_c("https://www.sec.gov/files/dera/data/",
               "financial-statement-data-sets/", file)
  get_last_modified(url)
}

get_file_modified_date <- Vectorize(get_file_modified_date)

last_modified_scraped <-
  resp |>
  html_elements("a") |>
  as.character(x = _) |>
  as_tibble() |>
  filter(str_detect(value, "zip")) |>
  mutate(file = str_replace(value, "^.*data-sets/(.*.zip).*$", "\\1")) |>
  mutate(last_modified = get_file_modified_date(file)) |>
  select(file, last_modified)

pq_dir <- file.path(Sys.getenv("DATA_DIR"), "dera")
pq_path <- file.path(pq_dir, "last_modified.parquet")

if (file.exists(pq_path)) {
  last_modified <- read_parquet(pq_path)
} else {
  last_modified <- tibble(file = NA, last_modified = NA)
}

to_update <-
  last_modified_scraped |>
  left_join(last_modified,
            by = "file",
            suffix = c("_new", "_old")) |>
  filter(is.na(last_modified_old) |
           last_modified_new != last_modified_old)

# Function to process a zip file ----
get_data <- function(file) {
  url <- str_c("https://www.sec.gov/files/dera/data/",
               "financial-statement-data-sets/", file)

  period <- str_replace(file, "\\.zip$", "")
  t <- tempfile(fileext = ".zip")

  download.file(url, t)

  pq_dir <- file.path(Sys.getenv("DATA_DIR"), "dera")

  if (!dir.exists(pq_dir)) dir.create(pq_dir, recursive = TRUE)

  db <- dbConnect(duckdb::duckdb())

  ## sub ----
  sub <- read_tsv(unz(t, "sub.txt"),
                  col_types = "cdcdcccccccccccccccccdcdccddcdcddcdc") |>
    mutate(across(c(changed, filed, period), ymd),
           across(c(accepted), ymd_hms)) |>
    copy_to(db, df = _, name = "sub", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("sub_", period, ".parquet"))

  dbExecute(db, str_c("COPY sub TO '", pq_file, "'"))

  ## tag ----
  tag <- read_tsv(unz(t, "tag.txt"),
                  col_types = "ccddccccc") |>
    copy_to(db, df = _, name = "tag", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("tag_", period, ".parquet"))

  dbExecute(db, str_c("COPY tag TO '", pq_file, "'"))

  ## num ----
  num <- read_tsv(unz(t, "num.txt"),
                  col_types = "ccccdcccdc") |>
    mutate(across(c(ddate), ymd)) |>
    copy_to(db, df = _, name = "num", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("num_", period, ".parquet"))

  dbExecute(db, str_c("COPY num TO '", pq_file, "'"))

  ## pre ----
  pre <-
    read_tsv(unz(t, "pre.txt"), col_types = "cddcdccccd") |>
    copy_to(db, df = _, name = "pre", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("pre_", period, ".parquet"))

  dbExecute(db, str_c("COPY pre TO '", pq_file, "'"))

  dbDisconnect(db)
}

# Apply function to get data ----
map(to_update$file, get_data)

save_parquet <- function(df, name, schema = "",
                         path = Sys.getenv("DATA_DIR")) {
  file_path <- file.path(path, schema, str_c(name, ".parquet"))
  arrow::write_parquet(collect(df), sink = file_path)
}

last_modified_scraped |>
  save_parquet(name = "last_modified", schema = "dera")
