//! The plugin itself -- this is the file a plugin author edits. Everything
//! above the "shim plumbing" marker is the whole contract; everything below
//! it wires that contract into the `describe`/`run` dispatch in `main.rs`
//! and shouldn't need to change.
//!
//! This starter ships a working "echo" example (same shape as the Tier 1
//! Python SDK's `examples/echo_plugin.py`) so `cargo build` and a `docker
//! run` smoke test succeed out of the box -- replace it with your own logic.

use crate::ctx::{Ctx, RpcError};
use crate::protocol::{IoSpec, OutFrame};
use schemars::JsonSchema;
use serde::Deserialize;
use serde_json::Value;
use std::collections::HashMap;
use std::io::BufRead;

// ---------------------------------------------------------------------------
// Edit below this line to build your own plugin.
// ---------------------------------------------------------------------------

/// Unique identifier used in workflow YAML. Prefix with your project name to
/// avoid collisions with other plugins.
pub const ID: &str = "example.echo";
/// Human-readable name shown in the UI.
pub const NAME: &str = "Echo";
pub const DESCRIPTION: &str = "Echoes its configured text back, plus whatever inputs it was given.";
/// Informational grouping only -- no functional effect.
pub const CATEGORY: &str = "example";
/// Every `ctx.*` method this plugin calls, by name. A call to an undeclared
/// capability fails at run time with `capability_denied` -- enforced against
/// this list as captured at `describe` time, not anything this process
/// claims about itself while running.
pub const CAPABILITIES: &[&str] = &["commit"];

/// The step's `config:` block, validated by serde before `run()` is called.
#[derive(Debug, Deserialize, JsonSchema)]
pub struct Config {
    pub text: String,
}

/// `None` disables input-name checking entirely (no contract declared yet);
/// `Some(vec![])` declares "this plugin takes no inputs" and makes wiring
/// anything into it a save-time error. See `IOSpec`'s doc comment in
/// `protocol.rs` for the full `None` vs `[]` distinction.
pub fn inputs() -> Option<Vec<IoSpec>> {
    None
}

pub fn outputs() -> Option<Vec<IoSpec>> {
    Some(vec![
        IoSpec::new("echo", "string", true, "The configured text, unchanged."),
        IoSpec::new("inputs", "mapping", true, "The raw inputs this step received."),
    ])
}

/// Return output values other steps reference as `<this_step_id>.<output_name>`.
/// Return `Err` (or panic -- a panic is caught and reported the same way) to
/// fail the whole workflow job; nothing committed by earlier steps in the
/// same run is kept.
pub fn run<R: BufRead>(
    inputs: HashMap<String, Value>,
    config: Config,
    ctx: &mut Ctx<'_, R>,
) -> Result<HashMap<String, Value>, PluginError> {
    if inputs
        .get("call_commit")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        ctx.commit()?;
    }
    let mut outputs = HashMap::new();
    outputs.insert("echo".to_string(), Value::String(config.text));
    outputs.insert(
        "inputs".to_string(),
        Value::Object(inputs.into_iter().collect()),
    );
    Ok(outputs)
}

// ---------------------------------------------------------------------------
// Shim plumbing -- shouldn't need to change.
// ---------------------------------------------------------------------------

/// {"kind", "message", "retryable"} -- same envelope shape the Python SDK's
/// `PluginError` sends. `retryable` defaults to `false`: an unclassified
/// failure is never assumed safe to retry.
pub struct PluginError {
    pub kind: String,
    pub message: String,
    pub retryable: bool,
}

impl PluginError {
    pub fn new(kind: &str, message: impl Into<String>) -> Self {
        Self {
            kind: kind.to_string(),
            message: message.into(),
            retryable: false,
        }
    }
}

impl From<RpcError> for PluginError {
    /// An unhandled failed `ctx.*` call fails the run with the host's own
    /// classification (e.g. `capability_denied`) preserved, not flattened to
    /// a generic error.
    fn from(e: RpcError) -> Self {
        Self {
            kind: e.kind,
            message: e.message,
            retryable: e.retryable,
        }
    }
}

pub fn parse_config(raw: HashMap<String, Value>) -> Result<Config, String> {
    serde_json::from_value(Value::Object(raw.into_iter().collect())).map_err(|e| e.to_string())
}

pub fn describe() -> OutFrame {
    OutFrame::DescribeResult {
        id: ID.to_string(),
        name: NAME.to_string(),
        description: DESCRIPTION.to_string(),
        category: CATEGORY.to_string(),
        capabilities: CAPABILITIES.iter().map(|s| s.to_string()).collect(),
        inputs: inputs(),
        outputs: outputs(),
        config_schema: serde_json::to_value(schemars::schema_for!(Config))
            .expect("JSON Schema always serializes"),
    }
}
