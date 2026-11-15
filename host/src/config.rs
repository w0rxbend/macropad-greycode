//! ~/.config/greycode/config.toml: which app selects which layer, its colour, labels and host actions.
//! greyd re-reads it when it changes, so edits apply without a restart.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use serde::Deserialize;

use crate::focus::Focus;
use crate::protocol::{parse_rgb, Rgb, KEYS};

/// Layers 1-14 hold app profiles; 0 is the base layer and 15 the FN layer.
const PROFILE_LAYERS: std::ops::RangeInclusive<u8> = 1..=14;
/// HOST_0 .. HOST_7 in the firmware.
const HOST_ACTIONS: u8 = 8;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawConfig {
    #[serde(default = "default_pause")]
    pause_apps: Vec<String>,
    #[serde(default)]
    actions: BTreeMap<String, String>,
    #[serde(default, rename = "profile")]
    profiles: Vec<RawProfile>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawProfile {
    name: String,
    apps: Vec<String>,
    #[serde(default)]
    titles: Vec<String>,
    layer: u8,
    #[serde(default = "default_color")]
    color: String,
    #[serde(default)]
    labels: Vec<String>,
    #[serde(default)]
    actions: BTreeMap<String, String>,
    #[serde(default, rename = "state")]
    states: Vec<RawState>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawState {
    name: String,
    layer: u8,
    color: Option<String>,
    #[serde(default)]
    labels: Vec<String>,
}

fn default_pause() -> Vec<String> {
    vec!["vial".into()] // Vial shares the HID interface; stay quiet while it is in front
}

fn default_color() -> String {
    "#ffffff".into()
}

#[derive(Debug, Clone, PartialEq)]
pub struct Profile {
    pub name: String,
    apps: Vec<String>,
    titles: Vec<String>,
    pub layer: u8,
    pub color: Rgb,
    pub labels: Vec<String>,
    actions: BTreeMap<u8, String>,
    pub states: Vec<State>,
}

/// A sub-state of a profile: what the pad shows while the app in front reports it (greyctl state).
#[derive(Debug, Clone, PartialEq)]
pub struct State {
    pub name: String,
    pub layer: u8,
    pub color: Rgb,
    pub labels: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct Config {
    pause_apps: Vec<String>,
    actions: BTreeMap<u8, String>,
    pub profiles: Vec<Profile>,
}

pub fn default_path() -> PathBuf {
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))
        .unwrap_or_else(|| PathBuf::from("."));
    base.join("greycode/config.toml")
}

pub fn load(path: &Path) -> Result<Config, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    parse(&text).map_err(|e| format!("{}: {e}", path.display()))
}

pub fn parse(text: &str) -> Result<Config, String> {
    let raw: RawConfig = toml::from_str(text).map_err(|e| e.to_string())?;
    let profiles = raw.profiles.into_iter().map(profile).collect::<Result<Vec<_>, _>>()?;
    Ok(Config { pause_apps: lower(raw.pause_apps), actions: actions(raw.actions)?, profiles })
}

fn profile(raw: RawProfile) -> Result<Profile, String> {
    let at = |e: String| format!("profile {:?}: {e}", raw.name);
    check_layer_and_labels(raw.layer, &raw.labels).map_err(at)?;
    if raw.apps.is_empty() && raw.titles.is_empty() {
        return Err(at("needs `apps` or `titles` to match".into()));
    }
    let color = parse_rgb(&raw.color).map_err(at)?;
    let states = raw.states.into_iter().map(|s| state(s, color)).collect::<Result<Vec<_>, _>>().map_err(at)?;
    let mut seen = BTreeSet::new();
    if let Some(dup) = states.iter().find(|s| !seen.insert(s.name.as_str())) {
        return Err(at(format!("state {:?} is defined twice", dup.name)));
    }
    Ok(Profile {
        color,
        actions: actions(raw.actions).map_err(at)?,
        name: raw.name,
        apps: lower(raw.apps),
        titles: lower(raw.titles),
        layer: raw.layer,
        labels: raw.labels,
        states,
    })
}

/// A state without `color` keeps its profile's.
fn state(raw: RawState, profile_color: Rgb) -> Result<State, String> {
    let at = |e: String| format!("state {:?}: {e}", raw.name);
    if raw.name.is_empty() {
        return Err("a state needs a name".into());
    }
    check_layer_and_labels(raw.layer, &raw.labels).map_err(at)?;
    let color = raw.color.as_deref().map_or(Ok(profile_color), parse_rgb).map_err(at)?;
    Ok(State { color, name: raw.name, layer: raw.layer, labels: raw.labels })
}

fn check_layer_and_labels(layer: u8, labels: &[String]) -> Result<(), String> {
    if !PROFILE_LAYERS.contains(&layer) {
        return Err(format!("layer {layer} is outside 1-14"));
    }
    if labels.len() > KEYS {
        return Err(format!("{} labels for {KEYS} keys", labels.len()));
    }
    Ok(())
}

fn lower(v: Vec<String>) -> Vec<String> {
    v.into_iter().map(|s| s.to_lowercase()).collect()
}

fn actions(raw: BTreeMap<String, String>) -> Result<BTreeMap<u8, String>, String> {
    raw.into_iter()
        .map(|(k, cmd)| match k.parse::<u8>() {
            Ok(n) if n < HOST_ACTIONS => Ok((n, cmd)),
            _ => Err(format!("action key {k:?} is not 0-{}", HOST_ACTIONS - 1)),
        })
        .collect()
}

fn any_in(patterns: &[String], haystack: &str) -> bool {
    let haystack = haystack.to_lowercase();
    patterns.iter().any(|p| haystack.contains(p.as_str()))
}

impl Profile {
    pub fn state(&self, name: &str) -> Option<&State> {
        self.states.iter().find(|s| s.name == name)
    }
}

impl Config {
    /// First profile whose `apps` is part of the app id / class, or whose `titles` is part of the title.
    pub fn select(&self, focus: &Focus) -> Option<&Profile> {
        self.profiles.iter().find(|p| any_in(&p.apps, &focus.app) || any_in(&p.titles, &focus.title))
    }

    pub fn paused(&self, focus: &Focus) -> bool {
        any_in(&self.pause_apps, &focus.app)
    }

    /// The profile's HOST(n) command, else the global one.
    pub fn action<'a>(&'a self, profile: Option<&'a Profile>, n: u8) -> Option<&'a str> {
        profile.and_then(|p| p.actions.get(&n)).or_else(|| self.actions.get(&n)).map(String::as_str)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn focus(app: &str, title: &str) -> Focus {
        Focus { app: app.into(), title: title.into() }
    }

    #[test]
    fn example_config_parses() {
        let cfg = parse(include_str!("../config.example.toml")).unwrap();
        let freecad = cfg.select(&focus("org.freecad.FreeCAD", "Part - FreeCAD 1.0")).unwrap();
        assert_eq!((freecad.name.as_str(), freecad.layer), ("FreeCAD", 1));
        let sketcher = freecad.states.iter().find(|s| s.name == "Sketcher").unwrap();
        assert_eq!((sketcher.layer, sketcher.labels.len()), (4, KEYS));
        assert!(cfg.paused(&focus("Vial", "Vial")));
        assert!(cfg.select(&focus("foot", "zsh")).is_none());
    }

    #[test]
    fn matches_app_or_title_case_insensitively() {
        let cfg = parse(
            r#"
            [[profile]]
            name = "Docs"
            apps = []
            titles = ["- Google Docs"]
            layer = 4
            "#,
        )
        .unwrap();
        assert!(cfg.select(&focus("firefox", "Plan - GOOGLE DOCS — Mozilla Firefox")).is_some());
        assert!(cfg.select(&focus("firefox", "GitHub")).is_none());
    }

    #[test]
    fn actions_fall_back_to_global() {
        let cfg = parse(
            r#"
            actions = { 0 = "global0", 1 = "global1" }
            [[profile]]
            name = "A"
            apps = ["a"]
            layer = 1
            actions = { 1 = "local1" }
            "#,
        )
        .unwrap();
        let a = cfg.select(&focus("a", "")).unwrap();
        assert_eq!(cfg.action(Some(a), 0), Some("global0"));
        assert_eq!(cfg.action(Some(a), 1), Some("local1"));
        assert_eq!(cfg.action(None, 1), Some("global1"));
        assert_eq!(cfg.action(None, 7), None);
    }

    #[test]
    fn rejects_bad_profiles() {
        let bad = |body: &str| parse(&format!("[[profile]]\nname = \"X\"\napps = [\"x\"]\n{body}")).unwrap_err();
        assert!(bad("layer = 0").contains("outside 1-14"));
        assert!(bad("layer = 15").contains("outside 1-14"));
        assert!(bad("layer = 1\ncolor = \"red\"").contains("#rrggbb"));
        assert!(bad("layer = 1\nlabels = [\"1\",\"2\",\"3\",\"4\",\"5\",\"6\",\"7\",\"8\",\"9\",\"10\"]")
            .contains("10 labels"));
        assert!(bad("layer = 1\nactions = { 8 = \"x\" }").contains("not 0-7"));
        assert!(bad("layer = 1\nbogus = 1").contains("bogus"));
    }

    #[test]
    fn profile_states() {
        let cfg = parse(
            r##"
            [[profile]]
            name = "FreeCAD"
            apps = ["freecad"]
            layer = 1
            color = "#ff8800"
            [[profile.state]]
            name = "Sketcher"
            layer = 4
            labels = ["Line"]
            [[profile.state]]
            name = "TechDraw"
            layer = 5
            color = "#00ff00"
            "##,
        )
        .unwrap();
        let states = &cfg.profiles[0].states;
        assert_eq!(
            states[0],
            State { name: "Sketcher".into(), layer: 4, color: [0xff, 0x88, 0], labels: vec!["Line".into()] }
        );
        assert_eq!((states[1].color, states[1].labels.len()), ([0, 0xff, 0], 0));
    }

    #[test]
    fn rejects_bad_states() {
        let bad = |body: &str| {
            parse(&format!("[[profile]]\nname = \"X\"\napps = [\"x\"]\nlayer = 1\n[[profile.state]]\n{body}"))
                .unwrap_err()
        };
        assert!(bad("name = \"S\"\nlayer = 15").contains("profile \"X\": state \"S\": layer 15 is outside 1-14"));
        assert!(bad("name = \"S\"").contains("layer"), "layer is required");
        assert!(bad("name = \"\"\nlayer = 4").contains("needs a name"));
        assert!(bad("name = \"S\"\nlayer = 4\ncolor = \"red\"").contains("#rrggbb"));
        assert!(bad(
            "name = \"S\"\nlayer = 4\nlabels = [\"1\",\"2\",\"3\",\"4\",\"5\",\"6\",\"7\",\"8\",\"9\",\"10\"]"
        )
        .contains("10 labels"));
        assert!(bad("name = \"S\"\nlayer = 4\nactions = { 0 = \"x\" }").contains("actions"), "no per-state actions");
        assert!(bad("name = \"S\"\nlayer = 4\n[[profile.state]]\nname = \"S\"\nlayer = 5").contains("defined twice"));
    }
}
