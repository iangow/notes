library(tidyverse)
library(DBI)

pq_dir <- file.path(Sys.getenv("DATA_DIR"), "imdb")

imdb_url_to_pq <- function(url) {

  db <- dbConnect(duckdb::duckdb())

  table_name <- function(x) {
    x <- str_replace(x, "\\.tsv\\.gz$", "")
    str_replace(x, "\\.", "_")
  }

  download.file(url, basename(url))

  filename <- basename(url)
  table <- table_name(filename)

  pq_file <- file.path(pq_dir, str_c(table, ".parquet"))
  df <- tbl(db, str_c("read_csv('", filename, "', quote = '',
                         nullstr = '\\N')"))

  if (table == "name_basics") {
    df <-
      df |>
      mutate(primaryProfession = regexp_split_to_array(primaryProfession, ","),
             knownForTitles = regexp_split_to_array(knownForTitles, ","))

  } else if (table == "title_crew") {
      df <-
        df |>
        mutate(directors = regexp_split_to_array(directors, ","),
               writers = regexp_split_to_array(writers, ","))

  } else if (table == "title_basics") {
    df <-
      df |>
      mutate(isAdult = as.logical(isAdult),
             genres = regexp_split_to_array(genres, ","))

  } else if (table == "title_akas") {
    df <-
      df |>
      mutate(isOriginalTitle = as.logical(isOriginalTitle),
             types = regexp_split_to_array(types, "\\x{0002}"),
             attributes = regexp_split_to_array(attributes, "\\x{0002}"))

  }

  df <- compute(df, name = table)

  res <- dbExecute(db, str_c("COPY ", table, " TO '", pq_file, "'"))
  dbDisconnect(db)
  unlink(filename)
  res
}

urls <-
  c("https://datasets.imdbws.com/name.basics.tsv.gz",
    "https://datasets.imdbws.com/title.basics.tsv.gz",
    "https://datasets.imdbws.com/title.crew.tsv.gz",
    "https://datasets.imdbws.com/title.akas.tsv.gz",
    "https://datasets.imdbws.com/title.episode.tsv.gz",
    "https://datasets.imdbws.com/title.principals.tsv.gz",
    "https://datasets.imdbws.com/title.ratings.tsv.gz")

map(urls, imdb_url_to_pq)

