
f <- function(a, b, d = 0, ...) {
  sum(a, b, d)
}

f(a = 1, b = 2, c = 3)

f <- function(a, b, d = 0) {
  sum(a, b, d)
}

f(a = 1, b = 2, c = 3)

dots_call <- function(fun, list_args = list(), ...) {
  dots <- list(...)
  all_args <- c(list_args, dots)
  keep <- intersect(names(all_args), names(formals(fun)))
  do.call(fun, all_args[keep])
}

f <- function(a, b, d = 0, ...) {
  sum(a, b, d)
}

dots_call(fun = f, a = 5, b = 4, c = 1)

new_f <- function(...) {
  dots_call(new_f, ...)
}

format_tt <- function(x, y = NA) {
  print(x)
}

dots_call(fun = format_tt,
          list_args = list(x = "res",
                           replace = list("NA" = c(NA, NaN)),
                           num_fmt = "decimal",
                           num_zero = TRUE,
                           escape = TRUE))
