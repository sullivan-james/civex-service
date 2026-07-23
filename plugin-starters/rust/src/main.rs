//! Entrypoint for a civex Tier 2 (container) plugin written in Rust.
//!
//! Invoked as `docker run -i <image> <mode>` where `<mode>` is `describe` or
//! `run` -- the host always spawns a fresh container for a single operation,
//! same as how the Tier 1 subprocess runtime spawns a fresh `uv run` process
//! per `describe`/`run` rather than keeping one alive across both.
//!
//!   describe: no stdin needed -- write one `describe_result` frame and exit.
//!   run:      read one `run` request line from stdin, execute the plugin,
//!             (which may exchange `rpc_call`/`rpc_result` frames with the
//!             host along the way), then write one `result`/`error` frame.
//!
//! Stdout isolation happens before anything else runs, exactly mirroring
//! `civex_plugin_sdk.io.isolate_stdout` in the Tier 1 SDK -- see `io.rs`.

mod ctx;
mod io;
mod plugin;
mod protocol;

use ctx::Ctx;
use io::{isolate_stdout, read_line, FrameWriter};
use protocol::{ErrorPayload, OutFrame, RunRequest};

fn main() {
    // Must happen before any plugin code runs -- see io::isolate_stdout.
    let out = isolate_stdout();
    let mut writer = FrameWriter::new(out);

    let mode = std::env::args().nth(1);
    match mode.as_deref() {
        Some("describe") => writer.send(&plugin::describe()),
        Some("run") => run_mode(&mut writer),
        other => {
            writer.send(&OutFrame::Error {
                call_id: None,
                error: ErrorPayload::new(
                    "protocol_error",
                    format!("expected argv[1] to be 'describe' or 'run', got {other:?}"),
                ),
            });
            std::process::exit(1);
        }
    }
}

fn run_mode(writer: &mut FrameWriter) {
    let stdin = std::io::stdin();
    let mut lock = stdin.lock();

    let line = match read_line(&mut lock) {
        Some(l) => l,
        None => return fail(writer, "protocol_error", "stdin closed before a run request arrived"),
    };
    let request: RunRequest = match serde_json::from_str(&line) {
        Ok(r) => r,
        Err(e) => return fail(writer, "protocol_error", format!("malformed run request: {e}")),
    };
    let config = match plugin::parse_config(request.config) {
        Ok(c) => c,
        Err(e) => return fail(writer, "config_validation_error", e),
    };

    let outputs = {
        let mut ctx = Ctx::new(writer, &mut lock);
        plugin::run(request.inputs, config, &mut ctx)
    };

    match outputs {
        Ok(outputs) => writer.send(&OutFrame::Result { outputs }),
        Err(e) => fail(writer, &e.kind, e.message),
    }
}

fn fail(writer: &mut FrameWriter, kind: &str, message: impl Into<String>) {
    writer.send(&OutFrame::Error {
        call_id: None,
        error: ErrorPayload::new(kind, message),
    });
    std::process::exit(1);
}
