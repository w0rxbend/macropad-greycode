//! The control socket: one JSON request per line in, one JSON reply per line out.
//! greyctl, scripts and (later) the configurator use it to raise alerts and colour keys.

use std::io::{self, BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;

use serde::Deserialize;

use crate::protocol::{self as proto, parse_rgb, Alert, Frame, Level, Pattern, KEYS};

#[derive(Debug, Deserialize, PartialEq)]
#[serde(tag = "cmd", rename_all = "lowercase", deny_unknown_fields)]
pub enum Request {
    Alert {
        level: Level,
        #[serde(default)]
        text: String,
        #[serde(default)]
        timeout: u16,
        color: Option<String>,
        pattern: Option<Pattern>,
    },
    Clear,
    /// Colour `keys` (0-8, row by row); no colour gives them back to the RGB effect.
    Keys {
        keys: Vec<u8>,
        color: Option<String>,
    },
    /// `app` says what it is doing (FreeCAD: "Sketcher"); no `state` clears it.
    State {
        app: String,
        #[serde(default)]
        state: Option<String>,
    },
    Status,
}

pub fn socket_path() -> PathBuf {
    match std::env::var_os("XDG_RUNTIME_DIR") {
        Some(dir) => PathBuf::from(dir).join("greyd.sock"),
        None => std::env::temp_dir().join(format!("greyd-{}.sock", std::env::var("USER").unwrap_or_default())),
    }
}

/// The frame for a request that goes to the pad; None for Status and State, which the bridge answers.
pub fn frame_for(req: &Request) -> Result<Option<Frame>, String> {
    let color = |c: &Option<String>| c.as_deref().map(parse_rgb).transpose();
    Ok(Some(match req {
        Request::Alert { level, text, timeout, color: c, pattern } => proto::alert(&Alert {
            level: *level,
            // an error should be noticed from across the room
            pattern: pattern.unwrap_or(if *level == Level::Error { Pattern::Blink } else { Pattern::Solid }),
            color: color(c)?,
            timeout_s: *timeout,
            text: text.clone(),
        }),
        Request::Clear => proto::alert(&Alert {
            level: Level::Clear,
            pattern: Pattern::Solid,
            color: None,
            timeout_s: 0,
            text: String::new(),
        }),
        Request::Keys { keys, color: c } => {
            if let Some(k) = keys.iter().find(|&&k| k as usize >= KEYS) {
                return Err(format!("key {k} is not 0-{}", KEYS - 1));
            }
            proto::key_leds(keys.iter().fold(0u16, |m, &k| m | 1 << k), color(c)?)
        }
        Request::Status | Request::State { .. } => return Ok(None),
    }))
}

/// Send one request line to greyd and return its reply line.
pub fn call(request: &serde_json::Value) -> io::Result<serde_json::Value> {
    let path = socket_path();
    let mut stream = UnixStream::connect(&path)
        .map_err(|e| io::Error::new(e.kind(), format!("{}: {e} (is greyd running?)", path.display())))?;
    writeln!(stream, "{request}")?;
    let mut line = String::new();
    BufReader::new(stream).read_line(&mut line)?;
    Ok(serde_json::from_str(&line)?)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn req(json: &str) -> Request {
        serde_json::from_str(json).unwrap()
    }

    #[test]
    fn alert_defaults() {
        let f = frame_for(&req(r#"{"cmd":"alert","level":"error","text":"CI red"}"#)).unwrap().unwrap();
        assert_eq!((f[2], f[3]), (Level::Error as u8, Pattern::Blink as u8));
        let f = frame_for(&req(r##"{"cmd":"alert","level":"info","color":"#0000ff","timeout":3}"##)).unwrap().unwrap();
        assert_eq!((f[3], &f[4..7], f[7]), (Pattern::Solid as u8, &[0u8, 0, 0xff][..], 3));
    }

    #[test]
    fn keys_mask_and_bounds() {
        let f = frame_for(&req(r##"{"cmd":"keys","keys":[0,8],"color":"#ff0000"}"##)).unwrap().unwrap();
        assert_eq!(f, proto::key_leds(0x101, Some([0xff, 0, 0])));
        assert!(frame_for(&req(r#"{"cmd":"keys","keys":[9]}"#)).unwrap_err().contains("not 0-8"));
        assert!(frame_for(&req(r##"{"cmd":"keys","keys":[1],"color":"red"}"##)).is_err());
    }

    #[test]
    fn state_requests() {
        let set = req(r#"{"cmd":"state","app":"freecad","state":"Sketcher"}"#);
        assert_eq!(set, Request::State { app: "freecad".into(), state: Some("Sketcher".into()) });
        let cleared = Request::State { app: "freecad".into(), state: None };
        assert_eq!(req(r#"{"cmd":"state","app":"freecad","state":null}"#), cleared);
        assert_eq!(req(r#"{"cmd":"state","app":"freecad"}"#), cleared);
        assert!(serde_json::from_str::<Request>(r#"{"cmd":"state","state":"Sketcher"}"#).is_err(), "no app");
        assert_eq!(frame_for(&set).unwrap(), None);
    }

    #[test]
    fn rejects_unknown_requests() {
        assert!(serde_json::from_str::<Request>(r#"{"cmd":"reboot"}"#).is_err());
        assert_eq!(frame_for(&Request::Status).unwrap(), None);
    }
}
