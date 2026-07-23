//! Frame I/O: the fd-dup stdout-isolation trick (mirrors
//! `civex_plugin_sdk.io.isolate_stdout`) plus a thin newline-delimited JSON
//! writer over the resulting private fd.

use crate::protocol::OutFrame;
use std::ffi::CString;
use std::fs::File;
use std::io::{self, Write};
use std::os::unix::io::FromRawFd;

/// Duplicates the real stdout fd (1) to a private fd, then redirects the
/// public fd 1 to `/dev/null` so any stray `println!`/library output a
/// plugin author's code emits can't corrupt the protocol stream. Must be
/// called at the very start of `main()`, before any plugin code runs --
/// same requirement, same trick, as the Tier 1 SDK's `isolate_stdout()`.
///
/// `docker run -i` captures this process's stdout, so a plain fd-dup here is
/// invisible to the host and identical in effect to the subprocess tier --
/// the uniformity lives inside this binary, not in how the host spawns it.
pub fn isolate_stdout() -> File {
    unsafe {
        let real_stdout_fd = libc::dup(1);
        if real_stdout_fd < 0 {
            panic!("dup(1) failed: {}", io::Error::last_os_error());
        }
        let devnull = CString::new("/dev/null").expect("no interior NUL");
        let devnull_fd = libc::open(devnull.as_ptr(), libc::O_WRONLY);
        if devnull_fd < 0 {
            panic!("open(/dev/null) failed: {}", io::Error::last_os_error());
        }
        if libc::dup2(devnull_fd, 1) < 0 {
            panic!("dup2(devnull, 1) failed: {}", io::Error::last_os_error());
        }
        libc::close(devnull_fd);
        File::from_raw_fd(real_stdout_fd)
    }
}

/// Writes one JSON object per line to the private stdout fd, flushing after
/// every frame so the host sees it immediately -- there is no framing
/// beyond the newline, so a buffered-but-unflushed write would just look
/// like a hang to the host.
pub struct FrameWriter {
    out: File,
}

impl FrameWriter {
    pub fn new(out: File) -> Self {
        Self { out }
    }

    pub fn send(&mut self, frame: &OutFrame) {
        let line = serde_json::to_string(frame).expect("frame always serializes");
        self.out
            .write_all(line.as_bytes())
            .expect("write to isolated stdout fd failed");
        self.out
            .write_all(b"\n")
            .expect("write to isolated stdout fd failed");
        self.out.flush().expect("write to isolated stdout fd failed");
    }
}

/// Reads exactly one line from real stdin, skipping blank lines -- mirrors
/// `FrameReader.__next__` in the Python SDK. Returns `None` on EOF (the host
/// closed stdin without sending anything further).
pub fn read_line(stdin: &mut impl std::io::BufRead) -> Option<String> {
    loop {
        let mut line = String::new();
        let n = stdin.read_line(&mut line).expect("read from stdin failed");
        if n == 0 {
            return None;
        }
        let trimmed = line.trim_end_matches(['\n', '\r']);
        if trimmed.trim().is_empty() {
            continue;
        }
        return Some(trimmed.to_string());
    }
}
