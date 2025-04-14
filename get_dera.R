library(tidyverse)
library(DBI)

if (!grepl("@", getOption("HTTPUserAgent"))) {
  stop('You should run `options(HTTPUserAgent = "your_name@email.com") before running this script.')
}

files_df <-
  expand_grid(year = 2025:2025, quarter = 1:4) |>
  mutate(file = paste0(year, "q", quarter)) |>
  filter(file <= "2025q1")

get_data <- function(file) {
  url <- str_c("https://www.sec.gov/files/dera/data/",
               "financial-statement-data-sets/", file, ".zip")

  t <- tempfile(fileext = ".zip")

  download.file(url, t)

  pq_dir <- file.path(Sys.getenv("DATA_DIR"), "dera")

  if (!dir.exists(pq_dir)) dir.create(pq_dir, recursive = TRUE)

  db <- dbConnect(duckdb::duckdb())

  sub <- read_tsv(unz(t, "sub.txt"),
                  col_types = "cdcdcccccccccccccccccdcdccddcdcddcdc") |>
    mutate(across(c(changed, filed, period), ymd)) |>
    copy_to(db, df = _, name = "sub", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("sub_", file, ".parquet"))

  dbExecute(db, str_c("COPY sub TO '", pq_file, "'"))

  pre <- read_tsv(unz(t, "pre.txt"),
                  col_types = "cddcdccccd") |>
    copy_to(db, df = _, name = "pre", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("pre_", file, ".parquet"))

  dbExecute(db, str_c("COPY pre TO '", pq_file, "'"))

  num <- read_tsv(unz(t, "num.txt"),
                  col_types = "ccccdcccdc") |>
    mutate(ddate = ymd(ddate)) |>
    copy_to(db, df = _, name = "num", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("num_", file, ".parquet"))

  dbExecute(db, str_c("COPY num TO '", pq_file, "'"))

  tag <-
    read_tsv(unz(t, "tag.txt"), col_types = "ccddccccc") |>
    copy_to(db, df = _, name = "tag", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("tag_", file, ".parquet"))

  dbExecute(db, str_c("COPY tag TO '", pq_file, "'"))

  dbDisconnect(db)
}

get_type_string <- function(df) {
  types <- tibble(type = map(df, class))
  types |>
    mutate(
      type_str = case_when(
        type == "character" ~ "c",
        type == "double" ~ "d",
        type == "numeric" ~ "d",
        type == "Date" ~ "D",
        inherits(type, "POSIXct") ~ "T",
        .default = "c"
      )
    ) |>
    select(type_str) |>
    pull() |>
    paste0(collapse = "")
}

map(files_df$file, get_data)
