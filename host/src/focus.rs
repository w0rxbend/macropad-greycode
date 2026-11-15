//! Which window has focus. One backend per session type, picked from the environment:
//! sway ($SWAYSOCK), Hyprland ($HYPRLAND_INSTANCE_SIGNATURE), then X11 ($DISPLAY).
//! shortcut: no KDE or GNOME Wayland backend; add one when someone needs it. There, X11 runs on
//! XWayland and greyd warns that native Wayland windows stay invisible.

mod hyprland;
mod sway;
mod x11;

use std::fmt;
use std::io;
use std::path::PathBuf;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Focus {
    /// Wayland app_id, or the X11 class for X11 and XWayland windows.
    pub app: String,
    pub title: String,
}

/// Where focus comes from in this session.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Backend {
    /// sway's IPC socket path.
    Sway(String),
    /// The Hyprland instance's socket directory.
    Hyprland(PathBuf),
    /// The X11 display name; `under_wayland` when it is XWayland of a compositor greyd cannot ask.
    X11 { display: String, under_wayland: bool },
}

impl Backend {
    /// The first backend whose variable `var` returns. sway and Hyprland come before X11 because
    /// both also set DISPLAY for XWayland, which sees only X11 windows.
    pub fn from_env(var: impl Fn(&str) -> Option<String>) -> Option<Backend> {
        let set = |name: &str| var(name).filter(|v| !v.is_empty());
        if let Some(socket) = set("SWAYSOCK") {
            return Some(Backend::Sway(socket));
        }
        if let (Some(runtime), Some(instance)) = (set("XDG_RUNTIME_DIR"), set("HYPRLAND_INSTANCE_SIGNATURE")) {
            return Some(Backend::Hyprland(PathBuf::from(runtime).join("hypr").join(instance)));
        }
        let under_wayland = set("WAYLAND_DISPLAY").is_some();
        set("DISPLAY").map(|display| Backend::X11 { display, under_wayland })
    }

    /// What the user should know about this backend's blind spots, if anything.
    pub fn warning(&self) -> Option<&'static str> {
        match self {
            Backend::X11 { under_wayland: true, .. } => Some(
                "WAYLAND_DISPLAY is set but greyd has no backend for this compositor: \
                 profiles follow X11 (XWayland) windows only, not native Wayland ones",
            ),
            _ => None,
        }
    }

    /// Call `on_focus` with the current focus, then on every change, until the connection ends.
    pub fn watch(&self, on_focus: impl FnMut(Focus)) -> io::Result<()> {
        match self {
            Backend::Sway(socket) => sway::watch(socket, on_focus),
            Backend::Hyprland(dir) => hyprland::watch(dir, on_focus),
            Backend::X11 { display, .. } => x11::watch(display, on_focus),
        }
    }
}

impl fmt::Display for Backend {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Backend::Sway(socket) => write!(f, "sway ({socket})"),
            Backend::Hyprland(dir) => write!(f, "Hyprland ({})", dir.display()),
            Backend::X11 { display, .. } => write!(f, "X11 (DISPLAY={display})"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn backend(vars: &[(&str, &str)]) -> Option<Backend> {
        Backend::from_env(|name| vars.iter().find(|(k, _)| *k == name).map(|(_, v)| v.to_string()))
    }

    fn x11(display: &str, under_wayland: bool) -> Option<Backend> {
        Some(Backend::X11 { display: display.into(), under_wayland })
    }

    #[test]
    fn picks_backend_from_environment() {
        let sway = [("SWAYSOCK", "/run/user/1000/sway-ipc.sock"), ("DISPLAY", ":0"), ("WAYLAND_DISPLAY", "wayland-1")];
        assert_eq!(backend(&sway), Some(Backend::Sway("/run/user/1000/sway-ipc.sock".into())));
        let hypr = [("XDG_RUNTIME_DIR", "/run/user/1000"), ("HYPRLAND_INSTANCE_SIGNATURE", "abc_1"), ("DISPLAY", ":1")];
        assert_eq!(backend(&hypr), Some(Backend::Hyprland("/run/user/1000/hypr/abc_1".into())));
        assert_eq!(backend(&[("DISPLAY", ":0")]), x11(":0", false));
    }

    #[test]
    fn warns_only_for_xwayland_without_compositor_backend() {
        let gnome = [("DISPLAY", ":0"), ("WAYLAND_DISPLAY", "wayland-0")];
        assert_eq!(backend(&gnome), x11(":0", true));
        assert!(backend(&gnome).unwrap().warning().is_some());
        assert_eq!(backend(&[("DISPLAY", ":0"), ("WAYLAND_DISPLAY", "")]).unwrap().warning(), None);
        let sway = [("SWAYSOCK", "/run/user/1000/sway-ipc.sock"), ("WAYLAND_DISPLAY", "wayland-1")];
        assert_eq!(backend(&sway).unwrap().warning(), None);
    }

    #[test]
    fn empty_or_missing_variables_are_unset() {
        assert_eq!(backend(&[("SWAYSOCK", ""), ("DISPLAY", ":0")]), x11(":0", false));
        assert_eq!(backend(&[("HYPRLAND_INSTANCE_SIGNATURE", "abc")]), None, "no XDG_RUNTIME_DIR, no socket dir");
        assert_eq!(backend(&[]), None);
    }
}
