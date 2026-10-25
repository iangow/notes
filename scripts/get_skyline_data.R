# Recreate the Melbourne data used in the 28 August 2025 skyline note.
library(dplyr)
library(readr)
library(rvest)
library(janitor)
library(jsonlite)

roots <- Sys.getenv(c("RAW_DATA_DIR", "DATA_DIR"))
if (any(!nzchar(roots))) {
  stop("Set RAW_DATA_DIR and DATA_DIR before running this script.")
}

raw_path <- file.path(path.expand(roots[["RAW_DATA_DIR"]]), "skylines")
data_path <- file.path(path.expand(roots[["DATA_DIR"]]), "skylines")
for (path in c(raw_path, data_path)) {
  if (!dir.exists(path) && !dir.create(path, recursive = TRUE)) {
    stop("Could not create data directory: ", path)
  }
}

revision <- 1306544759
url <- paste0("https://en.wikipedia.org/w/api.php?action=parse&oldid=",
              revision, "&prop=text%7Crevid&format=json&formatversion=2")
raw_file <- file.path(raw_path, paste0("melbourne_", revision, ".json"))
if (!file.exists(raw_file)) {
  download <- tempfile(pattern = "melbourne-", tmpdir = raw_path,
                       fileext = ".json")
  tryCatch({
    status <- download.file(url, download, mode = "wb",
                            headers = c("User-Agent" =
                              "IanGowNotes/1.0 (https://iangow.github.io/notes/)"))
    downloaded <- fromJSON(download)
    if (status != 0L || is.null(downloaded$parse$revid) ||
        downloaded$parse$revid != revision) {
      stop("The download does not contain the requested Wikipedia revision.")
    }
    if (!file.rename(download, raw_file)) {
      stop("Could not save the Wikipedia response: ", raw_file)
    }
  }, finally = unlink(download))
}

response <- fromJSON(raw_file)
if (is.null(response$parse$revid) || response$parse$revid != revision) {
  stop("The response does not contain the requested Wikipedia revision.")
}

tables <- read_html(response$parse$text) |>
  html_elements("table.wikitable") |>
  html_table(fill = TRUE) |>
  lapply(clean_names)

columns <- c("rank", "name_street_address", "height", "height_2", "built")
matches <- which(vapply(tables, \(x) all(columns %in% names(x)), logical(1)))
if (length(matches) != 1L) {
  stop("Could not identify a unique table containing both height measures.")
}

melbourne <- tables[[matches]] |>
  filter(rank != "Rank") |>
  transmute(building = name_street_address,
            spire_m = parse_number(height),
            roof_m = parse_number(height_2),
            completed = parse_number(built))

output <- file.path(data_path, "melbourne_2025-08-18.csv")
write_csv(melbourne, output)
message("Saved ", nrow(melbourne), " building records to ", output)
