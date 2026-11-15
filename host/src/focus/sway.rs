//! sway (and i3) IPC: a GET_TREE query, then window events on a second connection.

use std::io::{self, Read, Write};
use std::os::unix::net::UnixStream;

use serde_json::Value;

use super::Focus;

const MAGIC: &[u8] = b"i3-ipc";
const SUBSCRIBE: u32 = 2;
const GET_TREE: u32 = 4;
const WINDOW_EVENT: u32 = 0x8000_0003;

fn send(stream: &mut UnixStream, kind: u32, payload: &[u8]) -> io::Result<()> {
    let len = u32::try_from(payload.len()).map_err(|_| io::Error::other("IPC payload too long"))?;
    let mut msg = MAGIC.to_vec();
    msg.extend_from_slice(&len.to_ne_bytes());
    msg.extend_from_slice(&kind.to_ne_bytes());
    msg.extend_from_slice(payload);
    stream.write_all(&msg)
}

fn recv(stream: &mut impl Read) -> io::Result<(u32, Value)> {
    let mut head = [0u8; 14];
    stream.read_exact(&mut head)?;
    if &head[..6] != MAGIC {
        return Err(io::Error::other("not an i3-ipc message"));
    }
    let len = u32::from_ne_bytes(head[6..10].try_into().unwrap()) as usize;
    let kind = u32::from_ne_bytes(head[10..14].try_into().unwrap());
    let mut body = vec![0u8; len];
    stream.read_exact(&mut body)?;
    Ok((kind, serde_json::from_slice(&body)?))
}

fn node_focus(node: &Value) -> Focus {
    let text = |v: &Value| v.as_str().unwrap_or_default().to_string();
    let app = match node["app_id"].as_str() {
        Some(id) if !id.is_empty() => id.to_string(),
        _ => text(&node["window_properties"]["class"]),
    };
    Focus { app, title: text(&node["name"]) }
}

/// The focused window in a GET_TREE reply.
fn focused_in_tree(node: &Value) -> Option<Focus> {
    if node["focused"].as_bool() == Some(true) && node["type"] != "workspace" && node["type"] != "output" {
        return Some(node_focus(node));
    }
    ["nodes", "floating_nodes"].iter().filter_map(|k| node[*k].as_array()).flatten().find_map(focused_in_tree)
}

/// A window event that changes what has focus: a new focus, or the focused window's new title.
fn focus_from_event(event: &Value) -> Option<Focus> {
    let container = &event["container"];
    match event["change"].as_str()? {
        "focus" => Some(node_focus(container)),
        "title" if container["focused"].as_bool() == Some(true) => Some(node_focus(container)),
        _ => None,
    }
}

/// Call `on_focus` with the current focus, then on every change, until the socket closes.
pub fn watch(socket: &str, mut on_focus: impl FnMut(Focus)) -> io::Result<()> {
    let mut query = UnixStream::connect(socket)?;
    send(&mut query, GET_TREE, b"")?;
    let (_, tree) = recv(&mut query)?;
    if let Some(f) = focused_in_tree(&tree) {
        on_focus(f);
    }
    let mut events = UnixStream::connect(socket)?;
    send(&mut events, SUBSCRIBE, br#"["window"]"#)?;
    let (_, ack) = recv(&mut events)?;
    if ack["success"] != true {
        return Err(io::Error::other("sway refused the window subscription"));
    }
    loop {
        let (kind, event) = recv(&mut events)?;
        if let Some(f) = (kind == WINDOW_EVENT).then(|| focus_from_event(&event)).flatten() {
            on_focus(f);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn finds_focused_window_in_tree() {
        let tree = json!({"type": "root", "nodes": [{"type": "output", "nodes": [{"type": "workspace",
            "nodes": [{"type": "con", "focused": false, "app_id": "foot", "name": "zsh"}],
            "floating_nodes": [{"type": "con", "focused": true, "app_id": null, "name": "Part - FreeCAD",
                "window_properties": {"class": "FreeCAD"}}]}]}]});
        assert_eq!(focused_in_tree(&tree), Some(Focus { app: "FreeCAD".into(), title: "Part - FreeCAD".into() }));
    }

    #[test]
    fn empty_workspace_has_no_window_focus() {
        let tree = json!({"type": "root", "nodes": [{"type": "workspace", "focused": true, "nodes": []}]});
        assert_eq!(focused_in_tree(&tree), None);
    }

    #[test]
    fn window_events() {
        let focus = json!({"change": "focus", "container": {"app_id": "org.kicad.pcbnew", "name": "board"}});
        assert_eq!(focus_from_event(&focus).unwrap().app, "org.kicad.pcbnew");
        let title = json!({"change": "title", "container": {"focused": true, "app_id": "firefox", "name": "new"}});
        assert_eq!(focus_from_event(&title).unwrap().title, "new");
        let background = json!({"change": "title", "container": {"focused": false, "app_id": "x", "name": "y"}});
        assert_eq!(focus_from_event(&background), None);
        assert_eq!(focus_from_event(&json!({"change": "move", "container": {}})), None);
    }

    #[test]
    fn reads_ipc_frames() {
        let mut msg = MAGIC.to_vec();
        let body = br#"{"success":true}"#;
        msg.extend_from_slice(&(body.len() as u32).to_ne_bytes());
        msg.extend_from_slice(&SUBSCRIBE.to_ne_bytes());
        msg.extend_from_slice(body);
        let (kind, v) = recv(&mut msg.as_slice()).unwrap();
        assert_eq!((kind, v["success"].as_bool()), (SUBSCRIBE, Some(true)));
        assert!(recv(&mut &b"garbage-header"[..]).is_err());
    }
}
