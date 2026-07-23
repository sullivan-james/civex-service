// Example Tier 2 (container) plugin -- computes the numeric difference
// between two fields on the record that triggered this workflow step. Copy
// this file (and Dockerfile / go.mod / civex-plugin.toml) into
// _civex/plugins/<name>/, then replace this example with your own logic.
// shim.go is the reusable protocol plumbing and shouldn't need edits.
package main

import (
	"fmt"
	"os"
)

type computeDurationPlugin struct{}

func (computeDurationPlugin) ID() string          { return "my_project.compute_duration" }
func (computeDurationPlugin) Name() string        { return "Compute Duration" }
func (computeDurationPlugin) Description() string { return "" }
func (computeDurationPlugin) Category() string    { return "transforms" }

func (computeDurationPlugin) Capabilities() []string {
	return []string{"get_context_record"}
}

func (computeDurationPlugin) ConfigSchema() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"start_field": map[string]any{"type": "string"},
			"end_field":   map[string]any{"type": "string"},
		},
		"required": []string{"start_field", "end_field"},
	}
}

func (computeDurationPlugin) Invoke(inputs, config map[string]any, ctx *Ctx) (map[string]any, error) {
	startField, _ := config["start_field"].(string)
	endField, _ := config["end_field"].(string)

	record, err := ctx.GetContextRecord()
	if err != nil {
		return nil, err
	}
	data, _ := record["data"].(map[string]any)

	start := asFloat(data[startField])
	end := asFloat(data[endField])

	return map[string]any{"duration": end - start}, nil
}

func asFloat(v any) float64 {
	f, _ := v.(float64) // JSON numbers decode as float64
	return f
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: plugin <describe|run>")
		os.Exit(1)
	}
	Serve(os.Args[1], computeDurationPlugin{})
}
