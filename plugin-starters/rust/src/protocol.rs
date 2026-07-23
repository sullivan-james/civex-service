//! Wire protocol frame shapes -- mirrors `civex_plugin_sdk.protocol` (the
//! Python Tier 1 SDK) so a Tier 2 container plugin speaks byte-for-byte the
//! same newline-delimited JSON frames over stdin/stdout, just via `docker
//! run -i <image> <mode>` instead of `uv run`.
//!
//! One JSON object per line, in both directions over a single stdin/stdout
//! pair. `mode` (this process's first argv, "describe" or "run") picks which
//! side of the exchange this invocation performs; frames sent back over the
//! private (fd-duped, see `io::isolate_stdout`) stdout use the same
//! `describe_result` / `result` / `error` / `log` / `rpc_call` shapes Tier 1
//! plugins use, and the host answers an `rpc_call` with `rpc_result`.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

/// One declared input or output of a plugin -- see `plugin_base.IOSpec` in
/// the Python SDK. `type_` is deliberately a plain string, not a closed enum:
/// an older host reading a newer plugin's `describe_result` shouldn't choke
/// on a type name it doesn't recognize yet.
#[derive(Debug, Clone, Serialize)]
pub struct IoSpec {
    pub name: String,
    #[serde(rename = "type")]
    pub type_: String,
    pub required: bool,
    pub description: String,
}

impl IoSpec {
    pub fn new(name: &str, type_: &str, required: bool, description: &str) -> Self {
        Self {
            name: name.to_string(),
            type_: type_.to_string(),
            required,
            description: description.to_string(),
        }
    }
}

/// {"kind", "message", "retryable"} -- see `civex_plugin_sdk.errors`.
/// `retryable` answers the one question a caller acts on: could running this
/// again, unchanged, plausibly succeed? Defaults to `false`, the safe answer.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorPayload {
    pub kind: String,
    pub message: String,
    #[serde(default)]
    pub retryable: bool,
}

impl ErrorPayload {
    pub fn new(kind: &str, message: impl Into<String>) -> Self {
        Self {
            kind: kind.to_string(),
            message: message.into(),
            retryable: false,
        }
    }
}

/// The `run` request this process reads from stdin (a single line) when
/// invoked as `<image> run`.
#[derive(Debug, Deserialize)]
pub struct RunRequest {
    #[serde(default)]
    pub inputs: HashMap<String, Value>,
    #[serde(default)]
    pub config: HashMap<String, Value>,
}

/// The host's response to an `rpc_call`, read from stdin while a `run` is in
/// flight. `error` is set instead of `result` when the host's own
/// classification of a failed capability call comes back (e.g.
/// `capability_denied`).
#[derive(Debug, Deserialize)]
#[serde(tag = "type")]
pub enum HostFrame {
    #[serde(rename = "rpc_result")]
    RpcResult {
        call_id: String,
        #[serde(default)]
        result: HashMap<String, Value>,
    },
    #[serde(rename = "error")]
    Error {
        call_id: Option<String>,
        error: ErrorPayload,
    },
}

/// Frames this process writes to its private (fd-duped) stdout.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type")]
pub enum OutFrame {
    #[serde(rename = "describe_result")]
    DescribeResult {
        id: String,
        name: String,
        description: String,
        category: String,
        capabilities: Vec<String>,
        inputs: Option<Vec<IoSpec>>,
        outputs: Option<Vec<IoSpec>>,
        config_schema: Value,
    },
    #[serde(rename = "result")]
    Result { outputs: HashMap<String, Value> },
    #[serde(rename = "error")]
    Error {
        call_id: Option<String>,
        error: ErrorPayload,
    },
    #[serde(rename = "log")]
    #[allow(dead_code)]
    Log { stream: String, text: String },
    #[serde(rename = "rpc_call")]
    RpcCall {
        call_id: String,
        method: String,
        params: HashMap<String, Value>,
    },
}

/// Above this size, a binary payload would be written to a shared scratch
/// path instead of base64-inlined (see `encode_binary` in the Python SDK).
/// This starter always inlines -- large-file scratch-path support is left
/// for a plugin author to add if they need it.
pub const BINARY_INLINE_THRESHOLD: usize = 1_000_000;

pub fn encode_binary(data: &[u8]) -> Value {
    use base64::Engine;
    serde_json::json!({
        "encoding": "base64",
        "data": base64::engine::general_purpose::STANDARD.encode(data),
    })
}

pub fn decode_binary(payload: &Value) -> Result<Vec<u8>, String> {
    use base64::Engine;
    match payload.get("encoding").and_then(Value::as_str) {
        Some("base64") => {
            let data = payload
                .get("data")
                .and_then(Value::as_str)
                .ok_or("binary payload missing 'data'")?;
            base64::engine::general_purpose::STANDARD
                .decode(data)
                .map_err(|e| format!("invalid base64 payload: {e}"))
        }
        Some("path") => {
            let path = payload
                .get("path")
                .and_then(Value::as_str)
                .ok_or("binary payload missing 'path'")?;
            std::fs::read(path).map_err(|e| format!("failed to read {path}: {e}"))
        }
        other => Err(format!("unknown binary encoding: {other:?}")),
    }
}
