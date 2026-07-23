//! `Ctx` -- the out-of-process capability client, mirroring
//! `civex_plugin_sdk.ctx.Ctx` in the Tier 1 Python SDK. Every method sends an
//! `rpc_call` frame over the (fd-duped) stdout and blocks reading the next
//! stdin line for the matching `rpc_result`/`error` -- the protocol is
//! strictly synchronous request/response with no interleaving, so a single
//! blocking read is sufficient; the host always answers one `rpc_call`
//! before sending anything else.
//!
//! There is deliberately no ambient `.record`/`.dataset` here -- a plugin
//! only sees what it fetches through one of these calls, each capability-
//! checked host-side against the `capabilities` this plugin declared in
//! `describe`.

use crate::io::{read_line, FrameWriter};
use crate::protocol::{decode_binary, encode_binary, ErrorPayload, HostFrame, OutFrame};
use serde_json::Value;
use std::collections::HashMap;
use std::fmt;
use std::io::BufRead;

#[derive(Debug, Clone)]
pub struct RpcError {
    pub kind: String,
    pub message: String,
    pub retryable: bool,
}

impl RpcError {
    fn protocol(message: impl Into<String>) -> Self {
        Self {
            kind: "protocol_error".to_string(),
            message: message.into(),
            retryable: false,
        }
    }
}

impl fmt::Display for RpcError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.kind, self.message)
    }
}

impl std::error::Error for RpcError {}

impl From<ErrorPayload> for RpcError {
    fn from(e: ErrorPayload) -> Self {
        Self {
            kind: e.kind,
            message: e.message,
            retryable: e.retryable,
        }
    }
}

pub struct Ctx<'a, R: BufRead> {
    writer: &'a mut FrameWriter,
    stdin: &'a mut R,
}

impl<'a, R: BufRead> Ctx<'a, R> {
    pub fn new(writer: &'a mut FrameWriter, stdin: &'a mut R) -> Self {
        Self { writer, stdin }
    }

    fn call(
        &mut self,
        method: &str,
        params: HashMap<String, Value>,
    ) -> Result<HashMap<String, Value>, RpcError> {
        let call_id = uuid::Uuid::new_v4().simple().to_string();
        self.writer.send(&OutFrame::RpcCall {
            call_id: call_id.clone(),
            method: method.to_string(),
            params,
        });
        let line = read_line(&mut *self.stdin)
            .ok_or_else(|| RpcError::protocol("host closed stdin while awaiting rpc_result"))?;
        let frame: HostFrame = serde_json::from_str(&line)
            .map_err(|e| RpcError::protocol(format!("malformed frame from host: {e}")))?;
        match frame {
            HostFrame::Error { error, .. } => Err(error.into()),
            HostFrame::RpcResult {
                call_id: got,
                result,
            } => {
                if got != call_id {
                    return Err(RpcError::protocol(format!(
                        "unexpected rpc_result for call_id {got}, expected {call_id}"
                    )));
                }
                Ok(result)
            }
        }
    }

    /// All CRUD-shaped methods beyond the original four direct `RpcMethod`s
    /// go over this one generic `call_tool` rather than growing the method
    /// literal list one capability at a time -- see the note above
    /// `CAPABILITIES` in `civex_plugin_sdk.protocol`.
    fn call_tool(
        &mut self,
        tool: &str,
        args: HashMap<String, Value>,
    ) -> Result<HashMap<String, Value>, RpcError> {
        let mut params = HashMap::new();
        params.insert("tool".to_string(), Value::String(tool.to_string()));
        params.insert("args".to_string(), Value::Object(args.into_iter().collect()));
        self.call("call_tool", params)
    }

    /// The record that triggered this workflow step -- how a plugin learns
    /// what triggered it, since there's no ambient field for it.
    pub fn get_context_record(&mut self) -> Result<Value, RpcError> {
        let result = self.call_tool("get_context_record", HashMap::new())?;
        Ok(result.get("record").cloned().unwrap_or(Value::Null))
    }

    pub fn get_context_dataset(&mut self) -> Result<Value, RpcError> {
        let result = self.call_tool("get_context_dataset", HashMap::new())?;
        Ok(result.get("dataset").cloned().unwrap_or(Value::Null))
    }

    pub fn get_file(&mut self, sha256: &str) -> Result<Vec<u8>, RpcError> {
        let mut params = HashMap::new();
        params.insert("sha256".to_string(), Value::String(sha256.to_string()));
        let result = self.call("get_file", params)?;
        let payload = Value::Object(result.into_iter().collect());
        decode_binary(&payload).map_err(RpcError::protocol)
    }

    pub fn store_file(&mut self, data: &[u8], filename: &str) -> Result<Value, RpcError> {
        let mut args = HashMap::new();
        args.insert("data".to_string(), encode_binary(data));
        args.insert("filename".to_string(), Value::String(filename.to_string()));
        let result = self.call_tool("store_file", args)?;
        Ok(result.get("file").cloned().unwrap_or(Value::Null))
    }

    /// Merges `data` into any record by id -- pass the trigger's id from
    /// `get_context_record()` to update it.
    pub fn update_record(&mut self, record_id: &str, data: Value) -> Result<Value, RpcError> {
        let mut params = HashMap::new();
        params.insert("record_id".to_string(), Value::String(record_id.to_string()));
        params.insert("data".to_string(), data);
        let result = self.call("update_record", params)?;
        Ok(Value::Object(result.into_iter().collect()))
    }

    /// `context_record_id`, when `None`, defaults host-side to the trigger
    /// record's id.
    pub fn create_record(
        &mut self,
        dataset_name: &str,
        schema_name: &str,
        data: Value,
        context_record_id: Option<&str>,
    ) -> Result<Value, RpcError> {
        let mut params = HashMap::new();
        params.insert(
            "dataset_name".to_string(),
            Value::String(dataset_name.to_string()),
        );
        params.insert(
            "schema_name".to_string(),
            Value::String(schema_name.to_string()),
        );
        params.insert("data".to_string(), data);
        params.insert(
            "context_record_id".to_string(),
            context_record_id
                .map(|s| Value::String(s.to_string()))
                .unwrap_or(Value::Null),
        );
        let result = self.call("create_record", params)?;
        Ok(Value::Object(result.into_iter().collect()))
    }

    pub fn get_record(&mut self, record_id: &str) -> Result<Value, RpcError> {
        let mut args = HashMap::new();
        args.insert("record_id".to_string(), Value::String(record_id.to_string()));
        let result = self.call_tool("get_record", args)?;
        Ok(result.get("record").cloned().unwrap_or(Value::Null))
    }

    #[allow(clippy::too_many_arguments)]
    pub fn find_records(
        &mut self,
        dataset_name: &str,
        schema_name: Option<&str>,
        parent_record_id: Option<&str>,
        filters: Option<Vec<String>>,
        search: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<Value>, RpcError> {
        let mut args = HashMap::new();
        args.insert(
            "dataset_name".to_string(),
            Value::String(dataset_name.to_string()),
        );
        args.insert(
            "schema_name".to_string(),
            schema_name.map(|s| Value::String(s.to_string())).unwrap_or(Value::Null),
        );
        args.insert(
            "parent_record_id".to_string(),
            parent_record_id
                .map(|s| Value::String(s.to_string()))
                .unwrap_or(Value::Null),
        );
        args.insert(
            "filters".to_string(),
            match filters {
                Some(f) => Value::Array(f.into_iter().map(Value::String).collect()),
                None => Value::Null,
            },
        );
        args.insert(
            "search".to_string(),
            search.map(|s| Value::String(s.to_string())).unwrap_or(Value::Null),
        );
        args.insert("limit".to_string(), Value::from(limit));
        args.insert("offset".to_string(), Value::from(offset));
        let result = self.call_tool("find_records", args)?;
        Ok(result
            .get("records")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default())
    }

    pub fn delete_record(&mut self, record_id: &str) -> Result<(), RpcError> {
        let mut args = HashMap::new();
        args.insert("record_id".to_string(), Value::String(record_id.to_string()));
        self.call_tool("delete_record", args)?;
        Ok(())
    }

    pub fn get_schema(&mut self, name: &str) -> Result<Value, RpcError> {
        let mut args = HashMap::new();
        args.insert("name".to_string(), Value::String(name.to_string()));
        let result = self.call_tool("get_schema", args)?;
        Ok(result.get("schema").cloned().unwrap_or(Value::Null))
    }

    pub fn list_schemas(&mut self) -> Result<Vec<Value>, RpcError> {
        let result = self.call_tool("list_schemas", HashMap::new())?;
        Ok(result
            .get("schemas")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default())
    }

    pub fn get_collection(&mut self, name: &str) -> Result<Value, RpcError> {
        let mut args = HashMap::new();
        args.insert("name".to_string(), Value::String(name.to_string()));
        let result = self.call_tool("get_collection", args)?;
        Ok(result.get("collection").cloned().unwrap_or(Value::Null))
    }

    pub fn list_collections(&mut self) -> Result<Vec<Value>, RpcError> {
        let result = self.call_tool("list_collections", HashMap::new())?;
        Ok(result
            .get("collections")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default())
    }

    pub fn commit(&mut self) -> Result<(), RpcError> {
        self.call("commit", HashMap::new())?;
        Ok(())
    }
}
