library(tidyverse)
library(arrow)
library(lubridate)

required_dirs <- Sys.getenv(c("RAW_DATA_DIR", "DATA_DIR"))
if (any(!nzchar(required_dirs))) {
  stop("Set RAW_DATA_DIR and DATA_DIR before running get_form_aps.R.")
}
raw_path <- file.path(path.expand(required_dirs[["RAW_DATA_DIR"]]), "pcaob")
data_path <- file.path(path.expand(required_dirs[["DATA_DIR"]]), "pcaob")
for (path in c(raw_path, data_path)) {
  if (!dir.exists(path) && !dir.create(path, recursive = TRUE)) {
    stop("Could not create data directory: ", path)
  }
}

zip_file <- file.path(raw_path, "FirmFilings.zip")
parquet_file <- file.path(data_path, "form_aps.parquet")

url <- "https://pcaobus.org/assets/PCAOBFiles/FirmFilings.zip"

if (!file.exists(zip_file)) {
  # Cache only a completed ZIP; a failed download should not be reused.
  downloaded <- tempfile(tmpdir = raw_path, fileext = ".zip")
  tryCatch({
    status <- download.file(url, downloaded, mode = "wb")
    if (status != 0L) stop("Could not download the PCAOB ZIP.")
    if (!"FirmFilings.csv" %in% unzip(downloaded, list = TRUE)$Name) {
      stop("The PCAOB download does not contain FirmFilings.csv.")
    }
    if (!file.rename(downloaded, zip_file)) {
      stop("Could not save the PCAOB ZIP to ", zip_file)
    }
  }, finally = unlink(downloaded))
}

fix_names <- function(names) {
  names <- tolower(gsub("\\s+", "_", names))
  names <- gsub("<", "lt", names)
  names <- gsub(">", "gt", names)
  names <- gsub("%", "_pct", names)
  names <- gsub("[)(_]+", "_", names)
  names
}

process_date <- function(x) {
  # The export mixes US dates with AM/PM times and ISO dates.
  parsed <- parse_date_time(as.character(x),
                           orders = c("mdy IMSp", "mdy", "ymd HMS", "ymd"),
                           tz = "America/New_York")
  as.Date(parsed, tz = "America/New_York")
}

process_dual_dates <- function(x) {
  str_split(x, fixed("#^#")) |>
    map(process_date)
}

form_aps <-
  read_csv(zip_file, guess_max = Inf, show_col_types = FALSE) |>
  rename_with(fix_names) |>
  mutate(across(c(latest_form_ap_filing, ends_with("id")), as.integer),
         across(c(audit_report_date, fiscal_period_end_date, signed_date),
                process_date),
         filing_date = parse_date_time(as.character(filing_date),
                                      orders = c("mdy IMSp", "ymd HMS"),
                                      tz = "America/New_York"),
         audit_dual_date = process_dual_dates(audit_dual_date))

write_parquet(form_aps, parquet_file)
