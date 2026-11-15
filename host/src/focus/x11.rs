//! X11 through x11rb: `_NET_ACTIVE_WINDOW` on the root window names the window in front; its
//! `WM_CLASS` gives the app, `_NET_WM_NAME` (else `WM_NAME`) the title. PropertyNotify on the
//! root reports a new active window, on the active window a new title.

use std::io;

use x11rb::connection::Connection;
use x11rb::errors::ReplyError;
use x11rb::protocol::xproto::{Atom, AtomEnum, ChangeWindowAttributesAux, ConnectionExt, EventMask, Window};
use x11rb::protocol::Event;
use x11rb::rust_connection::RustConnection;

use super::Focus;

x11rb::atom_manager! {
    Atoms: AtomsCookie {
        _NET_ACTIVE_WINDOW,
        _NET_WM_NAME,
    }
}

/// Window properties are short; 1024 x 4 bytes holds any sane title.
const MAX_PROPERTY_WORDS: u32 = 1024;
const NO_WINDOW: Window = 0;

/// What a PropertyNotify means for the focus.
#[derive(Debug, PartialEq, Eq)]
enum Change {
    ActiveWindow,
    Title,
    Other,
}

fn classify(window: Window, atom: Atom, root: Window, active: Window, atoms: &Atoms) -> Change {
    if window == root && atom == atoms._NET_ACTIVE_WINDOW {
        Change::ActiveWindow
    } else if window == active && (atom == atoms._NET_WM_NAME || atom == u32::from(AtomEnum::WM_NAME)) {
        Change::Title
    } else {
        Change::Other
    }
}

/// WM_CLASS holds "instance\0class\0"; the class ("FreeCAD", "firefox") is what profiles match.
fn class_name(wm_class: &[u8]) -> String {
    let mut parts = wm_class.split(|&b| b == 0);
    let instance = parts.next().unwrap_or_default();
    let class = parts.next().filter(|c| !c.is_empty()).unwrap_or(instance);
    String::from_utf8_lossy(class).into_owned()
}

/// The first window id in a `_NET_ACTIVE_WINDOW` value (native-endian 32-bit words).
fn window_id(value: &[u8]) -> Window {
    value.get(..4).map_or(NO_WINDOW, |b| Window::from_ne_bytes([b[0], b[1], b[2], b[3]]))
}

struct Session {
    conn: RustConnection,
    root: Window,
    atoms: Atoms,
    active: Window,
}

impl Session {
    /// A property's bytes; empty when the window is gone, which happens between event and query.
    fn property(&self, window: Window, atom: impl Into<Atom>) -> io::Result<Vec<u8>> {
        let cookie = self
            .conn
            .get_property(false, window, atom, AtomEnum::ANY, 0, MAX_PROPERTY_WORDS)
            .map_err(io::Error::other)?;
        match cookie.reply() {
            Ok(reply) => Ok(reply.value),
            Err(ReplyError::X11Error(_)) => Ok(Vec::new()),
            Err(e @ ReplyError::ConnectionError(_)) => Err(io::Error::other(e)),
        }
    }

    fn listen(&self, window: Window, mask: EventMask) -> io::Result<()> {
        let aux = ChangeWindowAttributesAux::new().event_mask(mask);
        self.conn.change_window_attributes(window, &aux).map_err(io::Error::other)?;
        Ok(())
    }

    fn title(&self) -> io::Result<String> {
        let mut title = self.property(self.active, self.atoms._NET_WM_NAME)?;
        if title.is_empty() {
            title = self.property(self.active, AtomEnum::WM_NAME)?;
        }
        Ok(String::from_utf8_lossy(&title).into_owned())
    }

    fn focus(&self) -> io::Result<Focus> {
        if self.active == NO_WINDOW {
            return Ok(Focus::default());
        }
        Ok(Focus { app: class_name(&self.property(self.active, AtomEnum::WM_CLASS)?), title: self.title()? })
    }

    /// Re-read the active window and follow its title changes instead of the old one's.
    fn update_active(&mut self) -> io::Result<()> {
        let active = window_id(&self.property(self.root, self.atoms._NET_ACTIVE_WINDOW)?);
        if active == self.active {
            return Ok(());
        }
        if self.active != NO_WINDOW {
            self.listen(self.active, EventMask::NO_EVENT)?;
        }
        if active != NO_WINDOW {
            self.listen(active, EventMask::PROPERTY_CHANGE)?;
        }
        self.active = active;
        self.conn.flush().map_err(io::Error::other)
    }
}

pub fn watch(display: &str, mut on_focus: impl FnMut(Focus)) -> io::Result<()> {
    let (conn, screen) = x11rb::connect(Some(display)).map_err(io::Error::other)?;
    let root = conn.setup().roots[screen].root;
    let atoms = Atoms::new(&conn).map_err(io::Error::other)?.reply().map_err(io::Error::other)?;
    let mut session = Session { conn, root, atoms, active: NO_WINDOW };
    session.listen(root, EventMask::PROPERTY_CHANGE)?;
    session.update_active()?;
    on_focus(session.focus()?);
    loop {
        // errors for windows that vanished arrive as events too; only PropertyNotify matters
        let Event::PropertyNotify(e) = session.conn.wait_for_event().map_err(io::Error::other)? else { continue };
        match classify(e.window, e.atom, session.root, session.active, &session.atoms) {
            Change::ActiveWindow => {
                let before = session.active;
                session.update_active()?;
                if session.active != before {
                    on_focus(session.focus()?);
                }
            }
            Change::Title => on_focus(session.focus()?),
            Change::Other => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const ROOT: Window = 0x3a5;
    const ACTIVE: Window = 0x0140_0007;
    const ATOMS: Atoms = Atoms { _NET_ACTIVE_WINDOW: 330, _NET_WM_NAME: 331 };

    #[test]
    fn classifies_property_changes() {
        let classify = |window, atom| classify(window, atom, ROOT, ACTIVE, &ATOMS);
        assert_eq!(classify(ROOT, ATOMS._NET_ACTIVE_WINDOW), Change::ActiveWindow);
        assert_eq!(classify(ACTIVE, ATOMS._NET_WM_NAME), Change::Title);
        assert_eq!(classify(ACTIVE, AtomEnum::WM_NAME.into()), Change::Title);
        assert_eq!(classify(ROOT, ATOMS._NET_WM_NAME), Change::Other, "the root's own name");
        assert_eq!(classify(0x0160_0003, ATOMS._NET_WM_NAME), Change::Other, "a window in the background");
        assert_eq!(classify(ACTIVE, AtomEnum::WM_CLASS.into()), Change::Other);
    }

    #[test]
    fn reads_class_from_wm_class() {
        // Captured under XWayland (sway) with `xprop -f WM_CLASS 8x WM_CLASS` on Bambu Studio:
        // WM_CLASS(STRING) = "bambu-studio", "BambuStudio"
        assert_eq!(class_name(b"bambu-studio\0BambuStudio\0"), "BambuStudio");
        // guesses, not captured: the same instance\0class\0 layout for FreeCAD and Firefox
        assert_eq!(class_name(b"FreeCAD\0FreeCAD\0"), "FreeCAD");
        assert_eq!(class_name(b"Navigator\0firefox\0"), "firefox");
        assert_eq!(class_name(b"xterm\0"), "xterm", "no class part: fall back to the instance");
        assert_eq!(class_name(b""), "");
    }

    #[test]
    fn reads_active_window_id() {
        assert_eq!(window_id(&ACTIVE.to_ne_bytes()), ACTIVE);
        assert_eq!(window_id(&[0, 0, 0, 0]), NO_WINDOW);
        assert_eq!(window_id(&[]), NO_WINDOW, "property not set");
    }
}
