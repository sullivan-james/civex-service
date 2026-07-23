export interface PluginIOSpec {
  name: string
  type: string
  required: boolean
  description: string
}

export interface PluginInfo {
  id: string
  name: string
  description: string
  builtin: boolean
  category: string
  capabilities: string[]
  // null = plugin declared no contract in this direction; [] = it declared
  // it has none (see civex_plugin_sdk.PluginBase.inputs)
  inputs: PluginIOSpec[] | null
  outputs: PluginIOSpec[] | null
  config_schema: {
    properties?: Record<string, { type?: string; default?: unknown }>
    required?: string[]
  }
}
