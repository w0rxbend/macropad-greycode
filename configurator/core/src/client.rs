//! greyd's control socket: one JSON request line out, one JSON reply line back (host/src/control.rs).

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

/// greyd answers from its main loop, which ticks every second.
const TIMEOUT: Duration = Duration::from_secs(2);

/// What the app shows about greyd and the pad. `error` says why greyd did not answer.
#[derive(Debug, Default, Serialize, PartialEq)]
pub struct Link {
    pub greyd: bool,
    /// greyd has the pad's HID device open.
    pub pad: bool,
    /// The pad answered greyd's HELLO.
    pub linked: bool,
    pub app: String,
    pub title: String,
    pub profile: Option<String>,
    pub error: Option<String>,
}

#[derive(Deserialize)]
struct Reply {
    ok: bool,
    #[serde(default)]
    error: Option<String>,
    status: Option<StatusReply>,
}

#[derive(Deserialize)]
struct StatusReply {
    linked: bool,
    app: String,
    title: String,
    profile: Option<String>,
    device: Option<String>,
}

pub fn status(socket: &Path) -> Link {
    let reply =
        call(socket, &json!({"cmd": "status"})).and_then(|r| r.status.ok_or_else(|| "reply has no status".into()));
    match reply {
        Ok(s) => Link {
            greyd: true,
            pad: s.device.is_some(),
            linked: s.linked,
            app: s.app,
            title: s.title,
            profile: s.profile,
            error: None,
        },
        Err(e) => Link { error: Some(e), ..Link::default() },
    }
}

/// Raise an alert on the pad; greyd checks the level and refuses when the pad is not connected.
pub fn alert(socket: &Path, level: &str, text: &str, timeout_s: u16) -> Result<(), String> {
    call(socket, &json!({"cmd": "alert", "level": level, "text": text, "timeout": timeout_s})).map(drop)
}

fn call(socket: &Path, request: &Value) -> Result<Reply, String> {
    let at = |e: std::io::Error| format!("{}: {e}", socket.display());
    let mut stream = UnixStream::connect(socket).map_err(|e| format!("greyd is not running ({})", at(e)))?;
    stream.set_read_timeout(Some(TIMEOUT)).map_err(at)?;
    stream.set_write_timeout(Some(TIMEOUT)).map_err(at)?;
    writeln!(stream, "{request}").map_err(at)?;
    let mut line = String::new();
    BufReader::new(stream).read_line(&mut line).map_err(at)?;
    let reply: Reply = serde_json::from_str(&line).map_err(|e| format!("greyd sent {:?}: {e}", line.trim_end()))?;
    if !reply.ok {
        return Err(reply.error.unwrap_or_else(|| "greyd refused the request".into()));
    }
    Ok(reply)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scratch;
    use std::os::unix::net::UnixListener;
    use std::path::PathBuf;
    use std::thread::{self, JoinHandle};

    /// A one-shot greyd: checks the request line, answers `reply`.
    fn fake_greyd(name: &str, expect: Value, reply: &'static str) -> (PathBuf, JoinHandle<()>) {
        let dir = scratch(name);
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("greyd.sock");
        let listener = UnixListener::bind(&path).unwrap();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut line = String::new();
            BufReader::new(&stream).read_line(&mut line).unwrap();
            assert_eq!(serde_json::from_str::<Value>(&line).unwrap(), expect);
            writeln!(stream, "{reply}").unwrap();
        });
        (path, server)
    }

    #[test]
    fn status_reports_app_and_pad() {
        let reply = r#"{"ok":true,"status":{"linked":true,"app":"org.freecad.FreeCAD","title":"Part","profile":"FreeCAD","device":"/dev/hidraw3"}}"#;
        let (path, server) = fake_greyd("status", json!({"cmd": "status"}), reply);
        let link = status(&path);
        server.join().unwrap();
        assert_eq!(
            link,
            Link {
                greyd: true,
                pad: true,
                linked: true,
                app: "org.freecad.FreeCAD".into(),
                title: "Part".into(),
                profile: Some("FreeCAD".into()),
                error: None
            }
        );
    }

    #[test]
    fn status_without_pad_or_profile() {
        let reply = r#"{"ok":true,"status":{"linked":false,"app":"foot","title":"zsh","profile":null,"device":null}}"#;
        let (path, server) = fake_greyd("nopad", json!({"cmd": "status"}), reply);
        let link = status(&path);
        server.join().unwrap();
        assert!(link.greyd && !link.pad && link.profile.is_none());
    }

    #[test]
    fn greyd_not_running() {
        let link = status(&scratch("down").join("greyd.sock"));
        assert!(!link.greyd);
        assert!(link.error.unwrap().contains("greyd is not running"));
    }

    #[test]
    fn alert_sends_the_request_and_passes_refusals_on() {
        let expect = json!({"cmd": "alert", "level": "warn", "text": "Test", "timeout": 5});
        let (path, server) = fake_greyd("alert", expect, r#"{"ok":false,"error":"the pad is not connected"}"#);
        let result = alert(&path, "warn", "Test", 5);
        server.join().unwrap();
        assert_eq!(result.unwrap_err(), "the pad is not connected");
    }

    #[test]
    fn malformed_reply_is_an_error() {
        let (path, server) = fake_greyd("garbage", json!({"cmd": "status"}), "hello");
        let link = status(&path);
        server.join().unwrap();
        assert!(link.error.unwrap().contains("greyd sent \"hello\""));
    }
}
