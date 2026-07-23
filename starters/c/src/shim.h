/* Runtime for the civex Tier 2 (container) plugin wire protocol: newline-
 * delimited JSON over stdin/stdout, the same protocol Tier 1 (uv-run
 * subprocess) plugins speak -- see ../README.md for the frame shapes. A
 * plugin author fills in a ShimPlugin descriptor (see plugin.c) and calls
 * shim_serve() from main(); everything protocol-shaped (fd-dup stdout
 * isolation, describe/run dispatch, error framing) lives here so plugin.c
 * only has to contain plugin logic.
 */
#ifndef CIVEX_STARTER_SHIM_H
#define CIVEX_STARTER_SHIM_H

#include "json.h"

/* One declared input or output, matching civex_plugin_sdk.plugin_base.IOSpec
 * (see civex-plugin-sdk/src/civex_plugin_sdk/plugin_base.py). `type` is one
 * of civex_plugin_sdk's IO_TYPES vocabulary ("any", "string", "number",
 * "boolean", "bytes", "table", "files", "records", "mapping", "list") but
 * isn't validated here -- an unrecognized value degrades to being displayed
 * as-is host-side rather than failing discovery. */
typedef struct {
    const char *name;
    const char *type;        /* NULL defaults to "any" */
    int required;            /* nonzero = required (the common case) */
    const char *description; /* NULL defaults to "" */
} ShimIOSpec;

/* {kind, message, retryable} -- see civex_plugin_sdk.errors.PluginError.
 * `kind` left empty defaults to "plugin_error"; `retryable` defaults to 0
 * (false), matching the SDK's "guessing wrong means re-running a
 * permanently broken step" reasoning. */
typedef struct {
    char kind[64];
    char message[256];
    int retryable;
} ShimError;

typedef struct ShimCtx ShimCtx;

/* Blocking RPC call for a declared capability (see protocol RpcMethod:
 * "get_file", "update_record", "create_record", "commit", "call_tool").
 * Sends an rpc_call frame and blocks for the matching rpc_result -- the
 * protocol is strictly synchronous, no interleaving. Takes ownership of
 * `params`. On success returns the "result" object (caller owns, must
 * json_free()); on failure returns NULL and fills *out_error. */
JsonValue *shim_rpc_call(ShimCtx *ctx, const char *method, JsonValue *params, ShimError *out_error);

/* Sends an out-of-band `log` frame (informational only -- the host may
 * ignore it). `stream` should be "stdout" or "stderr". */
void shim_log(ShimCtx *ctx, const char *stream, const char *text);

typedef struct {
    const char *id;          /* required; unique, namespace-prefixed */
    const char *name;        /* required; human-readable */
    const char *description; /* NULL defaults to "" */
    const char *category;    /* NULL defaults to "general" */

    /* NULL-terminated array of capability names this plugin declares (every
     * ctx.* method / named tool it calls via shim_rpc_call), or NULL for
     * none. */
    const char **capabilities;

    /* NULL means "no contract declared in this direction" (protocol's
     * None, not []) -- see plugin_base.py's note on inputs/outputs. */
    const ShimIOSpec *inputs;
    size_t inputs_count;
    const ShimIOSpec *outputs;
    size_t outputs_count;

    /* Raw JSON Schema text describing `run`'s config object, e.g. "{}" for
     * no config. Must be valid JSON; NULL is treated as "{}". */
    const char *config_schema_json;

    /* Called for a `run` frame. `inputs`/`config` are borrowed (do not
     * free); `ctx` is valid only for the duration of this call. On success,
     * write the outputs object to *out_outputs (ownership transfers to the
     * shim, which frees it after sending) and return 0. On failure, fill
     * out_error and return nonzero. */
    int (*invoke)(const JsonValue *inputs, const JsonValue *config, ShimCtx *ctx,
                   JsonValue **out_outputs, ShimError *out_error);
} ShimPlugin;

/* Entry point: call as `return shim_serve(&my_plugin, argv);` from main().
 * `argv` must be the process argv (argv[1] selects "describe" or "run", per
 * `docker run -i <image> <mode>`). Returns a process exit code. */
int shim_serve(const ShimPlugin *plugin, char **argv, int argc);

#endif
