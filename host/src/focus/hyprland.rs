//! Hyprland IPC: `j/activewindow` on .socket.sock for the window in front at start, then
//! `activewindow>>class,title` lines on .socket2.sock. Hyprland repeats that event when the
//! focused window changes its title, so no other event is needed.
//! Titles come from any client and need not be UTF-8: bytes are decoded lossily, like X11 does.

use std::io::{self, BufRead, BufReader, Read, Write};
use std::os::unix::net::UnixStream;
use std::path::Path;

use serde_json::Value;

use super::Focus;

const QUERY_SOCKET: &str = ".socket.sock";
const EVENT_SOCKET: &str = ".socket2.sock";
const ACTIVE_WINDOW_EVENT: &str = "activewindow>>";

/// The reply to `j/activewindow`: a window object, or `{}` when no window has focus.
fn focus_from_query(reply: &str) -> io::Result<Focus> {
    let window: Value = serde_json::from_str(reply)?;
    let text = |key: &str| window[key].as_str().unwrap_or_default().to_string();
    Ok(Focus { app: text("class"), title: text("title") })
}

/// The focus an event line announces; None for every other event. The class has no comma,
/// the title may: split at the first one. `activewindow>>,` means nothing has focus.
fn focus_from_event(line: &str) -> Option<Focus> {
    let (app, title) = line.strip_prefix(ACTIVE_WINDOW_EVENT)?.split_once(',')?;
    Some(Focus { app: app.to_string(), title: title.to_string() })
}

/// Send `j/activewindow` and read the reply up to EOF; Hyprland closes the socket after it.
fn query_focus(mut socket: impl Read + Write) -> io::Result<Focus> {
    socket.write_all(b"j/activewindow")?;
    let mut reply = Vec::new();
    socket.read_to_end(&mut reply)?;
    focus_from_query(&String::from_utf8_lossy(&reply))
}

/// Call `on_focus` for each activewindow line until the stream ends.
fn forward_events(mut events: impl BufRead, on_focus: &mut impl FnMut(Focus)) -> io::Result<()> {
    let mut line = Vec::new();
    while events.read_until(b'\n', &mut line)? > 0 {
        let text = String::from_utf8_lossy(&line);
        if let Some(focus) = focus_from_event(text.trim_end_matches('\n')) {
            on_focus(focus);
        }
        line.clear();
    }
    Ok(())
}

pub fn watch(dir: &Path, mut on_focus: impl FnMut(Focus)) -> io::Result<()> {
    // subscribe before the query, so a focus change between the two is not lost
    let events = UnixStream::connect(dir.join(EVENT_SOCKET))?;
    on_focus(query_focus(UnixStream::connect(dir.join(QUERY_SOCKET))?)?);
    forward_events(BufReader::new(events), &mut on_focus)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn focus(app: &str, title: &str) -> Focus {
        Focus { app: app.into(), title: title.into() }
    }

    // Samples follow the formats on the Hyprland wiki (IPC page); not captured from a running Hyprland.
    const QUERY_REPLY: &str = r#"{
        "address": "0x5f1c2a3b4c50", "mapped": true, "hidden": false, "at": [10, 50], "size": [1900, 1020],
        "workspace": {"id": 1, "name": "1"}, "floating": false, "monitor": 0,
        "class": "org.freecad.FreeCAD", "title": "Unnamed - FreeCAD 1.0.2",
        "initialClass": "org.freecad.FreeCAD", "initialTitle": "FreeCAD", "pid": 4242, "xwayland": false
    }"#;

    #[test]
    fn parses_activewindow_query() {
        assert_eq!(focus_from_query(QUERY_REPLY).unwrap(), focus("org.freecad.FreeCAD", "Unnamed - FreeCAD 1.0.2"));
        assert_eq!(focus_from_query("{}").unwrap(), Focus::default(), "empty workspace");
        assert!(focus_from_query("unknown request").is_err());
    }

    #[test]
    fn parses_activewindow_events() {
        let event = |line| focus_from_event(line);
        assert_eq!(event("activewindow>>kitty,~/src"), Some(focus("kitty", "~/src")));
        assert_eq!(
            event("activewindow>>firefox,Plan, draft 2 — Mozilla Firefox"),
            Some(focus("firefox", "Plan, draft 2 — Mozilla Firefox"))
        );
        assert_eq!(event("activewindow>>,"), Some(Focus::default()), "nothing focused");
    }

    #[test]
    fn survives_titles_that_are_not_utf8() {
        // an XWayland window with a Latin-1 WM_NAME: "café" as 0xe9
        let stream: &[u8] = b"activewindow>>xterm,caf\xe9\nworkspace>>2\nactivewindow>>org.freecad.FreeCAD,ok\n";
        let mut seen = Vec::new();
        forward_events(stream, &mut |f| seen.push(f)).unwrap();
        assert_eq!(seen, [focus("xterm", "caf\u{fffd}"), focus("org.freecad.FreeCAD", "ok")]);
    }

    #[test]
    fn last_event_needs_no_newline() {
        let mut seen = Vec::new();
        forward_events(&b"activewindow>>kitty,~"[..], &mut |f| seen.push(f)).unwrap();
        assert_eq!(seen, [focus("kitty", "~")]);
    }

    #[test]
    fn query_sends_request_and_reads_lossy_reply() {
        struct Fake {
            sent: Vec<u8>,
            reply: &'static [u8],
        }
        impl Read for Fake {
            fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
                self.reply.read(buf)
            }
        }
        impl Write for Fake {
            fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
                self.sent.write(buf)
            }
            fn flush(&mut self) -> io::Result<()> {
                Ok(())
            }
        }
        let mut fake = Fake { sent: Vec::new(), reply: b"{\"class\": \"xterm\", \"title\": \"caf\xe9\"}" };
        assert_eq!(query_focus(&mut fake).unwrap(), focus("xterm", "caf\u{fffd}"));
        assert_eq!(fake.sent, b"j/activewindow");
    }

    #[test]
    fn ignores_other_events() {
        for line in
            ["activewindowv2>>5f1c2a3b4c50", "workspace>>2", "windowtitle>>5f1c2a3b4c50", "openwindow>>a,1,b,c", ""]
        {
            assert_eq!(focus_from_event(line), None, "{line}");
        }
    }
}
