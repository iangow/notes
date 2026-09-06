library(DBI)
library(duckdb)
library(glue)

data_dir <- Sys.getenv(
  "DATA_DIR",
  file.path(path.expand("~"), "Dropbox", "pq_data")
)
default_old_filings_path <- file.path(
  data_dir,
  "submissions",
  "filings.parquet.bak-20260906-105247"
)
default_new_filings_path <- file.path(
  data_dir,
  "edgar",
  "filings.parquet.bak-20260906-bad-timeline"
)

if (!file.exists(default_new_filings_path)) {
  default_new_filings_path <- file.path(data_dir, "edgar", "filings.parquet")
}

old_filings_path <- Sys.getenv("OLD_FILINGS_PATH", default_old_filings_path)
new_filings_path <- Sys.getenv("NEW_FILINGS_PATH", default_new_filings_path)

sql_quote <- function(x) {
  gsub("'", "''", x, fixed = TRUE)
}

old_filings_sql <- sql_quote(old_filings_path)
new_filings_sql <- sql_quote(new_filings_path)

db <- dbConnect(duckdb::duckdb(), timezone_out = "America/New_York")
on.exit(dbDisconnect(db, shutdown = TRUE), add = TRUE)

invisible(dbExecute(db, "LOAD icu"))
invisible(dbExecute(db, "SET TIME ZONE 'America/New_York'"))

run_query <- function(title, sql) {
  cat("\n", title, "\n", sep = "")
  cat(strrep("-", nchar(title)), "\n", sep = "")
  print(dbGetQuery(db, sql), row.names = FALSE)
}

cat("Old filings path: ", old_filings_path, "\n", sep = "")
cat("New filings path: ", new_filings_path, "\n", sep = "")

run_query(
  "Input file summaries",
  glue("
    SELECT 'old' AS file,
           count(*) AS n,
           min(acceptanceDateTime) AS min_acceptanceDateTime,
           max(acceptanceDateTime) AS max_acceptanceDateTime
    FROM read_parquet('{old_filings_sql}')
    UNION ALL
    SELECT 'new' AS file,
           count(*) AS n,
           min(acceptanceDateTime) AS min_acceptanceDateTime,
           max(acceptanceDateTime) AS max_acceptanceDateTime
    FROM read_parquet('{new_filings_sql}')
  ")
)

common_cte <- glue("
  WITH old_filings AS (
    SELECT cik, accessionNumber, filingDate, form,
           acceptanceDateTime AS old_acceptanceDateTime
    FROM read_parquet('{old_filings_sql}')
  ),
  new_filings AS (
    SELECT cik, accessionNumber, filingDate, form,
           acceptanceDateTime AS new_acceptanceDateTime
    FROM read_parquet('{new_filings_sql}')
  ),
  common AS (
    SELECT n.cik,
           n.accessionNumber,
           coalesce(n.filingDate, o.filingDate) AS filingDate,
           coalesce(n.form, o.form) AS form,
           o.old_acceptanceDateTime,
           n.new_acceptanceDateTime,
           date_diff('minute',
                     o.old_acceptanceDateTime,
                     n.new_acceptanceDateTime) AS diff_min
    FROM new_filings AS n
    INNER JOIN old_filings AS o USING (cik, accessionNumber)
    WHERE year(n.new_acceptanceDateTime) >= 2003
  )
")

run_query(
  "Timestamp diff among common rows, 2003+",
  glue("
    {common_cte}
    SELECT diff_min, count(*) AS n
    FROM common
    GROUP BY diff_min
    ORDER BY n DESC, diff_min
  ")
)

run_query(
  "Diff 240/300 summary",
  glue("
    {common_cte}
    SELECT diff_min,
           count(*) AS n,
           min(new_acceptanceDateTime) AS min_new_acceptanceDateTime,
           max(new_acceptanceDateTime) AS max_new_acceptanceDateTime,
           count(*) FILTER (
             WHERE form IN ('3', '3/A', '4', '4/A', '5', '5/A')
           ) AS ownership,
           count(*) FILTER (WHERE form = 'EFFECT') AS effect,
           count(DISTINCT form) AS distinct_forms
    FROM common
    WHERE diff_min IN (240, 300)
    GROUP BY diff_min
    ORDER BY diff_min
  ")
)

run_query(
  "Top forms among diff 240/300 rows",
  glue("
    {common_cte}
    SELECT diff_min, form, count(*) AS n
    FROM common
    WHERE diff_min IN (240, 300)
    GROUP BY diff_min, form
    QUALIFY row_number() OVER (
      PARTITION BY diff_min
      ORDER BY count(*) DESC, form
    ) <= 15
    ORDER BY diff_min, n DESC, form
  ")
)

run_query(
  "Diff 240/300 rows by year",
  glue("
    {common_cte}
    SELECT diff_min,
           year(new_acceptanceDateTime) AS year,
           count(*) AS n
    FROM common
    WHERE diff_min IN (240, 300)
    GROUP BY diff_min, year
    ORDER BY diff_min, year
  ")
)

run_query(
  "Old and new hour distribution for diff 240/300 rows",
  glue("
    {common_cte}
    SELECT diff_min,
           hour(old_acceptanceDateTime) AS old_hour,
           hour(new_acceptanceDateTime) AS new_hour,
           count(*) AS n
    FROM common
    WHERE diff_min IN (240, 300)
    GROUP BY diff_min, old_hour, new_hour
    ORDER BY diff_min, old_hour, new_hour
  ")
)

run_query(
  "Sample diff 240/300 rows",
  glue("
    {common_cte}
    SELECT diff_min,
           cik,
           accessionNumber,
           form,
           filingDate,
           old_acceptanceDateTime,
           new_acceptanceDateTime
    FROM common
    WHERE diff_min IN (240, 300)
    ORDER BY diff_min, new_acceptanceDateTime
    LIMIT 40
  ")
)
