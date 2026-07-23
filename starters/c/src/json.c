/* strdup needs POSIX visibility under -std=c11. */
#define _POSIX_C_SOURCE 200809L

#include "json.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---------------------------------------------------------------- StrBuf */

void sb_init(StrBuf *sb) {
    sb->data = NULL;
    sb->len = 0;
    sb->cap = 0;
}

void sb_free(StrBuf *sb) {
    free(sb->data);
    sb->data = NULL;
    sb->len = 0;
    sb->cap = 0;
}

static void sb_reserve(StrBuf *sb, size_t extra) {
    if (sb->len + extra + 1 <= sb->cap) {
        return;
    }
    size_t new_cap = sb->cap == 0 ? 256 : sb->cap;
    while (new_cap < sb->len + extra + 1) {
        new_cap *= 2;
    }
    sb->data = realloc(sb->data, new_cap);
    sb->cap = new_cap;
}

void sb_append(StrBuf *sb, const char *s, size_t n) {
    sb_reserve(sb, n);
    memcpy(sb->data + sb->len, s, n);
    sb->len += n;
    sb->data[sb->len] = '\0';
}

void sb_append_str(StrBuf *sb, const char *s) { sb_append(sb, s, strlen(s)); }

/* ------------------------------------------------------------- value ctors */

static JsonValue *new_value(JsonType type) {
    JsonValue *v = calloc(1, sizeof(JsonValue));
    v->type = type;
    return v;
}

JsonValue *json_new_null(void) { return new_value(JSON_NULL); }

JsonValue *json_new_bool(int value) {
    JsonValue *v = new_value(JSON_BOOL);
    v->as.boolean = value ? 1 : 0;
    return v;
}

JsonValue *json_new_number(double value) {
    JsonValue *v = new_value(JSON_NUMBER);
    v->as.number = value;
    return v;
}

JsonValue *json_new_string(const char *value) {
    JsonValue *v = new_value(JSON_STRING);
    v->as.string = strdup(value ? value : "");
    return v;
}

JsonValue *json_new_array(void) {
    JsonValue *v = new_value(JSON_ARRAY);
    v->as.array.items = NULL;
    v->as.array.count = 0;
    return v;
}

JsonValue *json_new_object(void) {
    JsonValue *v = new_value(JSON_OBJECT);
    v->as.object.keys = NULL;
    v->as.object.values = NULL;
    v->as.object.count = 0;
    return v;
}

void json_array_append(JsonValue *array, JsonValue *item) {
    size_t n = array->as.array.count;
    array->as.array.items = realloc(array->as.array.items, (n + 1) * sizeof(JsonValue *));
    array->as.array.items[n] = item;
    array->as.array.count = n + 1;
}

void json_object_set(JsonValue *object, const char *key, JsonValue *value) {
    /* Starter-scale objects (protocol frames, small configs) -- a linear
     * scan to replace an existing key is fine; not worth a hash map here. */
    for (size_t i = 0; i < object->as.object.count; i++) {
        if (strcmp(object->as.object.keys[i], key) == 0) {
            json_free(object->as.object.values[i]);
            object->as.object.values[i] = value;
            return;
        }
    }
    size_t n = object->as.object.count;
    object->as.object.keys = realloc(object->as.object.keys, (n + 1) * sizeof(char *));
    object->as.object.values = realloc(object->as.object.values, (n + 1) * sizeof(JsonValue *));
    object->as.object.keys[n] = strdup(key);
    object->as.object.values[n] = value;
    object->as.object.count = n + 1;
}

void json_free(JsonValue *value) {
    if (value == NULL) {
        return;
    }
    switch (value->type) {
        case JSON_STRING:
            free(value->as.string);
            break;
        case JSON_ARRAY:
            for (size_t i = 0; i < value->as.array.count; i++) {
                json_free(value->as.array.items[i]);
            }
            free(value->as.array.items);
            break;
        case JSON_OBJECT:
            for (size_t i = 0; i < value->as.object.count; i++) {
                free(value->as.object.keys[i]);
                json_free(value->as.object.values[i]);
            }
            free(value->as.object.keys);
            free(value->as.object.values);
            break;
        default:
            break;
    }
    free(value);
}

/* ---------------------------------------------------------------- accessors */

const JsonValue *json_object_get(const JsonValue *object, const char *key) {
    if (object == NULL || object->type != JSON_OBJECT) {
        return NULL;
    }
    for (size_t i = 0; i < object->as.object.count; i++) {
        if (strcmp(object->as.object.keys[i], key) == 0) {
            return object->as.object.values[i];
        }
    }
    return NULL;
}

const char *json_get_string(const JsonValue *value, const char *fallback) {
    if (value == NULL || value->type != JSON_STRING) {
        return fallback;
    }
    return value->as.string;
}

double json_get_number(const JsonValue *value, double fallback) {
    if (value == NULL || value->type != JSON_NUMBER) {
        return fallback;
    }
    return value->as.number;
}

int json_get_bool(const JsonValue *value, int fallback) {
    if (value == NULL || value->type != JSON_BOOL) {
        return fallback;
    }
    return value->as.boolean;
}

int json_is_null(const JsonValue *value) { return value == NULL || value->type == JSON_NULL; }

/* -------------------------------------------------------------------- write */

static void write_escaped_string(const char *s, StrBuf *sb) {
    sb_append(sb, "\"", 1);
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        switch (*p) {
            case '"':
                sb_append_str(sb, "\\\"");
                break;
            case '\\':
                sb_append_str(sb, "\\\\");
                break;
            case '\n':
                sb_append_str(sb, "\\n");
                break;
            case '\r':
                sb_append_str(sb, "\\r");
                break;
            case '\t':
                sb_append_str(sb, "\\t");
                break;
            default:
                if (*p < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof buf, "\\u%04x", *p);
                    sb_append_str(sb, buf);
                } else {
                    sb_append(sb, (const char *)p, 1);
                }
        }
    }
    sb_append(sb, "\"", 1);
}

static void write_number(double n, StrBuf *sb) {
    char buf[64];
    double rounded = (double)(long long)n;
    if (n == rounded && n > -1e15 && n < 1e15) {
        snprintf(buf, sizeof buf, "%lld", (long long)n);
    } else {
        snprintf(buf, sizeof buf, "%.17g", n);
    }
    sb_append_str(sb, buf);
}

void json_write(const JsonValue *value, StrBuf *sb) {
    if (value == NULL) {
        sb_append_str(sb, "null");
        return;
    }
    switch (value->type) {
        case JSON_NULL:
            sb_append_str(sb, "null");
            break;
        case JSON_BOOL:
            sb_append_str(sb, value->as.boolean ? "true" : "false");
            break;
        case JSON_NUMBER:
            write_number(value->as.number, sb);
            break;
        case JSON_STRING:
            write_escaped_string(value->as.string, sb);
            break;
        case JSON_ARRAY:
            sb_append(sb, "[", 1);
            for (size_t i = 0; i < value->as.array.count; i++) {
                if (i > 0) {
                    sb_append(sb, ",", 1);
                }
                json_write(value->as.array.items[i], sb);
            }
            sb_append(sb, "]", 1);
            break;
        case JSON_OBJECT:
            sb_append(sb, "{", 1);
            for (size_t i = 0; i < value->as.object.count; i++) {
                if (i > 0) {
                    sb_append(sb, ",", 1);
                }
                write_escaped_string(value->as.object.keys[i], sb);
                sb_append(sb, ":", 1);
                json_write(value->as.object.values[i], sb);
            }
            sb_append(sb, "}", 1);
            break;
    }
}

/* -------------------------------------------------------------------- parse */

typedef struct {
    const char *p;
    char *err;
} Parser;

static void set_err(Parser *ps, const char *msg) {
    if (ps->err == NULL) {
        ps->err = strdup(msg);
    }
}

static void skip_ws(Parser *ps) {
    while (*ps->p == ' ' || *ps->p == '\t' || *ps->p == '\n' || *ps->p == '\r') {
        ps->p++;
    }
}

static JsonValue *parse_value(Parser *ps);

static int hex_digit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static void append_utf8(StrBuf *sb, unsigned int cp) {
    char buf[4];
    int n = 0;
    if (cp <= 0x7F) {
        buf[0] = (char)cp;
        n = 1;
    } else if (cp <= 0x7FF) {
        buf[0] = (char)(0xC0 | (cp >> 6));
        buf[1] = (char)(0x80 | (cp & 0x3F));
        n = 2;
    } else if (cp <= 0xFFFF) {
        buf[0] = (char)(0xE0 | (cp >> 12));
        buf[1] = (char)(0x80 | ((cp >> 6) & 0x3F));
        buf[2] = (char)(0x80 | (cp & 0x3F));
        n = 3;
    } else {
        buf[0] = (char)(0xF0 | (cp >> 18));
        buf[1] = (char)(0x80 | ((cp >> 12) & 0x3F));
        buf[2] = (char)(0x80 | ((cp >> 6) & 0x3F));
        buf[3] = (char)(0x80 | (cp & 0x3F));
        n = 4;
    }
    sb_append(sb, buf, (size_t)n);
}

/* Parses the body of a JSON string (opening quote already consumed).
 * Returns a malloc'd, NUL-terminated C string, or NULL on error. */
static char *parse_string_body(Parser *ps) {
    StrBuf sb;
    sb_init(&sb);
    while (1) {
        char c = *ps->p;
        if (c == '\0') {
            set_err(ps, "unterminated string");
            sb_free(&sb);
            return NULL;
        }
        if (c == '"') {
            ps->p++;
            break;
        }
        if (c == '\\') {
            ps->p++;
            char esc = *ps->p;
            switch (esc) {
                case '"':
                    sb_append(&sb, "\"", 1);
                    ps->p++;
                    break;
                case '\\':
                    sb_append(&sb, "\\", 1);
                    ps->p++;
                    break;
                case '/':
                    sb_append(&sb, "/", 1);
                    ps->p++;
                    break;
                case 'b':
                    sb_append(&sb, "\b", 1);
                    ps->p++;
                    break;
                case 'f':
                    sb_append(&sb, "\f", 1);
                    ps->p++;
                    break;
                case 'n':
                    sb_append(&sb, "\n", 1);
                    ps->p++;
                    break;
                case 'r':
                    sb_append(&sb, "\r", 1);
                    ps->p++;
                    break;
                case 't':
                    sb_append(&sb, "\t", 1);
                    ps->p++;
                    break;
                case 'u': {
                    ps->p++;
                    unsigned int cp = 0;
                    for (int i = 0; i < 4; i++) {
                        int d = hex_digit(ps->p[i]);
                        if (d < 0) {
                            set_err(ps, "invalid \\u escape");
                            sb_free(&sb);
                            return NULL;
                        }
                        cp = (cp << 4) | (unsigned int)d;
                    }
                    ps->p += 4;
                    if (cp >= 0xD800 && cp <= 0xDBFF && ps->p[0] == '\\' && ps->p[1] == 'u') {
                        unsigned int low = 0;
                        int ok = 1;
                        for (int i = 0; i < 4; i++) {
                            int d = hex_digit(ps->p[2 + i]);
                            if (d < 0) {
                                ok = 0;
                                break;
                            }
                            low = (low << 4) | (unsigned int)d;
                        }
                        if (ok && low >= 0xDC00 && low <= 0xDFFF) {
                            ps->p += 6;
                            cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
                        }
                    }
                    append_utf8(&sb, cp);
                    break;
                }
                default:
                    set_err(ps, "invalid escape sequence");
                    sb_free(&sb);
                    return NULL;
            }
            continue;
        }
        sb_append(&sb, &c, 1);
        ps->p++;
    }
    if (sb.data == NULL) {
        sb_append(&sb, "", 0);
    }
    return sb.data;
}

static JsonValue *parse_string(Parser *ps) {
    ps->p++; /* opening quote */
    char *s = parse_string_body(ps);
    if (s == NULL) {
        return NULL;
    }
    JsonValue *v = new_value(JSON_STRING);
    v->as.string = s;
    return v;
}

static JsonValue *parse_number(Parser *ps) {
    const char *start = ps->p;
    if (*ps->p == '-') ps->p++;
    while (isdigit((unsigned char)*ps->p)) ps->p++;
    if (*ps->p == '.') {
        ps->p++;
        while (isdigit((unsigned char)*ps->p)) ps->p++;
    }
    if (*ps->p == 'e' || *ps->p == 'E') {
        ps->p++;
        if (*ps->p == '+' || *ps->p == '-') ps->p++;
        while (isdigit((unsigned char)*ps->p)) ps->p++;
    }
    if (ps->p == start) {
        set_err(ps, "invalid number");
        return NULL;
    }
    char buf[64];
    size_t n = (size_t)(ps->p - start);
    if (n >= sizeof buf) n = sizeof(buf) - 1;
    memcpy(buf, start, n);
    buf[n] = '\0';
    JsonValue *v = new_value(JSON_NUMBER);
    v->as.number = strtod(buf, NULL);
    return v;
}

static int literal_at(Parser *ps, const char *literal) {
    size_t n = strlen(literal);
    if (strncmp(ps->p, literal, n) == 0) {
        ps->p += n;
        return 1;
    }
    return 0;
}

static JsonValue *parse_array(Parser *ps) {
    ps->p++; /* '[' */
    JsonValue *arr = json_new_array();
    skip_ws(ps);
    if (*ps->p == ']') {
        ps->p++;
        return arr;
    }
    while (1) {
        skip_ws(ps);
        JsonValue *item = parse_value(ps);
        if (item == NULL) {
            json_free(arr);
            return NULL;
        }
        json_array_append(arr, item);
        skip_ws(ps);
        if (*ps->p == ',') {
            ps->p++;
            continue;
        }
        if (*ps->p == ']') {
            ps->p++;
            break;
        }
        set_err(ps, "expected ',' or ']' in array");
        json_free(arr);
        return NULL;
    }
    return arr;
}

static JsonValue *parse_object(Parser *ps) {
    ps->p++; /* '{' */
    JsonValue *obj = json_new_object();
    skip_ws(ps);
    if (*ps->p == '}') {
        ps->p++;
        return obj;
    }
    while (1) {
        skip_ws(ps);
        if (*ps->p != '"') {
            set_err(ps, "expected string key in object");
            json_free(obj);
            return NULL;
        }
        ps->p++;
        char *key = parse_string_body(ps);
        if (key == NULL) {
            json_free(obj);
            return NULL;
        }
        skip_ws(ps);
        if (*ps->p != ':') {
            set_err(ps, "expected ':' after object key");
            free(key);
            json_free(obj);
            return NULL;
        }
        ps->p++;
        skip_ws(ps);
        JsonValue *val = parse_value(ps);
        if (val == NULL) {
            free(key);
            json_free(obj);
            return NULL;
        }
        json_object_set(obj, key, val);
        free(key);
        skip_ws(ps);
        if (*ps->p == ',') {
            ps->p++;
            continue;
        }
        if (*ps->p == '}') {
            ps->p++;
            break;
        }
        set_err(ps, "expected ',' or '}' in object");
        json_free(obj);
        return NULL;
    }
    return obj;
}

static JsonValue *parse_value(Parser *ps) {
    skip_ws(ps);
    char c = *ps->p;
    if (c == '"') return parse_string(ps);
    if (c == '{') return parse_object(ps);
    if (c == '[') return parse_array(ps);
    if (c == '-' || isdigit((unsigned char)c)) return parse_number(ps);
    if (literal_at(ps, "true")) return json_new_bool(1);
    if (literal_at(ps, "false")) return json_new_bool(0);
    if (literal_at(ps, "null")) return json_new_null();
    set_err(ps, "unexpected character");
    return NULL;
}

JsonValue *json_parse(const char *text, char **err_out) {
    Parser ps = {text, NULL};
    JsonValue *v = parse_value(&ps);
    if (v != NULL) {
        skip_ws(&ps);
        if (*ps.p != '\0') {
            json_free(v);
            v = NULL;
            set_err(&ps, "trailing characters after JSON value");
        }
    }
    if (v == NULL) {
        if (err_out != NULL) {
            *err_out = ps.err != NULL ? ps.err : strdup("invalid JSON");
        } else {
            free(ps.err);
        }
    } else {
        free(ps.err);
        if (err_out != NULL) {
            *err_out = NULL;
        }
    }
    return v;
}
