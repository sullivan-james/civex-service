#!/usr/bin/env Rscript
# Starter shim for R-language container-tier plugins, speaking the same
# newline-delimited JSON wire protocol as the Tier 1 subprocess SDK (see
# civex-plugin-sdk/src/civex_plugin_sdk/{protocol,io,serve}.py for the
# canonical Python implementation this mirrors) -- so the host side needs no
# R-specific code to drive it.
#
# Invoked as `Rscript plugin.R <mode>`, where <mode> is "describe" or "run",
# matching the CLI arg entrypoint.sh forwards from `docker run -i <image>
# <mode>`. Reads exactly one frame from real stdin (fd 0, untouched by the
# fd-dup entrypoint.sh already did) and writes response frame(s) to fd 3 --
# by the time this script starts, fd 1 (stdout) has already been redirected
# to /dev/null, so nothing R or a loaded package prints via
# cat()/print()/message() can corrupt the protocol stream.
suppressPackageStartupMessages(library(jsonlite))

# --- plugin identity: keep these in sync with civex-plugin.toml -------------
PLUGIN_ID <- "example.r_echo"
PLUGIN_NAME <- "R Echo"
PLUGIN_DESCRIPTION <- "Starter template for an R-language container-tier plugin."
PLUGIN_CATEGORY <- "example"
PLUGIN_CAPABILITIES <- list("commit")
CONFIG_SCHEMA <- list(
  type = "object",
  properties = list(text = list(type = "string")),
  required = list("text")
)

protocol_out <- file("/dev/fd/3", open = "w")

send_frame <- function(frame) {
  writeLines(toJSON(frame, auto_unbox = TRUE, null = "null"), protocol_out)
  flush(protocol_out)
}

send_error <- function(message, kind = "plugin_error", retryable = FALSE, call_id = NULL) {
  send_frame(list(
    type = "error",
    call_id = call_id,
    error = list(kind = kind, message = message, retryable = retryable)
  ))
}

read_frame <- function() {
  line <- readLines(con = stdin(), n = 1)
  if (length(line) == 0) stop("no frame received on stdin")
  fromJSON(line, simplifyVector = FALSE)
}

new_call_id <- function() {
  paste0(sprintf("%08x", sample.int(2147483647, 4)), collapse = "")
}

# Synchronous rpc_call round-trip: send one rpc_call frame, then block for
# the matching rpc_result/error -- the host never interleaves anything else
# while a call is outstanding (mirrors civex_plugin_sdk.ctx.Ctx._call).
rpc_call <- function(method, params) {
  call_id <- new_call_id()
  send_frame(list(type = "rpc_call", call_id = call_id, method = method, params = params))
  response <- read_frame()
  if (identical(response$type, "error")) {
    stop(paste0("rpc_call '", method, "' failed: ", response$error$message))
  }
  if (!identical(response$type, "rpc_result") || !identical(response$call_id, call_id)) {
    stop(paste0("unexpected response to rpc_call '", method, "'"))
  }
  response$result
}

handle_describe <- function() {
  send_frame(list(
    type = "describe_result",
    id = PLUGIN_ID,
    name = PLUGIN_NAME,
    description = PLUGIN_DESCRIPTION,
    category = PLUGIN_CATEGORY,
    capabilities = PLUGIN_CAPABILITIES,
    config_schema = CONFIG_SCHEMA
  ))
}

# Replace this with your plugin's own logic -- everything else in this file
# (frame I/O, rpc_call, error envelopes) is boilerplate every R container
# plugin needs verbatim.
invoke <- function(inputs, config) {
  if (isTRUE(inputs$call_commit)) {
    rpc_call("commit", list())
  }
  list(echo = config$text, inputs = inputs)
}

handle_run <- function(frame) {
  config <- frame$config
  if (is.null(config)) config <- list()
  inputs <- frame$inputs
  if (is.null(inputs)) inputs <- list()

  if (is.null(config$text) || !is.character(config$text)) {
    send_error("config.text is required and must be a string", kind = "config_validation_error")
    return(invisible())
  }

  outputs <- tryCatch(
    invoke(inputs, config),
    error = function(e) {
      send_error(conditionMessage(e))
      NULL
    }
  )
  if (!is.null(outputs)) {
    send_frame(list(type = "result", outputs = outputs))
  }
}

main <- function() {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) != 1 || !(args[1] %in% c("describe", "run"))) {
    stop("usage: plugin.R <describe|run>", call. = FALSE)
  }
  mode <- args[1]

  frame <- read_frame()
  if (!identical(frame$type, mode)) {
    send_error(
      paste0("expected '", mode, "' frame, got '", frame$type, "'"),
      kind = "protocol_error"
    )
    return(invisible())
  }

  if (mode == "describe") {
    handle_describe()
  } else {
    handle_run(frame)
  }
}

main()
