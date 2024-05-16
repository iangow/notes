library(tidyverse)
library(arrow)

data_path <- "data"
t <- file.path(data_path, "FirmFilings.zip")
parquet_file <- file.path(data_path, "form_aps.parquet")

url <- "https://pcaobus.org/assets/PCAOBFiles/FirmFilings.zip"

if (!file.exists(t)) {
  if (!dir.exists(data_path)) {
    dir.create(data_path)
  }
  download.file(url, t)
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
  x <- str_replace(x,
                   "^([0-9]{4})-([0-9]{2})-([0-9]{2})(.*)$",
                   "\\2/\\3/\\1\\4")
  x <- str_replace(x, "([0-9]{2})$", "\\1 AM")
  parse_date(x, locale = locale(date_format = "%m/%d/%Y %H:%H:%S %p"))
}

process_dual_dates <- function(x) {
  x <- str_split(x, "#\\^#")
  map(x, \(x) as.Date(parse_date_time(x,
                                      orders = c("ymdHMS", "ymd"),
                                      tz = "America/New_York")))

}

form_aps <-
  read_csv(t, guess_max = Inf, show_col_types = FALSE) |>
  rename_with(fix_names) |>
  mutate(across(c(latest_form_ap_filing, ends_with("id")), as.integer),
         across(c(audit_report_date, fiscal_period_end_date, signed_date),
                process_date),
         filing_date = parse_date_time(filing_date,
                                       orders = "mdyHMSp",
                                       tz = "America/New_York"),
         audit_dual_date = process_dual_dates(audit_dual_date))

write_parquet(form_aps, parquet_file)
