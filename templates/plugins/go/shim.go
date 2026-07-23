// Language shim implementing civex's stdin/stdout JSON wire protocol for a
// Tier 2 (container) plugin, mirroring civex-plugin-sdk (the Python SDK
// used by Tier 1 subprocess plugins) frame-for-frame. This file is the
// reusable plumbing -- copy it into your own plugin unmodified and write
// your plugin logic in main.go instead.
//
// Unlike the Tier 1 subprocess (`uv run <plugin>.py`, which stays alive and
// waits for whichever frame type -- describe or run -- arrives first on
// stdin), a Tier 2 container is invoked once per operation as
// `docker run -i <image> <mode>`, with `<mode>` ("describe" or "run") given
// as argv[1]. That's the only structural difference; the frames themselves
// (describe_result / run / result / error / rpc_call / rpc_result) are
// identical across both tiers, so nothing downstream needs a tier-specific
// branch to talk to either one.
package main

import (
	"bufio"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
	"syscall"
)

// -- fd-dup stdout isolation (same trick as civex_plugin_sdk.io.isolate_stdout) --

// isolateStdout duplicates the real stdout fd to a private fd, then
// redirects the public fd 1 to /dev/null so any stray fmt.Println / library
// output your plugin code emits can't corrupt the protocol stream. Must be
// called before any plugin code runs -- see Serve below.
//
// Returns a file wrapping the private fd; every protocol frame is written
// through it, never through os.Stdout.
func isolateStdout() (*os.File, error) {
	realFD, err := syscall.Dup(1)
	if err != nil {
		return nil, fmt.Errorf("dup stdout: %w", err)
	}
	devnull, err := os.OpenFile(os.DevNull, os.O_WRONLY, 0)
	if err != nil {
		return nil, fmt.Errorf("open devnull: %w", err)
	}
	defer devnull.Close()
	if err := syscall.Dup2(int(devnull.Fd()), 1); err != nil {
		return nil, fmt.Errorf("redirect stdout to devnull: %w", err)
	}
	return os.NewFile(uintptr(realFD), "civex-protocol-stdout"), nil
}

// -- newline-delimited JSON frame I/O -----------------------------------------

type frame = map[string]any

type frameWriter struct {
	out io.Writer
}

func newFrameWriter(out io.Writer) *frameWriter {
	return &frameWriter{out: out}
}

func (w *frameWriter) send(f frame) error {
	line, err := json.Marshal(f)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(w.out, "%s\n", line)
	return err
}

type frameReader struct {
	scanner *bufio.Scanner
}

func newFrameReader(in io.Reader) *frameReader {
	return &frameReader{scanner: bufio.NewScanner(in)}
}

// next blocks for the next non-blank line and decodes it as a frame.
func (r *frameReader) next() (frame, error) {
	for r.scanner.Scan() {
		line := strings.TrimSpace(r.scanner.Text())
		if line == "" {
			continue
		}
		var f frame
		if err := json.Unmarshal([]byte(line), &f); err != nil {
			return nil, fmt.Errorf("malformed frame: %w", err)
		}
		return f, nil
	}
	if err := r.scanner.Err(); err != nil {
		return nil, err
	}
	return nil, io.EOF
}

// -- binary payloads (mirrors civex_plugin_sdk.protocol.{en,de}code_binary) --

func decodeBinary(payload frame) ([]byte, error) {
	switch payload["encoding"] {
	case "base64":
		data, _ := payload["data"].(string)
		return base64.StdEncoding.DecodeString(data)
	case "path":
		path, _ := payload["path"].(string)
		return os.ReadFile(path)
	default:
		return nil, fmt.Errorf("unknown binary encoding: %v", payload["encoding"])
	}
}

// encodeBinary always inlines as base64 -- a plugin process has no shared
// scratch dir with the host to spill large payloads to, exactly like the
// Python SDK's Ctx (constructed with scratch_dir=None inside serve()).
func encodeBinary(data []byte) frame {
	return frame{
		"encoding": "base64",
		"data":     base64.StdEncoding.EncodeToString(data),
	}
}

// -- errors (mirrors civex_plugin_sdk.errors) ---------------------------------

// PluginError is the structured failure envelope {kind, message, retryable}
// sent to the host on a failed run or a failed rpc_call. Return one from
// Invoke to classify a failure explicitly; a plain error is reported as the
// generic "plugin_error" kind, not retryable -- the same default the SDK
// uses for an exception it can't classify itself.
type PluginError struct {
	Kind      string
	Message   string
	Retryable bool
}

func (e *PluginError) Error() string { return e.Message }

func NewPluginError(message string) *PluginError {
	return &PluginError{Kind: "plugin_error", Message: message}
}

// classifyError preserves kind/retryable through an unhandled failure
// rather than flattening it to "plugin_error" -- e.g. an *RpcError bubbling
// straight out of Invoke() should still show up as "capability_denied" on
// the job record, not a generic error, mirroring how Python's RpcError
// (itself a PluginError subclass) survives the same path unchanged.
func classifyError(err error) *PluginError {
	switch e := err.(type) {
	case *PluginError:
		return e
	case *RpcError:
		return &PluginError{Kind: e.Kind, Message: e.Message, Retryable: e.Retryable}
	default:
		return NewPluginError(err.Error())
	}
}

// RpcError is raised when the host responds to an rpc_call with an error
// frame -- e.g. a capability the plugin didn't declare in Capabilities().
type RpcError struct {
	Kind      string
	Message   string
	Retryable bool
}

func (e *RpcError) Error() string { return e.Message }

// -- Ctx: RPC client for the capabilities a plugin declares -------------------

// Ctx is the out-of-process equivalent of civex's in-process WorkflowContext
// -- deliberately with no ambient "current record" or "current dataset";
// everything goes over an rpc_call, capability-checked host-side against
// whatever this plugin declared in Capabilities() at describe time.
type Ctx struct {
	writer *frameWriter
	reader *frameReader
}

func (c *Ctx) call(method string, params frame) (frame, error) {
	callID := newCallID()
	if err := c.writer.send(frame{
		"type":    "rpc_call",
		"call_id": callID,
		"method":  method,
		"params":  params,
	}); err != nil {
		return nil, err
	}
	resp, err := c.reader.next()
	if err != nil {
		return nil, err
	}
	switch resp["type"] {
	case "error":
		errPayload, _ := resp["error"].(map[string]any)
		kind, _ := errPayload["kind"].(string)
		message, _ := errPayload["message"].(string)
		retryable, _ := errPayload["retryable"].(bool)
		return nil, &RpcError{Kind: kind, Message: message, Retryable: retryable}
	case "rpc_result":
		if resp["call_id"] != callID {
			return nil, fmt.Errorf("unexpected response to rpc_call %q: %v", method, resp)
		}
		result, _ := resp["result"].(map[string]any)
		return result, nil
	default:
		return nil, fmt.Errorf("unexpected response to rpc_call %q: %v", method, resp)
	}
}

// callTool routes every capability beyond the four direct RpcMethods
// (get_file, update_record, create_record, commit) through the single
// generic "call_tool" method, exactly like civex_plugin_sdk.ctx.Ctx does --
// new host-side tools become callable without a wire protocol change.
func (c *Ctx) callTool(tool string, args frame) (frame, error) {
	return c.call("call_tool", frame{"tool": tool, "args": args})
}

// GetContextRecord returns the record that triggered this workflow step --
// the only way an out-of-process plugin learns what triggered it, since Ctx
// has no ambient "current record" field. Capability: get_context_record.
func (c *Ctx) GetContextRecord() (frame, error) {
	result, err := c.callTool("get_context_record", frame{})
	if err != nil {
		return nil, err
	}
	record, _ := result["record"].(map[string]any)
	return record, nil
}

// GetContextDataset returns the dataset the trigger record belongs to.
// Capability: get_context_dataset.
func (c *Ctx) GetContextDataset() (frame, error) {
	result, err := c.callTool("get_context_dataset", frame{})
	if err != nil {
		return nil, err
	}
	dataset, _ := result["dataset"].(map[string]any)
	return dataset, nil
}

// GetFile retrieves a stored file's bytes by hash. Capability: get_file.
func (c *Ctx) GetFile(sha256 string) ([]byte, error) {
	result, err := c.call("get_file", frame{"sha256": sha256})
	if err != nil {
		return nil, err
	}
	return decodeBinary(result)
}

// StoreFile stores bytes as a new file object, returning a FileRef-shaped
// map ({sha256, filename, size}). Capability: store_file.
func (c *Ctx) StoreFile(data []byte, filename string) (frame, error) {
	result, err := c.callTool("store_file", frame{
		"data":     encodeBinary(data),
		"filename": filename,
	})
	if err != nil {
		return nil, err
	}
	file, _ := result["file"].(map[string]any)
	return file, nil
}

// UpdateRecord merges data into any record by id. Capability: update_record.
func (c *Ctx) UpdateRecord(recordID string, data frame) (frame, error) {
	return c.call("update_record", frame{"record_id": recordID, "data": data})
}

// CreateRecord creates a new record; triggers fire for it as normal.
// contextRecordID defaults host-side to the trigger record's id when empty.
// Capability: create_record.
func (c *Ctx) CreateRecord(datasetName, schemaName string, data frame, contextRecordID string) (frame, error) {
	var contextID any
	if contextRecordID != "" {
		contextID = contextRecordID
	}
	return c.call("create_record", frame{
		"dataset_name":      datasetName,
		"schema_name":       schemaName,
		"data":              data,
		"context_record_id": contextID,
	})
}

// GetRecord fetches any record by id. Capability: get_record.
func (c *Ctx) GetRecord(recordID string) (frame, error) {
	result, err := c.callTool("get_record", frame{"record_id": recordID})
	if err != nil {
		return nil, err
	}
	record, _ := result["record"].(map[string]any)
	return record, nil
}

// FindRecords queries records. Capability: find_records.
func (c *Ctx) FindRecords(datasetName string, schemaName, parentRecordID, search string, filters []string, limit, offset int) ([]any, error) {
	args := frame{
		"dataset_name": datasetName,
		"limit":        limit,
		"offset":       offset,
	}
	if schemaName != "" {
		args["schema_name"] = schemaName
	}
	if parentRecordID != "" {
		args["parent_record_id"] = parentRecordID
	}
	if search != "" {
		args["search"] = search
	}
	if filters != nil {
		args["filters"] = filters
	}
	result, err := c.callTool("find_records", args)
	if err != nil {
		return nil, err
	}
	records, _ := result["records"].([]any)
	return records, nil
}

// DeleteRecord deletes a record. Capability: delete_record.
func (c *Ctx) DeleteRecord(recordID string) error {
	_, err := c.callTool("delete_record", frame{"record_id": recordID})
	return err
}

// GetSchema reads a schema by name. Capability: get_schema.
func (c *Ctx) GetSchema(name string) (frame, error) {
	result, err := c.callTool("get_schema", frame{"name": name})
	if err != nil {
		return nil, err
	}
	schema, _ := result["schema"].(map[string]any)
	return schema, nil
}

// ListSchemas lists every schema. Capability: list_schemas.
func (c *Ctx) ListSchemas() ([]any, error) {
	result, err := c.callTool("list_schemas", frame{})
	if err != nil {
		return nil, err
	}
	schemas, _ := result["schemas"].([]any)
	return schemas, nil
}

// GetCollection reads a dataset (collection) by name. Capability: get_collection.
func (c *Ctx) GetCollection(name string) (frame, error) {
	result, err := c.callTool("get_collection", frame{"name": name})
	if err != nil {
		return nil, err
	}
	collection, _ := result["collection"].(map[string]any)
	return collection, nil
}

// ListCollections lists every dataset (collection). Capability: list_collections.
func (c *Ctx) ListCollections() ([]any, error) {
	result, err := c.callTool("list_collections", frame{})
	if err != nil {
		return nil, err
	}
	collections, _ := result["collections"].([]any)
	return collections, nil
}

// Commit flushes pending changes to the database. The executor also commits
// once at the end of a successful run; call this yourself only if you need
// an intermediate commit. Capability: commit.
func (c *Ctx) Commit() error {
	_, err := c.call("commit", frame{})
	return err
}

var callIDCounter uint64

// newCallID doesn't need to be globally unique, only unique within one run
// -- the protocol is strictly synchronous request/response with no
// interleaving (see Ctx.call), so a per-process counter is sufficient.
func newCallID() string {
	callIDCounter++
	return fmt.Sprintf("call-%d", callIDCounter)
}

// -- Plugin contract ------------------------------------------------------------

// Plugin is what a Go plugin implements -- the same declaration surface as
// civex_plugin_sdk.plugin_base.PluginBase (id/name/description/category/
// capabilities/config schema) plus Invoke, which is Python's invoke().
type Plugin interface {
	ID() string
	Name() string
	Description() string
	Category() string
	// Capabilities lists every Ctx method this plugin calls, by capability
	// name (e.g. "find_records", not the literal string "call_tool"). A
	// call to an undeclared capability fails at run time with
	// capability_denied -- enforced host-side against this list, never
	// against anything the running container claims about itself.
	Capabilities() []string
	// ConfigSchema is real JSON Schema for this plugin's config, returned
	// verbatim in describe_result.config_schema.
	ConfigSchema() map[string]any
	// Invoke does the plugin's actual work. inputs are values from input
	// references; config is the step's validated config block. Return a map
	// of output values, referenced by downstream steps as
	// <this_step_id>.<output_name>; return an empty map if this plugin
	// produces no outputs.
	Invoke(inputs, config map[string]any, ctx *Ctx) (map[string]any, error)
}

// -- entrypoint -----------------------------------------------------------------

// Serve is the container's entrypoint, dispatching on mode ("describe" or
// "run") the same way civex_plugin_sdk.serve.serve does on frame type --
// just decided by argv instead of the first frame read, since a Tier 2
// container is spawned once per operation rather than staying alive to
// field either. Call this (and only this) from main().
func Serve(mode string, plugin Plugin) {
	switch mode {
	case "describe":
		serveDescribe(plugin)
	case "run":
		serveRun(plugin)
	default:
		fmt.Fprintf(os.Stderr, "unknown mode %q (expected \"describe\" or \"run\")\n", mode)
		os.Exit(1)
	}
}

func serveDescribe(plugin Plugin) {
	out, err := isolateStdout()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	writer := newFrameWriter(out)
	err = writer.send(frame{
		"type":          "describe_result",
		"id":            plugin.ID(),
		"name":          plugin.Name(),
		"description":   plugin.Description(),
		"category":      plugin.Category(),
		"capabilities":  plugin.Capabilities(),
		"inputs":        nil,
		"outputs":       nil,
		"config_schema": plugin.ConfigSchema(),
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func serveRun(plugin Plugin) {
	out, err := isolateStdout()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	writer := newFrameWriter(out)
	reader := newFrameReader(os.Stdin)

	req, err := reader.next()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if req["type"] != "run" {
		sendError(writer, nil, NewPluginError(fmt.Sprintf("expected a run frame, got %v", req["type"])))
		return
	}
	inputs, _ := req["inputs"].(map[string]any)
	config, _ := req["config"].(map[string]any)

	ctx := &Ctx{writer: writer, reader: reader}
	outputs, err := plugin.Invoke(inputs, config, ctx)
	if err != nil {
		sendError(writer, nil, classifyError(err))
		return
	}
	if outputs == nil {
		outputs = map[string]any{}
	}
	if err := writer.send(frame{"type": "result", "outputs": outputs}); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func sendError(writer *frameWriter, callID *string, pe *PluginError) {
	_ = writer.send(frame{
		"type":    "error",
		"call_id": callID,
		"error": frame{
			"kind":      pe.Kind,
			"message":   pe.Message,
			"retryable": pe.Retryable,
		},
	})
}
