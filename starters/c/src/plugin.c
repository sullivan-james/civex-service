/* Example Tier 2 (container) plugin built on the starter shim -- sums two
 * numeric inputs. Copy this whole directory to scaffold a new C/C++ plugin:
 * edit the ShimPlugin descriptor below (id/name/category/capabilities/
 * inputs/outputs) and `invoke()`'s body; shim.c/json.c handle the wire
 * protocol and don't need to change for most plugins.
 *
 * `invoke()` deliberately printf()s a line of "noisy" output before
 * returning, to demonstrate that the fd-dup stdout isolation in shim.c
 * (isolate_stdout(), called before any plugin code runs) keeps it from
 * corrupting the protocol stream on fd 1 -- run this binary and pipe its
 * stdout to a file to confirm only the JSON result line shows up there.
 */
#include <stdio.h>

#include "json.h"
#include "shim.h"

static const char *CAPABILITIES[] = {NULL}; /* this plugin makes no ctx/RPC calls */

static const ShimIOSpec INPUTS[] = {
    {"a", "number", 1, "First addend."},
    {"b", "number", 1, "Second addend."},
};

static const ShimIOSpec OUTPUTS[] = {
    {"sum", "number", 1, "a + b."},
};

static int invoke(const JsonValue *inputs, const JsonValue *config, ShimCtx *ctx,
                   JsonValue **out_outputs, ShimError *out_error) {
    (void)config;
    (void)ctx;

    const JsonValue *a_val = json_object_get(inputs, "a");
    const JsonValue *b_val = json_object_get(inputs, "b");
    if (a_val == NULL || b_val == NULL) {
        snprintf(out_error->kind, sizeof out_error->kind, "validation_error");
        snprintf(out_error->message, sizeof out_error->message,
                 "both 'a' and 'b' inputs are required");
        out_error->retryable = 0;
        return 1;
    }
    double a = json_get_number(a_val, 0.0);
    double b = json_get_number(b_val, 0.0);

    /* Regular library/debug output -- goes to /dev/null once isolate_stdout()
     * has run, never onto the wire. */
    printf("computing %g + %g\n", a, b);
    fflush(stdout);

    JsonValue *outputs = json_new_object();
    json_object_set(outputs, "sum", json_new_number(a + b));
    *out_outputs = outputs;
    return 0;
}

static const ShimPlugin PLUGIN = {
    .id = "my_project.c_example_sum",
    .name = "C Example: Sum Numbers",
    .description = "Starter C plugin that adds two numeric inputs.",
    .category = "starters",
    .capabilities = CAPABILITIES,
    .inputs = INPUTS,
    .inputs_count = sizeof(INPUTS) / sizeof(INPUTS[0]),
    .outputs = OUTPUTS,
    .outputs_count = sizeof(OUTPUTS) / sizeof(OUTPUTS[0]),
    .config_schema_json = "{}",
    .invoke = invoke,
};

int main(int argc, char **argv) { return shim_serve(&PLUGIN, argv, argc); }
