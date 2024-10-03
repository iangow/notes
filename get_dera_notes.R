library(httr2)         # request(), req_*(), resp_body_html()
library(rvest)


sec_url <- "https://www.sec.gov/data-research/financial-statement-notes-data-sets"

resp <-
  request(sec_url) |>
  req_user_agent(getOption("HTTPUserAgent")) |>
  req_perform() |>
  resp_body_html() |>
  html_elements("body")

zip_files <-
  resp |>
  html_elements("a") |>
  as.character(x = _) |>
  as_tibble() |>
  filter(str_detect(value, "zip")) |>
  mutate(file = str_replace(value, "^.*data-sets/(.*.zip).*$", "\\1"))

get_data <- function(file) {
  url <- str_c("https://www.sec.gov/files/dera/data/",
               "financial-statement-notes-data-sets/", file)

  period <- str_replace(file, "^(.*)_notes.*$", "\\1")
  t <- tempfile(fileext = ".zip")

  download.file(url, t)

  pq_dir <- file.path(Sys.getenv("DATA_DIR"), "dera_notes")

  if (!dir.exists(pq_dir)) dir.create(pq_dir, recursive = TRUE)

  db <- dbConnect(duckdb())

  # sub ----
  sub <- read_tsv(unz(t, "sub.tsv"),
                  col_types = "cdcccccccccccccccccccdcdccddcdcddcdcddcd") |>
    mutate(across(c(changed, filed, period), ymd),
           across(c(accepted), ymd_hms)) |>
    copy_to(db, df = _, name = "sub_notes", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("sub_notes_", period, ".parquet"))

  dbExecute(db, str_c("COPY sub_notes TO '", pq_file, "'"))

  # tag ----
  tag <- read_tsv(unz(t, "tag.tsv"),
                  col_types = "ccddccccc") |>
    copy_to(db, df = _, name = "tag_notes", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("tag_notes_", period, ".parquet"))

  dbExecute(db, str_c("COPY tag_notes TO '", pq_file, "'"))

  # dim ----
  dim <- read_tsv(unz(t, "dim.tsv"), col_types = "ccd") |>
    copy_to(db, df = _, name = "dim_notes", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("dim_notes_", period, ".parquet"))

  dbExecute(db, str_c("COPY dim_notes TO '", pq_file, "'"))

  # num ----
  num <- read_tsv(unz(t, "num.tsv"),
                  col_types = "cccddccddcddcddd") |>
    mutate(across(c(ddate), ymd)) |>
    copy_to(db, df = _, name = "num_notes", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("num_notes_", period, ".parquet"))

  dbExecute(db, str_c("COPY num_notes TO '", pq_file, "'"))

  # txt ----
  txt <- read_tsv(unz(t, "ren.tsv"),
                  col_types = "cdccccccdd") |>
    copy_to(db, df = _, name = "txt_notes", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("txt_notes_", period, ".parquet"))

  dbExecute(db, str_c("COPY txt_notes TO '", pq_file, "'"))

  # txt ----
  ren <- read_tsv(unz(t, "ren.tsv"),
                  col_types = "cdccccccdd") |>
    copy_to(db, df = _, name = "ren_notes", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("ren_notes_", period, ".parquet"))

  dbExecute(db, str_c("COPY ren_notes TO '", pq_file, "'"))

  # pre ----
  pre <-
    read_tsv(unz(t, "pre.tsv"), col_types = "cddcdccccd") |>
    copy_to(db, df = _, name = "pre_notes", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("pre_notes_", period, ".parquet"))

  dbExecute(db, str_c("COPY pre_notes TO '", pq_file, "'"))

  # cal ----
  cal <- read_tsv(unz(t, "cal.tsv"), col_types = "cdddcccc") |>
    copy_to(db, df = _, name = "cal_notes", overwrite = TRUE)

  pq_file <- file.path(pq_dir, str_c("cal_notes_", period, ".parquet"))

  dbExecute(db, str_c("COPY cal_notes TO '", pq_file, "'"))

  dbDisconnect(db)
}

map(zip_files$file[10:20], get_data)
