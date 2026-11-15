//! What to send the pad, given focus and config. No I/O, so every rule is testable.

use std::collections::BTreeMap;

use crate::config::{Config, Profile, State};
use crate::focus::Focus;
use crate::protocol::{self as proto, Frame};

/// What the pad should be doing for the window in front.
#[derive(Clone, Debug, PartialEq, Eq)]
enum Mode {
    /// A pause app (Vial) is in front: send nothing, the pad falls back to its base layer.
    Paused,
    /// The matched profile, or None for the base layer.
    Profile(Option<Selected>),
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct Selected {
    profile: String,
    /// The profile's sub-state that the app in front reported, if the profile defines it.
    state: Option<String>,
}

pub struct Bridge {
    cfg: Config,
    focus: Focus,
    mode: Mode,
    linked: bool,
    /// What each app last reported it is doing (lowercase app name to state name).
    app_states: BTreeMap<String, String>,
}

impl Bridge {
    pub fn new(cfg: Config) -> Self {
        Bridge { cfg, focus: Focus::default(), mode: Mode::Profile(None), linked: false, app_states: BTreeMap::new() }
    }

    fn mode_for(&self, focus: &Focus) -> Mode {
        if self.cfg.paused(focus) {
            return Mode::Paused;
        }
        Mode::Profile(self.cfg.select(focus).map(|p| Selected {
            profile: p.name.clone(),
            state: self.reported_state(p, focus).map(|s| s.name.clone()),
        }))
    }

    /// The sub-state of `profile` that an app matching the window in front has reported.
    fn reported_state<'a>(&self, profile: &'a Profile, focus: &Focus) -> Option<&'a State> {
        let app = focus.app.to_lowercase();
        self.app_states
            .iter()
            .filter(|(reporter, _)| app.contains(reporter.as_str()))
            .find_map(|(_, name)| profile.state(name))
    }

    fn selected(&self) -> Option<(&Profile, Option<&State>)> {
        let Mode::Profile(Some(sel)) = &self.mode else { return None };
        let profile = self.cfg.profiles.iter().find(|p| p.name == sel.profile)?;
        let state = sel.state.as_deref().and_then(|name| profile.state(name));
        Some((profile, state))
    }

    fn profile_frames(&self) -> Vec<Frame> {
        if !self.linked || self.mode == Mode::Paused {
            return Vec::new();
        }
        let (head, labels) = match self.selected() {
            None => return vec![proto::profile(None, [0, 0, 0], "")],
            Some((p, None)) => (proto::profile(Some(p.layer), p.color, &p.name), &p.labels),
            Some((_, Some(s))) => (proto::profile(Some(s.layer), s.color, &s.name), &s.labels),
        };
        // the firmware clears labels on a new profile, so empty ones need no frame
        let labels = labels.iter().enumerate().filter(|(_, l)| !l.is_empty());
        std::iter::once(head).chain(labels.map(|(i, l)| proto::label(i as u8, l))).collect()
    }

    /// Re-match the window in front; frames only when that changes what the pad shows.
    fn rematch(&mut self) -> Vec<Frame> {
        let mode = self.mode_for(&self.focus);
        if mode == self.mode {
            return Vec::new();
        }
        self.mode = mode;
        self.profile_frames()
    }

    pub fn connected(&mut self) -> Vec<Frame> {
        self.linked = true;
        let mut frames = vec![proto::hello()];
        frames.extend(self.profile_frames());
        frames
    }

    pub fn disconnected(&mut self) {
        self.linked = false;
    }

    pub fn focus(&mut self, focus: Focus) -> Vec<Frame> {
        self.focus = focus;
        self.rematch()
    }

    /// An app reports what it is doing (FreeCAD: its workbench); None clears it. It selects the
    /// profile's sub-state of that name while a window of that app is in front.
    pub fn app_state(&mut self, app: &str, state: Option<String>) -> Result<Vec<Frame>, String> {
        if app.is_empty() {
            return Err("app must not be empty: it would match every window".into());
        }
        let app = app.to_lowercase();
        match state {
            Some(state) => self.app_states.insert(app, state),
            None => self.app_states.remove(&app),
        };
        Ok(self.rematch())
    }

    /// New config: re-match the window in front and resend, so edits show at once.
    pub fn reload(&mut self, cfg: Config) -> Vec<Frame> {
        self.cfg = cfg;
        self.mode = self.mode_for(&self.focus);
        self.profile_frames()
    }

    /// Once a second. Without it the pad drops the profile after 5 s.
    pub fn heartbeat(&self) -> Option<Frame> {
        (self.linked && self.mode != Mode::Paused).then(proto::heartbeat)
    }

    /// Shell command for a HOST(n) key in the window in front.
    pub fn action(&self, n: u8) -> Option<String> {
        if self.mode == Mode::Paused {
            return None;
        }
        self.cfg.action(self.selected().map(|(p, _)| p), n).map(str::to_string)
    }

    pub fn status(&self) -> serde_json::Value {
        let (profile, state) = match &self.mode {
            Mode::Paused => (serde_json::json!("(paused)"), None),
            Mode::Profile(None) => (serde_json::Value::Null, None),
            Mode::Profile(Some(sel)) => (serde_json::json!(sel.profile), sel.state.as_deref()),
        };
        serde_json::json!({
            "linked": self.linked,
            "app": self.focus.app,
            "title": self.focus.title,
            "profile": profile,
            "state": state,
            "app_states": self.app_states,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config;

    const CFG: &str = r##"
        actions = { 0 = "notify-send base" }
        [[profile]]
        name = "FreeCAD"
        apps = ["freecad"]
        layer = 1
        color = "#ff8800"
        labels = ["Iso", "", "Right"]
        actions = { 0 = "notify-send freecad" }
        [[profile.state]]
        name = "Sketcher"
        layer = 4
        labels = ["Line", "Circle"]
        [[profile]]
        name = "Browser"
        apps = ["firefox"]
        layer = 3
        [[profile.state]]
        name = "Reader"
        layer = 5
        color = "#0000ff"
    "##;

    fn sketcher() -> Vec<Frame> {
        vec![proto::profile(Some(4), [0xff, 0x88, 0], "Sketcher"), proto::label(0, "Line"), proto::label(1, "Circle")]
    }

    fn focus(app: &str) -> Focus {
        Focus { app: app.into(), title: String::new() }
    }

    fn linked() -> Bridge {
        let mut b = Bridge::new(config::parse(CFG).unwrap());
        b.connected();
        b
    }

    #[test]
    fn connect_says_hello_then_current_profile() {
        let mut b = Bridge::new(config::parse(CFG).unwrap());
        assert!(b.focus(focus("org.freecad.FreeCAD")).is_empty(), "nothing goes out before the pad is there");
        let frames = b.connected();
        assert_eq!(frames[0], proto::hello());
        assert_eq!(frames[1], proto::profile(Some(1), [0xff, 0x88, 0], "FreeCAD"));
        assert_eq!(&frames[2..], &[proto::label(0, "Iso"), proto::label(2, "Right")]);
    }

    #[test]
    fn focus_change_sends_only_on_profile_change() {
        let mut b = linked();
        assert_eq!(b.focus(focus("FreeCAD")).len(), 3);
        assert!(b.focus(focus("freecad")).is_empty(), "same profile, other window");
        assert_eq!(b.focus(focus("foot")), vec![proto::profile(None, [0, 0, 0], "")]);
        assert!(b.focus(focus("kitty")).is_empty(), "still no profile");
    }

    #[test]
    fn vial_in_front_pauses_everything() {
        let mut b = linked();
        b.focus(focus("FreeCAD"));
        assert!(b.focus(focus("Vial")).is_empty());
        assert_eq!(b.heartbeat(), None);
        assert_eq!(b.action(0), None);
        assert_eq!(b.focus(focus("FreeCAD")).len(), 3, "back from Vial: resend the profile");
        assert_eq!(b.heartbeat(), Some(proto::heartbeat()));
    }

    #[test]
    fn actions_follow_focus() {
        let mut b = linked();
        assert_eq!(b.action(0).as_deref(), Some("notify-send base"));
        b.focus(focus("FreeCAD"));
        assert_eq!(b.action(0).as_deref(), Some("notify-send freecad"));
        assert_eq!(b.action(5), None);
    }

    #[test]
    fn reload_rematches_and_resends() {
        let mut b = linked();
        b.focus(focus("FreeCAD"));
        let recoloured = config::parse(&CFG.replace("#ff8800", "#00ff00")).unwrap();
        let frames = b.reload(recoloured);
        assert_eq!(frames[0], proto::profile(Some(1), [0, 0xff, 0], "FreeCAD"));
        assert_eq!(b.reload(Config::default()), vec![proto::profile(None, [0, 0, 0], "")]);
    }

    #[test]
    fn no_heartbeat_without_pad() {
        let mut b = linked();
        b.disconnected();
        assert_eq!(b.heartbeat(), None);
        assert!(b.focus(focus("FreeCAD")).is_empty());
    }

    #[test]
    fn app_state_switches_and_clears() {
        let mut b = linked();
        b.focus(focus("org.freecad.FreeCAD"));
        assert_eq!(b.app_state("FreeCAD", Some("Sketcher".into())).unwrap(), sketcher(), "colour from the profile");
        assert_eq!(b.status()["state"], "Sketcher");
        assert!(b.app_state("freecad", Some("Sketcher".into())).unwrap().is_empty(), "same state again");
        assert_eq!(b.app_state("freecad", None).unwrap().len(), 3, "cleared: back to the FreeCAD layer");
        assert!(b.app_state("freecad", Some("TechDraw".into())).unwrap().is_empty(), "no such state: profile stays");
        assert_eq!(b.action(0).as_deref(), Some("notify-send freecad"));
    }

    #[test]
    fn app_state_applies_only_while_that_app_is_in_front() {
        let mut b = linked();
        b.focus(focus("firefox"));
        assert!(
            b.app_state("freecad", Some("Reader".into())).unwrap().is_empty(),
            "Browser has Reader; FreeCAD said it"
        );
        assert!(b.app_state("freecad", Some("Sketcher".into())).unwrap().is_empty());
        assert_eq!(b.focus(focus("FreeCAD")), sketcher(), "kept until FreeCAD comes to the front");
        assert!(b.app_state("firefox", Some("Reader".into())).unwrap().is_empty(), "firefox is not in front");
        assert_eq!(b.focus(focus("firefox")), vec![proto::profile(Some(5), [0, 0, 0xff], "Reader")]);
    }

    #[test]
    fn reload_keeps_app_state() {
        let mut b = linked();
        b.focus(focus("FreeCAD"));
        b.app_state("freecad", Some("Sketcher".into())).unwrap();
        let frames = b.reload(config::parse(&CFG.replace("layer = 4", "layer = 6")).unwrap());
        assert_eq!(frames[0], proto::profile(Some(6), [0xff, 0x88, 0], "Sketcher"));
    }

    #[test]
    fn pause_wins_over_app_state() {
        let mut b = linked();
        b.focus(focus("Vial"));
        assert!(b.app_state("vial", Some("Sketcher".into())).unwrap().is_empty());
        assert!(b.app_state("freecad", Some("Sketcher".into())).unwrap().is_empty());
        assert_eq!(b.heartbeat(), None);
        assert_eq!(b.focus(focus("FreeCAD")), sketcher());
    }

    #[test]
    fn app_state_needs_an_app() {
        assert!(linked().app_state("", Some("Sketcher".into())).unwrap_err().contains("every window"));
    }
}
