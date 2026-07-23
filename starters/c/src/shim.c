/* strdup/getline/dup2/getpid all need POSIX visibility under -std=c11. */
#define _POSIX_C_SOURCE 200809L

#include "shim.h"

#include <ctype.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

struct ShimCtx {
    FILE *in;
    FILE *out;
    unsigned long call_counter;
};

/* Duplicate the real stdout fd to a private fd, then redirect the public fd
 * 1 to /dev/null so any printf()/library output plugin logic emits can't
 * corrupt the protocol stream -- the same trick civex_plugin_sdk.io's
 * isolate_stdout() uses for Tier 1 plugins (dup -> save; devnull -> dup2
 * onto fd 1; close the temp fd). Must run before any plugin code. */
static FILE *isolate_stdout(void) {
    int real_fd = dup(1);
    if (real_fd < 0) {
        return NULL;
    }
    int devnull_fd = open("/dev/null", O_WRONLY);
    if (devnull_fd < 0) {
        close(real_fd);
        return NULL;
    }
    if (dup2(devnull_fd, 1) < 0) {
        close(devnull_fd);
        close(real_fd);
        return NULL;
    }
    close(devnull_fd);
    FILE *stream = fdopen(real_fd, "w");
    if (stream == NULL) {
        close(real_fd);
        return NULL;
    }
    setvbuf(stream, NULL, _IOLBF, 0);
    return stream;
}

/* Reads one non-blank line (a frame), stripping the trailing newline, or
 * returns NULL at EOF -- mirrors FrameReader.__next__'s blank-line skip. */
static char *read_frame_line(FILE *stream) {
    char *line = NULL;
    size_t cap = 0;
    while (1) {
        ssize_t n = getline(&line, &cap, stream);
        if (n < 0) {
            free(line);
            return NULL;
        }
        while (n > 0 && (line[n - 1] == '\n' || line[n - 1] == '\r')) {
            line[--n] = '\0';
        }
        int blank = 1;
        for (ssize_t i = 0; i < n; i++) {
            if (!isspace((unsigned char)line[i])) {
                blank = 0;
                break;
            }
        }
        if (!blank) {
            return line;
        }
    }
}

/* Serializes and writes one frame as a single line, then frees it. */
static void send_frame(FILE *out, JsonValue *frame) {
    StrBuf sb;
    sb_init(&sb);
    json_write(frame, &sb);
    sb_append(&sb, "\n", 1);
    fwrite(sb.data, 1, sb.len, out);
    fflush(out);
    sb_free(&sb);
    json_free(frame);
}

static JsonValue *build_error_frame(const char *call_id, const char *kind, const char *message,
                                     int retryable) {
    JsonValue *frame = json_new_object();
    json_object_set(frame, "type", json_new_string("error"));
    json_object_set(frame, "call_id", call_id != NULL ? json_new_string(call_id) : json_new_null());
    JsonValue *error = json_new_object();
    json_object_set(error, "kind", json_new_string(kind != NULL && kind[0] != '\0' ? kind : "plugin_error"));
    json_object_set(error, "message", json_new_string(message != NULL ? message : ""));
    json_object_set(error, "retryable", json_new_bool(retryable));
    json_object_set(frame, "error", error);
    return frame;
}

static void fill_error_from_json(ShimError *out_error, const JsonValue *error_obj) {
    const char *kind = json_get_string(json_object_get(error_obj, "kind"), "rpc_error");
    const char *message = json_get_string(json_object_get(error_obj, "message"), "");
    int retryable = json_get_bool(json_object_get(error_obj, "retryable"), 0);
    snprintf(out_error->kind, sizeof out_error->kind, "%s", kind);
    snprintf(out_error->message, sizeof out_error->message, "%s", message);
    out_error->retryable = retryable;
}

/* Removes `key` from a JSON_OBJECT and returns its value without freeing
 * it, so the caller can keep a subtree alive past json_free(object). */
static JsonValue *object_take(JsonValue *object, const char *key) {
    for (size_t i = 0; i < object->as.object.count; i++) {
        if (strcmp(object->as.object.keys[i], key) == 0) {
            JsonValue *v = object->as.object.values[i];
            free(object->as.object.keys[i]);
            for (size_t j = i; j + 1 < object->as.object.count; j++) {
                object->as.object.keys[j] = object->as.object.keys[j + 1];
                object->as.object.values[j] = object->as.object.values[j + 1];
            }
            object->as.object.count--;
            return v;
        }
    }
    return NULL;
}

JsonValue *shim_rpc_call(ShimCtx *ctx, const char *method, JsonValue *params, ShimError *out_error) {
    char call_id[64];
    snprintf(call_id, sizeof call_id, "c%d-%lu", (int)getpid(), ctx->call_counter++);

    JsonValue *frame = json_new_object();
    json_object_set(frame, "type", json_new_string("rpc_call"));
    json_object_set(frame, "call_id", json_new_string(call_id));
    json_object_set(frame, "method", json_new_string(method));
    json_object_set(frame, "params", params != NULL ? params : json_new_object());
    send_frame(ctx->out, frame);

    char *line = read_frame_line(ctx->in);
    if (line == NULL) {
        if (out_error != NULL) {
            snprintf(out_error->kind, sizeof out_error->kind, "rpc_error");
            snprintf(out_error->message, sizeof out_error->message,
                     "host closed the connection before responding to rpc_call '%s'", method);
            out_error->retryable = 0;
        }
        return NULL;
    }

    char *err = NULL;
    JsonValue *resp = json_parse(line, &err);
    free(line);
    if (resp == NULL) {
        if (out_error != NULL) {
            snprintf(out_error->kind, sizeof out_error->kind, "protocol_error");
            snprintf(out_error->message, sizeof out_error->message, "invalid JSON in rpc response: %s",
                     err != NULL ? err : "parse error");
            out_error->retryable = 0;
        }
        free(err);
        return NULL;
    }

    const char *type = json_get_string(json_object_get(resp, "type"), "");
    if (strcmp(type, "error") == 0) {
        if (out_error != NULL) {
            fill_error_from_json(out_error, json_object_get(resp, "error"));
        }
        json_free(resp);
        return NULL;
    }
    if (strcmp(type, "rpc_result") != 0) {
        if (out_error != NULL) {
            snprintf(out_error->kind, sizeof out_error->kind, "rpc_error");
            snprintf(out_error->message, sizeof out_error->message, "unexpected response to rpc_call '%s'",
                     method);
            out_error->retryable = 0;
        }
        json_free(resp);
        return NULL;
    }

    JsonValue *result = object_take(resp, "result");
    json_free(resp);
    return result != NULL ? result : json_new_object();
}

void shim_log(ShimCtx *ctx, const char *stream, const char *text) {
    JsonValue *frame = json_new_object();
    json_object_set(frame, "type", json_new_string("log"));
    json_object_set(frame, "stream", json_new_string(stream != NULL ? stream : "stdout"));
    json_object_set(frame, "text", json_new_string(text != NULL ? text : ""));
    send_frame(ctx->out, frame);
}

static void handle_describe(const ShimPlugin *plugin, FILE *out) {
    JsonValue *frame = json_new_object();
    json_object_set(frame, "type", json_new_string("describe_result"));
    json_object_set(frame, "id", json_new_string(plugin->id));
    json_object_set(frame, "name", json_new_string(plugin->name));
    json_object_set(frame, "description",
                     json_new_string(plugin->description != NULL ? plugin->description : ""));
    json_object_set(frame, "category",
                     json_new_string(plugin->category != NULL ? plugin->category : "general"));

    JsonValue *caps = json_new_array();
    if (plugin->capabilities != NULL) {
        for (const char **c = plugin->capabilities; *c != NULL; c++) {
            json_array_append(caps, json_new_string(*c));
        }
    }
    json_object_set(frame, "capabilities", caps);

    if (plugin->inputs != NULL) {
        JsonValue *arr = json_new_array();
        for (size_t i = 0; i < plugin->inputs_count; i++) {
            const ShimIOSpec *spec = &plugin->inputs[i];
            JsonValue *item = json_new_object();
            json_object_set(item, "name", json_new_string(spec->name));
            json_object_set(item, "type", json_new_string(spec->type != NULL ? spec->type : "any"));
            json_object_set(item, "required", json_new_bool(spec->required));
            json_object_set(item, "description",
                             json_new_string(spec->description != NULL ? spec->description : ""));
            json_array_append(arr, item);
        }
        json_object_set(frame, "inputs", arr);
    } else {
        json_object_set(frame, "inputs", json_new_null());
    }

    if (plugin->outputs != NULL) {
        JsonValue *arr = json_new_array();
        for (size_t i = 0; i < plugin->outputs_count; i++) {
            const ShimIOSpec *spec = &plugin->outputs[i];
            JsonValue *item = json_new_object();
            json_object_set(item, "name", json_new_string(spec->name));
            json_object_set(item, "type", json_new_string(spec->type != NULL ? spec->type : "any"));
            json_object_set(item, "required", json_new_bool(spec->required));
            json_object_set(item, "description",
                             json_new_string(spec->description != NULL ? spec->description : ""));
            json_array_append(arr, item);
        }
        json_object_set(frame, "outputs", arr);
    } else {
        json_object_set(frame, "outputs", json_new_null());
    }

    char *err = NULL;
    JsonValue *schema = json_parse(plugin->config_schema_json != NULL ? plugin->config_schema_json : "{}",
                                    &err);
    if (schema == NULL) {
        free(err);
        schema = json_new_object();
    }
    json_object_set(frame, "config_schema", schema);

    send_frame(out, frame);
}

static void handle_run(const ShimPlugin *plugin, const JsonValue *frame, ShimCtx *ctx, FILE *out) {
    const JsonValue *inputs = json_object_get(frame, "inputs");
    const JsonValue *config = json_object_get(frame, "config");
    JsonValue *inputs_owned = NULL;
    JsonValue *config_owned = NULL;
    if (inputs == NULL) {
        inputs_owned = json_new_object();
        inputs = inputs_owned;
    }
    if (config == NULL) {
        config_owned = json_new_object();
        config = config_owned;
    }

    JsonValue *outputs = NULL;
    ShimError error;
    memset(&error, 0, sizeof error);
    int rc = plugin->invoke(inputs, config, ctx, &outputs, &error);
    if (rc == 0) {
        JsonValue *result = json_new_object();
        json_object_set(result, "type", json_new_string("result"));
        json_object_set(result, "outputs", outputs != NULL ? outputs : json_new_object());
        send_frame(out, result);
    } else {
        json_free(outputs);
        send_frame(out, build_error_frame(NULL, error.kind, error.message, error.retryable));
    }

    json_free(inputs_owned);
    json_free(config_owned);
}

int shim_serve(const ShimPlugin *plugin, char **argv, int argc) {
    if (argc != 2 || (strcmp(argv[1], "describe") != 0 && strcmp(argv[1], "run") != 0)) {
        fprintf(stderr, "usage: %s <describe|run>\n", argc > 0 ? argv[0] : "plugin");
        return 2;
    }
    const char *mode = argv[1];

    FILE *out = isolate_stdout();
    if (out == NULL) {
        fprintf(stderr, "failed to isolate stdout\n");
        return 1;
    }

    ShimCtx ctx = {stdin, out, 0};

    char *line = read_frame_line(stdin);
    if (line == NULL) {
        send_frame(out, build_error_frame(NULL, "protocol_error", "no frame received on stdin", 0));
        fclose(out);
        return 1;
    }

    char *err = NULL;
    JsonValue *frame = json_parse(line, &err);
    free(line);
    if (frame == NULL) {
        char msg[320];
        snprintf(msg, sizeof msg, "invalid JSON frame: %s", err != NULL ? err : "parse error");
        free(err);
        send_frame(out, build_error_frame(NULL, "protocol_error", msg, 0));
        fclose(out);
        return 1;
    }

    const char *type = json_get_string(json_object_get(frame, "type"), "");
    if (strcmp(mode, "describe") == 0) {
        if (strcmp(type, "describe") != 0) {
            char msg[256];
            snprintf(msg, sizeof msg, "expected a 'describe' frame in describe mode, got '%s'", type);
            send_frame(out, build_error_frame(NULL, "protocol_error", msg, 0));
        } else {
            handle_describe(plugin, out);
        }
    } else {
        if (strcmp(type, "run") != 0) {
            char msg[256];
            snprintf(msg, sizeof msg, "expected a 'run' frame in run mode, got '%s'", type);
            send_frame(out, build_error_frame(NULL, "protocol_error", msg, 0));
        } else {
            handle_run(plugin, frame, &ctx, out);
        }
    }

    json_free(frame);
    fclose(out);
    return 0;
}
