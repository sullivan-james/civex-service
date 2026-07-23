/* Minimal JSON value tree: just enough parsing/serialization to speak the
 * civex plugin wire protocol (see ../README.md) without pulling in a third-
 * party dependency. Not a general-purpose JSON library -- extend it if your
 * plugin needs something it doesn't cover (e.g. exact big-integer/float
 * round-tripping).
 */
#ifndef CIVEX_STARTER_JSON_H
#define CIVEX_STARTER_JSON_H

#include <stddef.h>

typedef enum {
    JSON_NULL,
    JSON_BOOL,
    JSON_NUMBER,
    JSON_STRING,
    JSON_ARRAY,
    JSON_OBJECT
} JsonType;

typedef struct JsonValue JsonValue;

struct JsonValue {
    JsonType type;
    union {
        int boolean;
        double number;
        char *string;
        struct {
            JsonValue **items;
            size_t count;
        } array;
        struct {
            char **keys;
            JsonValue **values;
            size_t count;
        } object;
    } as;
};

/* Growable byte buffer used to build serialized JSON text. */
typedef struct {
    char *data;
    size_t len;
    size_t cap;
} StrBuf;

void sb_init(StrBuf *sb);
void sb_free(StrBuf *sb);
void sb_append(StrBuf *sb, const char *s, size_t n);
void sb_append_str(StrBuf *sb, const char *s);

/* Parses one JSON value from a NUL-terminated string. On failure returns
 * NULL and, if err_out is non-NULL, sets *err_out to a malloc'd message the
 * caller must free(). */
JsonValue *json_parse(const char *text, char **err_out);

/* Serializes a value as compact JSON (no whitespace), appending to sb. */
void json_write(const JsonValue *value, StrBuf *sb);

/* Recursively frees a value tree built by json_parse or the constructors
 * below. Safe to call with NULL. */
void json_free(JsonValue *value);

/* Constructors. Each returns a new heap value the caller owns (frees via
 * json_free, or by handing it to json_object_set/json_array_append, which
 * take ownership). */
JsonValue *json_new_null(void);
JsonValue *json_new_bool(int value);
JsonValue *json_new_number(double value);
JsonValue *json_new_string(const char *value);
JsonValue *json_new_array(void);
JsonValue *json_new_object(void);

/* Appends to a JSON_ARRAY value, taking ownership of item. */
void json_array_append(JsonValue *array, JsonValue *item);

/* Sets (or replaces) a key on a JSON_OBJECT value, taking ownership of
 * value. */
void json_object_set(JsonValue *object, const char *key, JsonValue *value);

/* Accessors. All return NULL/defaults rather than asserting on a type
 * mismatch or missing key -- wire input is untrusted, so callers are
 * expected to check for NULL rather than crash on a malformed frame. */
const JsonValue *json_object_get(const JsonValue *object, const char *key);
const char *json_get_string(const JsonValue *value, const char *fallback);
double json_get_number(const JsonValue *value, double fallback);
int json_get_bool(const JsonValue *value, int fallback);
int json_is_null(const JsonValue *value);

#endif
