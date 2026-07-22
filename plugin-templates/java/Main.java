import java.io.BufferedReader;
import java.io.EOFException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Minimal Tier 2 (container) plugin shim. Speaks the same newline-delimited
 * JSON protocol as civex-plugin-sdk (civex_plugin_sdk.protocol / .serve) --
 * see docs/writing-custom-plugins.md for the frame shapes this mirrors.
 *
 * Copy this file into your own _civex/plugins/&lt;name&gt;/ directory
 * alongside civex-plugin.toml and the Dockerfile, then edit the PLUGIN_*
 * constants, configSchema(), and invoke() below. Nothing past the "protocol
 * plumbing" marker should normally need to change.
 *
 * Invoked as `java -cp /app Main <mode>`, where mode is "describe" or
 * "run" -- entrypoint.sh forwards docker run's trailing arg here. Protocol
 * frames are read from stdin and written to the fd-dup'd real stdout that
 * entrypoint.sh hands off as fd 3 (see its comment, and CIVEX-133); by the
 * time main() runs, System.out itself already points at /dev/null.
 */
public final class Main {

    // -- Edit this section for your own plugin ------------------------------

    static final String PLUGIN_ID = "example.java_echo";
    static final String PLUGIN_NAME = "Java Echo";
    static final String PLUGIN_DESCRIPTION =
            "Echoes its config text back; calls commit when asked to, as an example capability.";
    static final String PLUGIN_CATEGORY = "example";
    static final List<String> PLUGIN_CAPABILITIES = List.of("commit");

    /** JSON Schema for this plugin's config, advertised in `describe` -- the
     * same shape pydantic's BaseModel.model_json_schema() produces for a
     * Tier 1 plugin's Config. */
    static Map<String, Object> configSchema() {
        Map<String, Object> properties = new LinkedHashMap<>();
        properties.put("text", Map.of("type", "string"));
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");
        schema.put("properties", properties);
        schema.put("required", List.of("text"));
        return schema;
    }

    /** Runs one step. `inputs`/`config` are decoded JSON values (Map, List,
     * String, Long/Double, Boolean, or null). Return the outputs map;
     * declare every ctx.call() method name in PLUGIN_CAPABILITIES above. */
    static Map<String, Object> invoke(Map<String, Object> inputs, Map<String, Object> config, Ctx ctx)
            throws IOException {
        if (Boolean.TRUE.equals(inputs.get("call_commit"))) {
            ctx.call("commit", Map.of());
        }
        Map<String, Object> outputs = new LinkedHashMap<>();
        outputs.put("echo", config.get("text"));
        outputs.put("inputs", inputs);
        return outputs;
    }

    // -- Protocol plumbing -- shouldn't normally need to change below -------

    public static void main(String[] args) throws IOException {
        if (args.length != 1 || !(args[0].equals("describe") || args[0].equals("run"))) {
            System.err.println("usage: Main <describe|run>");
            System.exit(2);
            return;
        }
        PrintStream out = openIsolatedStdout();
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        try {
            if (args[0].equals("describe")) {
                handleDescribe(in, out);
            } else {
                handleRun(in, out);
            }
        } finally {
            out.flush();
        }
    }

    /** Opens the real stdout channel entrypoint.sh duped to fd 3 before
     * redirecting the public fd 1 to /dev/null -- see that script's
     * comment. All protocol frames must be written through this stream,
     * never through System.out. */
    static PrintStream openIsolatedStdout() throws IOException {
        return new PrintStream(new FileOutputStream("/proc/self/fd/3"), true, StandardCharsets.UTF_8);
    }

    static void handleDescribe(BufferedReader in, PrintStream out) throws IOException {
        readFrame(in); // the incoming `describe` request frame; contents unused
        Map<String, Object> frame = new LinkedHashMap<>();
        frame.put("type", "describe_result");
        frame.put("id", PLUGIN_ID);
        frame.put("name", PLUGIN_NAME);
        frame.put("description", PLUGIN_DESCRIPTION);
        frame.put("category", PLUGIN_CATEGORY);
        frame.put("capabilities", PLUGIN_CAPABILITIES);
        frame.put("inputs", null);
        frame.put("outputs", null);
        frame.put("config_schema", configSchema());
        sendFrame(out, frame);
    }

    @SuppressWarnings("unchecked")
    static void handleRun(BufferedReader in, PrintStream out) throws IOException {
        Map<String, Object> request = readFrame(in);
        Map<String, Object> inputs = (Map<String, Object>) request.getOrDefault("inputs", Map.of());
        Map<String, Object> config = (Map<String, Object>) request.getOrDefault("config", Map.of());
        Ctx ctx = new Ctx(in, out);
        try {
            Map<String, Object> outputs = invoke(inputs, config, ctx);
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("type", "result");
            result.put("outputs", outputs == null ? Map.of() : outputs);
            sendFrame(out, result);
        } catch (Exception e) {
            sendError(out, null, "plugin_error", String.valueOf(e.getMessage()), false);
        }
    }

    static void sendError(PrintStream out, String callId, String kind, String message, boolean retryable) {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("kind", kind);
        error.put("message", message);
        error.put("retryable", retryable);
        Map<String, Object> frame = new LinkedHashMap<>();
        frame.put("type", "error");
        frame.put("call_id", callId);
        frame.put("error", error);
        sendFrame(out, frame);
    }

    static Map<String, Object> readFrame(BufferedReader in) throws IOException {
        String line = in.readLine();
        while (line != null && line.strip().isEmpty()) {
            line = in.readLine();
        }
        if (line == null) {
            throw new EOFException("stdin closed before a frame was received");
        }
        Object decoded = Json.parse(line);
        if (!(decoded instanceof Map)) {
            throw new IOException("expected a JSON object frame, got: " + line);
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> frame = (Map<String, Object>) decoded;
        return frame;
    }

    static void sendFrame(PrintStream out, Map<String, Object> frame) {
        out.print(Json.write(frame));
        out.print('\n');
        out.flush();
    }

    /** RPC round trip for a declared capability: writes an `rpc_call` frame
     * and blocks on stdin for the matching `rpc_result` (or `error`) --
     * the container-tier equivalent of civex_plugin_sdk.ctx.Ctx. */
    static final class Ctx {
        private final BufferedReader in;
        private final PrintStream out;

        Ctx(BufferedReader in, PrintStream out) {
            this.in = in;
            this.out = out;
        }

        Map<String, Object> call(String method, Map<String, Object> params) throws IOException {
            String callId = UUID.randomUUID().toString().replace("-", "");
            Map<String, Object> frame = new LinkedHashMap<>();
            frame.put("type", "rpc_call");
            frame.put("call_id", callId);
            frame.put("method", method);
            frame.put("params", params);
            sendFrame(out, frame);

            Map<String, Object> response = readFrame(in);
            String type = String.valueOf(response.get("type"));
            if ("rpc_result".equals(type) && callId.equals(response.get("call_id"))) {
                @SuppressWarnings("unchecked")
                Map<String, Object> result = (Map<String, Object>) response.getOrDefault("result", Map.of());
                return result;
            }
            if ("error".equals(type)) {
                throw new IOException("rpc_call '" + method + "' failed: " + response.get("error"));
            }
            throw new IOException("unexpected frame in response to rpc_call: " + response);
        }
    }

    // -- Minimal JSON codec (no external dependencies) -----------------------

    static final class Json {
        static Object parse(String text) {
            Parser p = new Parser(text);
            Object value = p.parseValue();
            p.skipWhitespace();
            if (!p.atEnd()) {
                throw new IllegalArgumentException("trailing data after JSON value");
            }
            return value;
        }

        static String write(Object value) {
            StringBuilder sb = new StringBuilder();
            writeValue(value, sb);
            return sb.toString();
        }

        private static void writeValue(Object value, StringBuilder sb) {
            if (value == null) {
                sb.append("null");
            } else if (value instanceof String s) {
                writeString(s, sb);
            } else if (value instanceof Boolean b) {
                sb.append(b.toString());
            } else if (value instanceof Number n) {
                sb.append(n.toString());
            } else if (value instanceof Map<?, ?> map) {
                sb.append('{');
                boolean first = true;
                for (Map.Entry<?, ?> entry : map.entrySet()) {
                    if (!first) {
                        sb.append(',');
                    }
                    first = false;
                    writeString(String.valueOf(entry.getKey()), sb);
                    sb.append(':');
                    writeValue(entry.getValue(), sb);
                }
                sb.append('}');
            } else if (value instanceof List<?> list) {
                sb.append('[');
                boolean first = true;
                for (Object item : list) {
                    if (!first) {
                        sb.append(',');
                    }
                    first = false;
                    writeValue(item, sb);
                }
                sb.append(']');
            } else {
                throw new IllegalArgumentException("cannot encode value of type " + value.getClass());
            }
        }

        private static void writeString(String s, StringBuilder sb) {
            sb.append('"');
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
                switch (c) {
                    case '"' -> sb.append("\\\"");
                    case '\\' -> sb.append("\\\\");
                    case '\n' -> sb.append("\\n");
                    case '\r' -> sb.append("\\r");
                    case '\t' -> sb.append("\\t");
                    default -> {
                        if (c < 0x20) {
                            sb.append(String.format("\\u%04x", (int) c));
                        } else {
                            sb.append(c);
                        }
                    }
                }
            }
            sb.append('"');
        }

        private static final class Parser {
            private final String text;
            private int pos;

            Parser(String text) {
                this.text = text;
                this.pos = 0;
            }

            boolean atEnd() {
                return pos >= text.length();
            }

            void skipWhitespace() {
                while (pos < text.length() && Character.isWhitespace(text.charAt(pos))) {
                    pos++;
                }
            }

            Object parseValue() {
                skipWhitespace();
                if (atEnd()) {
                    throw new IllegalArgumentException("unexpected end of JSON input");
                }
                char c = text.charAt(pos);
                return switch (c) {
                    case '{' -> parseObject();
                    case '[' -> parseArray();
                    case '"' -> parseString();
                    case 't', 'f' -> parseBoolean();
                    case 'n' -> parseNull();
                    default -> parseNumber();
                };
            }

            Map<String, Object> parseObject() {
                expect('{');
                Map<String, Object> result = new LinkedHashMap<>();
                skipWhitespace();
                if (peek() == '}') {
                    pos++;
                    return result;
                }
                while (true) {
                    skipWhitespace();
                    String key = parseString();
                    skipWhitespace();
                    expect(':');
                    Object value = parseValue();
                    result.put(key, value);
                    skipWhitespace();
                    char next = peek();
                    if (next == ',') {
                        pos++;
                        continue;
                    }
                    if (next == '}') {
                        pos++;
                        break;
                    }
                    throw new IllegalArgumentException("expected ',' or '}' at position " + pos);
                }
                return result;
            }

            List<Object> parseArray() {
                expect('[');
                List<Object> result = new ArrayList<>();
                skipWhitespace();
                if (peek() == ']') {
                    pos++;
                    return result;
                }
                while (true) {
                    Object value = parseValue();
                    result.add(value);
                    skipWhitespace();
                    char next = peek();
                    if (next == ',') {
                        pos++;
                        continue;
                    }
                    if (next == ']') {
                        pos++;
                        break;
                    }
                    throw new IllegalArgumentException("expected ',' or ']' at position " + pos);
                }
                return result;
            }

            String parseString() {
                expect('"');
                StringBuilder sb = new StringBuilder();
                while (true) {
                    if (atEnd()) {
                        throw new IllegalArgumentException("unterminated string");
                    }
                    char c = text.charAt(pos++);
                    if (c == '"') {
                        break;
                    }
                    if (c == '\\') {
                        char esc = text.charAt(pos++);
                        switch (esc) {
                            case '"' -> sb.append('"');
                            case '\\' -> sb.append('\\');
                            case '/' -> sb.append('/');
                            case 'n' -> sb.append('\n');
                            case 't' -> sb.append('\t');
                            case 'r' -> sb.append('\r');
                            case 'b' -> sb.append('\b');
                            case 'f' -> sb.append('\f');
                            case 'u' -> {
                                String hex = text.substring(pos, pos + 4);
                                sb.append((char) Integer.parseInt(hex, 16));
                                pos += 4;
                            }
                            default -> throw new IllegalArgumentException("invalid escape: \\" + esc);
                        }
                    } else {
                        sb.append(c);
                    }
                }
                return sb.toString();
            }

            Boolean parseBoolean() {
                if (text.startsWith("true", pos)) {
                    pos += 4;
                    return Boolean.TRUE;
                }
                if (text.startsWith("false", pos)) {
                    pos += 5;
                    return Boolean.FALSE;
                }
                throw new IllegalArgumentException("invalid literal at position " + pos);
            }

            Object parseNull() {
                if (text.startsWith("null", pos)) {
                    pos += 4;
                    return null;
                }
                throw new IllegalArgumentException("invalid literal at position " + pos);
            }

            Number parseNumber() {
                int start = pos;
                if (peek() == '-') {
                    pos++;
                }
                while (!atEnd() && Character.isDigit(text.charAt(pos))) {
                    pos++;
                }
                boolean isDouble = false;
                if (!atEnd() && text.charAt(pos) == '.') {
                    isDouble = true;
                    pos++;
                    while (!atEnd() && Character.isDigit(text.charAt(pos))) {
                        pos++;
                    }
                }
                if (!atEnd() && (text.charAt(pos) == 'e' || text.charAt(pos) == 'E')) {
                    isDouble = true;
                    pos++;
                    if (!atEnd() && (text.charAt(pos) == '+' || text.charAt(pos) == '-')) {
                        pos++;
                    }
                    while (!atEnd() && Character.isDigit(text.charAt(pos))) {
                        pos++;
                    }
                }
                String token = text.substring(start, pos);
                if (token.isEmpty() || token.equals("-")) {
                    throw new IllegalArgumentException("invalid number at position " + start);
                }
                if (isDouble) {
                    return Double.parseDouble(token);
                }
                try {
                    return Long.parseLong(token);
                } catch (NumberFormatException e) {
                    return Double.parseDouble(token);
                }
            }

            char peek() {
                if (atEnd()) {
                    throw new IllegalArgumentException("unexpected end of JSON input");
                }
                return text.charAt(pos);
            }

            void expect(char c) {
                if (atEnd() || text.charAt(pos) != c) {
                    throw new IllegalArgumentException("expected '" + c + "' at position " + pos);
                }
                pos++;
            }
        }
    }
}
