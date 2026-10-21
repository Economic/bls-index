# Reference client for the bls_index catalog. It follows the "Clients" section of
# design.md and is meant to be ported into epidatatools, not used as a package.
#
#   source("examples/find_bls.R")
#   find_bls("unemployment rate", survey = c("ln", "la"), seasonality = "SA")
#
# Requires arrow, dplyr, jsonlite, openssl, rlang, SnowballC and tibble.
#
# Settings, for testing or mirrors:
#   BLS_INDEX_MANIFEST_URL or options(bls_index.manifest_url = ...): the manifest to read
#   options(bls_index.cache_dir = ...): where the catalog is cached

bls_index_default_manifest <-
  "https://github.com/Economic/bls-index/releases/latest/download/latest.json"
bls_index_columns <- c(
  "series_id",
  "series_title",
  "program",
  "survey_name",
  "seasonal",
  "begin_year",
  "end_year",
  "end_period"
)

find_bls <- function(
  search_string,
  survey = NULL,
  seasonality = NULL,
  limit = 1000,
  titles_only = FALSE,
  refresh = FALSE
) {
  words <- search_words(search_string)
  stopifnot(is.numeric(limit), length(limit) == 1, limit >= 1)
  stopifnot(is.logical(titles_only), length(titles_only) == 1, !is.na(titles_only))
  ds <- arrow::open_dataset(bls_catalog(refresh))

  # Survey names and aliases are fixed per program, so match them against the small
  # program table here and scan only the titles in the catalog. A word matched by the
  # survey name lets a row in; a word matched by the title or an alias also counts
  # toward the row's rank (`.hits`).
  programs <- program_table(ds)
  aliases <- dplyr::coalesce(programs$survey_aliases, "")
  query <- ds
  hits <- list()
  for (word in words) {
    p <- word_pattern(word)
    in_title <- rlang::expr(grepl(!!p, series_title, ignore.case = TRUE))
    if (titles_only) {
      query <- query |> dplyr::filter(!!in_title)
      hits <- c(hits, list(in_title))
      next
    }
    by_alias <- programs$program[grepl(p, aliases, ignore.case = TRUE, perl = TRUE)]
    by_name <- programs$program[
      grepl(p, programs$survey_name, ignore.case = TRUE, perl = TRUE)
    ]
    query <- query |>
      dplyr::filter(!!in_title | program %in% !!union(by_alias, by_name))
    hits <- c(hits, list(rlang::expr(!!in_title | program %in% !!by_alias)))
  }
  if (!is.null(survey)) {
    codes <- check_values(survey, sort(programs$program), "survey")
    query <- query |> dplyr::filter(program %in% !!codes)
  }
  if (!is.null(seasonality)) {
    values <- check_values(
      seasonality,
      c("SA", "NSA", "unknown"),
      "seasonality"
    )
    query <- query |> dplyr::filter(seasonal %in% !!values)
  }
  hit_count <- Reduce(
    function(a, b) rlang::expr(!!a + !!b),
    lapply(hits, function(h) rlang::expr(as.integer(!!h)))
  )

  # Scan the catalog once, keeping the matches in arrow memory (not R). Counts by
  # program, rank and title length show where the first `limit` rows end, so only those
  # rows (plus ties) are brought into R. survey_name is added back from the program table.
  matches <- query |>
    dplyr::mutate(.hits = !!hit_count) |>
    dplyr::select(dplyr::all_of(c(setdiff(bls_index_columns, "survey_name"), ".hits"))) |>
    dplyr::compute()
  tally <- matches |>
    dplyr::mutate(length = nchar(series_title)) |>
    dplyr::count(program, .hits, length) |>
    dplyr::collect()
  total <- sum(tally$n)
  if (is.finite(limit) && total > limit) {
    ranks <- tally |>
      dplyr::count(.hits, length, wt = n) |>
      dplyr::arrange(dplyr::desc(.hits), length)
    last <- ranks[which(cumsum(ranks$n) >= limit)[1], ]
    matches <- matches |>
      dplyr::filter(
        .hits > !!last$.hits |
          (.hits == !!last$.hits & nchar(series_title) <= !!last$length)
      )
  }
  result <- matches |>
    dplyr::collect() |>
    dplyr::left_join(
      dplyr::select(programs, program, survey_name),
      by = "program"
    )

  # Most matched words first, then title length, then lowercased title, then series ID.
  # "radix" compares strings by bytes, so the order is the same on every machine.
  result <- result[
    order(
      -result$.hits,
      nchar(result$series_title),
      tolower(result$series_title),
      result$series_id,
      method = "radix"
    ),
    bls_index_columns
  ]
  if (is.finite(limit)) {
    result <- utils::head(result, limit)
  }
  result <- tibble::as_tibble(result)

  if (total > nrow(result)) {
    counts <- tally |>
      dplyr::count(program, wt = n) |>
      dplyr::arrange(dplyr::desc(n), program)
    message(
      format_count(total),
      " matches; showing the first ",
      format_count(nrow(result)),
      ". Narrow the search, or use `limit = Inf`.\nBy survey: ",
      paste(counts$program, format_count(counts$n), collapse = ", "),
      "."
    )
  }
  result
}

# -- search terms -------------------------------------------------------------------

search_words <- function(search_string) {
  stopifnot(
    is.character(search_string),
    length(search_string) == 1,
    !is.na(search_string)
  )
  words <- strsplit(tolower(search_string), "\\s+")[[1]]
  words <- gsub("^[[:punct:]]+|[[:punct:]]+$", "", words)
  words <- words[words != ""]
  if (length(words) == 0) {
    stop("`search_string` must contain at least one word.", call. = FALSE)
  }
  words
}

# A word matches the start of any word beginning with the part it shares with its stem
# ("nurses" -> "nurs"). A stem is not always the start of its word ("city" -> "citi"),
# hence the shared part. If that part is
# under 4 characters, the word must match as a whole word, so short words such as
# "ces", "oes" or "city" stay exact.
word_pattern <- function(word) {
  stem <- SnowballC::wordStem(word, language = "english")
  shared <- shared_prefix(word, stem)
  if (nchar(shared) >= 4) {
    paste0("\\b", escape_regex(shared))
  } else {
    paste0("\\b", escape_regex(word), "\\b")
  }
}

shared_prefix <- function(a, b) {
  a <- strsplit(a, "")[[1]]
  b <- strsplit(b, "")[[1]]
  n <- min(length(a), length(b))
  same <- a[seq_len(n)] == b[seq_len(n)]
  k <- if (all(same)) n else which(!same)[1] - 1
  paste(a[seq_len(k)], collapse = "")
}

escape_regex <- function(x) gsub("([][{}()+*^$|\\\\?.])", "\\\\\\1", x)

check_values <- function(x, valid, arg) {
  stopifnot(is.character(x), length(x) >= 1)
  matched <- valid[match(tolower(x), tolower(valid))]
  if (anyNA(matched)) {
    stop(
      "Unknown `",
      arg,
      "` value(s): ",
      paste(x[is.na(matched)], collapse = ", "),
      ". Valid values: ",
      paste(valid, collapse = ", "),
      ".",
      call. = FALSE
    )
  }
  unique(matched)
}

# The program table (code, survey name, aliases) is read once per catalog per session.
bls_index_programs <- new.env()
program_table <- function(ds) {
  key <- paste(ds$files, collapse = "|")
  if (is.null(bls_index_programs[[key]])) {
    bls_index_programs[[key]] <- ds |>
      dplyr::distinct(program, survey_name, survey_aliases) |>
      dplyr::collect()
  }
  bls_index_programs[[key]]
}

format_count <- function(n) {
  format(n, big.mark = ",", scientific = FALSE, trim = TRUE)
}

# -- cached catalog -----------------------------------------------------------------

# Return the path of a verified local catalog, checking for a new one at most every 7 days.
bls_catalog <- function(refresh = FALSE) {
  dir <- getOption(
    "bls_index.cache_dir",
    tools::R_user_dir("epidatatools", "cache")
  )
  dir.create(dir, recursive = TRUE, showWarnings = FALSE)
  state_file <- file.path(dir, "bls_index_state.json")
  state <- if (file.exists(state_file)) {
    jsonlite::read_json(state_file)
  } else {
    NULL
  }
  cached <- if (is.null(state)) NA_character_ else file.path(dir, state$file)
  have <- !is.na(cached) && file.exists(cached)

  if (have && !refresh && days_since(state$checked_at) < 7) {
    return(warn_if_stale(cached, state))
  }
  manifest <- tryCatch(read_manifest(), error = function(e) e)
  if (inherits(manifest, "error")) {
    if (!have) {
      stop(
        "Could not read the BLS catalog manifest: ",
        conditionMessage(manifest),
        ". If no catalog has been published yet, point ",
        "`options(bls_index.manifest_url = ...)` at a local manifest.",
        call. = FALSE
      )
    }
    message(
      "Could not check for a newer BLS catalog (",
      conditionMessage(manifest),
      "); using the cached one built ",
      state$built_at,
      "."
    )
    return(warn_if_stale(cached, state))
  }

  catalog <- manifest$catalog
  if (!have || !identical(state$sha256, catalog$sha256)) {
    file <- paste0("bls_index-", catalog$sha256, ".parquet")
    partial <- file.path(dir, paste0(file, ".part"))
    on.exit(unlink(partial), add = TRUE)
    download(catalog$url, partial)
    actual <- sha256_file(partial)
    if (!identical(actual, catalog$sha256)) {
      stop(
        "Downloaded catalog failed its checksum (expected ",
        catalog$sha256,
        ", got ",
        actual,
        ").",
        call. = FALSE
      )
    }
    file.rename(partial, file.path(dir, file))
    if (have && basename(cached) != file) {
      unlink(cached)
    }
    cached <- file.path(dir, file)
  }
  state <- list(
    file = basename(cached),
    sha256 = catalog$sha256,
    tag = manifest$tag,
    built_at = manifest$built_at,
    checked_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
  )
  jsonlite::write_json(state, state_file, auto_unbox = TRUE, pretty = TRUE)
  warn_if_stale(cached, state)
}

read_manifest <- function() {
  url <- Sys.getenv(
    "BLS_INDEX_MANIFEST_URL",
    getOption("bls_index.manifest_url", bls_index_default_manifest)
  )
  path <- tempfile(fileext = ".json")
  on.exit(unlink(path))
  download(url, path)
  jsonlite::read_json(path)
}

download <- function(url, dest) {
  # A 33 MB catalog can take more than R's default 60 s on a slow connection.
  old <- options(timeout = max(900, getOption("timeout")))
  on.exit(options(old))
  # download.file reports a failure as warnings plus an error; keep one short error.
  status <- tryCatch(
    suppressWarnings(utils::download.file(
      url,
      dest,
      mode = "wb",
      quiet = TRUE,
      headers = c(
        "User-Agent" = "epidatatools find_bls (bls_index reference client)"
      )
    )),
    error = function(e) e
  )
  if (inherits(status, "error") || !identical(status, 0L)) {
    stop("could not download ", url, call. = FALSE)
  }
}

sha256_file <- function(path) {
  con <- file(path, "rb")
  on.exit(close(con))
  as.vector(as.character(openssl::sha256(con))) # as.vector drops the "hash" class
}

days_since <- function(timestamp) {
  as.numeric(difftime(
    Sys.time(),
    as.POSIXct(timestamp, format = "%Y-%m-%dT%H:%M:%OS", tz = "UTC"),
    units = "days"
  ))
}

warn_if_stale <- function(path, state) {
  age <- days_since(state$built_at)
  if (!is.na(age) && age > 10) {
    message(
      "The BLS catalog was built ",
      floor(age),
      " days ago and may be out of date. ",
      "Use `refresh = TRUE` to check for a newer one."
    )
  }
  path
}
