# Offline checks of the reference client's search rules (design.md, "Clients").
#
#   uv run python scripts/fixture_catalog.py /tmp/bls-fixture
#   Rscript examples/check_find_bls.R /tmp/bls-fixture
#
# Uses a temporary cache, so it never touches the real one. Exits nonzero on failure.
# These become testthat tests when the client moves to epidatatools.

fixture = normalizePath(commandArgs(TRUE)[1])
manifest_path = file.path(fixture, "latest.json")
options(
  bls_index.manifest_url = paste0("file://", manifest_path),
  bls_index.cache_dir = file.path(tempdir(), "bls_index_cache")
)
source("examples/find_bls.R")

failures = 0
check = function(name, ok) {
  if (isTRUE(ok)) {
    cat("ok   ", name, "\n")
  } else {
    failures <<- failures + 1
    cat("FAIL ", name, "\n")
  }
}
quiet = function(expr) suppressMessages(expr)
messages_of = function(expr) {
  out = character()
  withCallingHandlers(expr, message = function(m) {
    out <<- c(out, conditionMessage(m))
    invokeRestart("muffleMessage")
  })
  out
}
error_of = function(expr) tryCatch({ expr; "" }, error = conditionMessage)

# -- results ------------------------------------------------------------------------

r = quiet(find_bls("consumer"))
check("returns exactly the documented columns", identical(names(r), bls_index_columns))
check("stemming: 'consumer' finds titles with 'consumers'", any(grepl("\\bconsumers\\b", r$series_title)))
check("stemming: 'hourly' finds 'hour' and 'hours'",
      any(grepl("\\bhours\\b", quiet(find_bls("hourly"))$series_title)))
check("every word is required",
      all(grepl("unemployment", quiet(find_bls("unemployment rate"))$series_title, ignore.case = TRUE)))
check("a stem that is not the start of its word still matches: 'city' finds 'city'",
      "CUSR0000SA0" %in% quiet(find_bls("CPI all items U.S. city average"))$series_id)

ces = quiet(find_bls("CES"))
check("short words match whole words only: 'CES' finds ce, not 'services'",
      nrow(ces) > 0 && all(ces$program == "ce"))
check("aliases: 'JOLTS' finds jt", nrow(quiet(find_bls("JOLTS"))) == 4)
check("survey names: 'consumer price index' finds cu",
      "cu" %in% quiet(find_bls("consumer price index"))$program)

hours <- quiet(find_bls("hours"))
in_title <- grepl("\\bhour", hours$series_title, ignore.case = TRUE)
check(
  "survey-name matches let rows in: 'hours' finds ce and sm rows through their names",
  all(c("ce", "sm") %in% hours$program)
)
check(
  "title matches rank above survey-name matches, then by length, title, ID",
  identical(
    order(
      -in_title,
      nchar(hours$series_title),
      tolower(hours$series_title),
      hours$series_id,
      method = "radix"
    ),
    seq_len(nrow(hours))
  )
)
check(
  "alias matches count toward rank: 'CPI price' puts cu rows first",
  quiet(find_bls("CPI price"))$program[1] == "cu"
)
titles <- quiet(find_bls("hours", titles_only = TRUE))
check(
  "titles_only ignores survey names",
  nrow(titles) == sum(in_title) && all(grepl("\\bhour", titles$series_title, ignore.case = TRUE))
)
none <- quiet(find_bls("JOLTS", titles_only = TRUE))
check(
  "titles_only ignores aliases, and an empty result keeps the columns",
  nrow(none) == 0 && identical(names(none), bls_index_columns)
)

# -- filters ------------------------------------------------------------------------

two = quiet(find_bls("rate", survey = c("LA", "fm")))
check("several survey codes, ignoring case", nrow(two) > 0 && all(two$program %in% c("la", "fm")))
check("unknown survey code is an error listing valid codes",
      grepl("Unknown `survey`.*cps.*Valid values: ap", error_of(find_bls("rate", survey = "cps"))))
sa = quiet(find_bls("consumer", seasonality = "sa"))
check("seasonality filter, ignoring case", nrow(sa) > 0 && all(sa$seasonal == "SA"))
check("several seasonality values",
      setequal(unique(quiet(find_bls("consumer", seasonality = c("SA", "NSA")))$seasonal), c("SA", "NSA")))
check("unknown seasonality is an error", grepl("Unknown `seasonality`", error_of(find_bls("rate", seasonality = "X"))))
check("an empty search is an error", grepl("at least one word", error_of(find_bls(" ... "))))

# -- limit --------------------------------------------------------------------------

all_rows = quiet(find_bls("wage", limit = Inf))
msgs = messages_of(few <- find_bls("wage", limit = 3))
check("limit returns that many rows", nrow(few) == 3)
check("the limited rows are the first rows of the full sort",
      identical(few$series_id, head(all_rows$series_id, 3)))
check("a cut result reports the total and counts by survey",
      length(msgs) == 1 && grepl(paste0(nrow(all_rows), " matches; showing the first 3"), msgs) &&
        grepl("By survey: ", msgs))
check("no message when nothing is cut", length(messages_of(find_bls("wage", limit = Inf))) == 0)

# -- cache --------------------------------------------------------------------------

cache = getOption("bls_index.cache_dir")
state = jsonlite::read_json(file.path(cache, "bls_index_state.json"))
check("the catalog is cached under its checksum",
      file.exists(file.path(cache, paste0("bls_index-", state$sha256, ".parquet"))))

options(bls_index.manifest_url = "file:///nonexistent/latest.json")
check("within 7 days the manifest is not read", length(messages_of(find_bls("wage"))) == 0)
check("if the manifest cannot be read, the cached catalog is used",
      any(grepl("using the cached one", messages_of(find_bls("wage", refresh = TRUE)))))

state$built_at = "2000-01-01T00:00:00Z"
jsonlite::write_json(state, file.path(cache, "bls_index_state.json"), auto_unbox = TRUE)
check("an old catalog is reported as possibly out of date",
      any(grepl("may be out of date", messages_of(find_bls("wage")))))

bad = jsonlite::read_json(manifest_path)
bad$catalog$sha256 = strrep("0", 64)
bad_path = file.path(tempdir(), "bad_latest.json")
jsonlite::write_json(bad, bad_path, auto_unbox = TRUE)
options(bls_index.manifest_url = paste0("file://", bad_path))
check("a newer catalog that fails its checksum is not used; the cached one is",
      any(grepl("failed its checksum.*using the cached one", messages_of(find_bls("wage", refresh = TRUE)))))

gone = jsonlite::read_json(manifest_path)
gone$catalog$sha256 = strrep("1", 64)
gone$catalog$url = "file:///nonexistent/bls_index.parquet"
gone_path = file.path(tempdir(), "gone_latest.json")
jsonlite::write_json(gone, gone_path, auto_unbox = TRUE)
options(bls_index.manifest_url = paste0("file://", gone_path))
old_check = jsonlite::read_json(file.path(cache, "bls_index_state.json"))
old_check$checked_at = "2000-01-01T00:00:00Z"
jsonlite::write_json(old_check, file.path(cache, "bls_index_state.json"), auto_unbox = TRUE)
check("if a newer catalog cannot be downloaded, the cached one is used",
      any(grepl("could not download.*using the cached one", messages_of(find_bls("wage")))))
check("a failed check counts as a check: the next search does not retry",
      !any(grepl("could not download", messages_of(find_bls("wage")))))

unlink(cache, recursive = TRUE)
options(bls_index.manifest_url = paste0("file://", bad_path))
check("with no cache, a catalog that fails its checksum is an error",
      grepl("failed its checksum", error_of(find_bls("wage"))))
options(bls_index.manifest_url = "file:///nonexistent/latest.json")
check("with no cache and no manifest, an error", grepl("Could not read", error_of(find_bls("wage"))))

cat(if (failures) paste(failures, "check(s) failed\n") else "all checks passed\n")
quit(status = if (failures) 1 else 0)
