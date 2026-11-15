//! Edits to greyd's config.toml that keep comments, key order and keys this editor does not know.
//! Every change goes through toml_edit on the parsed document; nothing is re-serialised from structs.

use std::collections::BTreeMap;
use std::ops::RangeInclusive;

use serde::{Deserialize, Serialize};
use toml_edit::{Array, ArrayOfTables, DocumentMut, InlineTable, Item, RawString, Table, TableLike, Value};

/// The pad stores 6 characters per label (LABEL frame, docs/protocol.md).
pub const LABEL_CHARS: usize = 6;
/// Layers 1-14 hold app profiles (docs/protocol.md, "Layers").
const PROFILE_LAYERS: RangeInclusive<i64> = 1..=14;
const PROFILE: &str = "profile";
const ACTIONS: &str = "actions";
const PAUSE_APPS: &str = "pause_apps";
const KNOWN_PROFILE_KEYS: [&str; 7] = ["name", "apps", "titles", "layer", "color", "labels", ACTIONS];

/// One change from the UI. JSON: `{"op":"set_profile","index":0,"field":{"layer":3}}`.
#[derive(Debug, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum Edit {
    AddProfile,
    DeleteProfile {
        index: usize,
    },
    MoveProfile {
        from: usize,
        to: usize,
    },
    SetProfile {
        index: usize,
        field: Field,
    },
    /// `profile: None` is the global `[actions]` table. An empty command removes the entry.
    SetAction {
        profile: Option<usize>,
        key: u8,
        command: String,
    },
    /// An empty list removes `pause_apps`, so greyd's default (pause for Vial) applies again.
    SetPauseApps {
        apps: Vec<String>,
    },
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Field {
    Name(String),
    Apps(Vec<String>),
    Titles(Vec<String>),
    Layer(u8),
    Color(String),
    Labels(Vec<String>),
}

/// What the UI shows. Read leniently: a wrong type shows as missing and greyd's parser names it.
#[derive(Debug, Serialize, PartialEq)]
pub struct View {
    pub profiles: Vec<ProfileView>,
    /// None: not in the file, greyd uses its default.
    pub pause_apps: Option<Vec<String>>,
    pub actions: BTreeMap<String, String>,
    pub warnings: Vec<String>,
}

#[derive(Debug, Serialize, PartialEq)]
pub struct ProfileView {
    pub name: String,
    pub apps: Vec<String>,
    pub titles: Vec<String>,
    pub layer: Option<i64>,
    pub color: Option<String>,
    pub labels: Vec<String>,
    pub actions: BTreeMap<String, String>,
    /// Who else holds this profile's layer: other profiles, or their states as "FreeCAD / Sketcher".
    pub shares_layer_with: Vec<String>,
    /// Keys this editor does not edit; they are kept as written.
    pub other_keys: Vec<String>,
}

#[derive(Debug)]
pub struct ConfigDoc {
    doc: DocumentMut,
}

impl ConfigDoc {
    pub fn parse(text: &str) -> Result<Self, String> {
        let doc: DocumentMut = text.parse().map_err(|e: toml_edit::TomlError| e.to_string())?;
        if doc.get(PROFILE).is_some_and(|p| !p.is_array_of_tables()) {
            return Err("`profile` must be written as [[profile]] tables to be edited here".into());
        }
        if doc.get(ACTIONS).is_some_and(|a| !a.is_table_like()) {
            return Err("`actions` must be a table".into());
        }
        Ok(ConfigDoc { doc })
    }

    pub fn text(&self) -> String {
        self.doc.to_string()
    }

    pub fn apply(&mut self, edit: Edit) -> Result<(), String> {
        match edit {
            Edit::AddProfile => self.add_profile(),
            Edit::DeleteProfile { index } => {
                self.profile_mut(index)?;
                self.profiles_mut().remove(index);
            }
            Edit::MoveProfile { from, to } => self.move_profile(from, to)?,
            Edit::SetProfile { index, field } => set_field(self.profile_mut(index)?, field)?,
            Edit::SetAction { profile, key, command } => self.set_action(profile, key, &command)?,
            Edit::SetPauseApps { apps } => put_or_remove(self.doc.as_table_mut(), PAUSE_APPS, apps),
        }
        Ok(())
    }

    pub fn view(&self) -> View {
        let tables: Vec<&Table> = self.profiles().map(|aot| aot.iter().collect()).unwrap_or_default();
        let shared = shared_layers(&tables);
        let profiles: Vec<ProfileView> =
            tables.iter().enumerate().map(|(index, table)| profile_view(table, index, &shared)).collect();
        View {
            warnings: warnings(&profiles, &shared),
            profiles,
            pause_apps: self.doc.get(PAUSE_APPS).map(strings),
            actions: commands(self.doc.as_table()),
        }
    }

    fn profiles(&self) -> Option<&ArrayOfTables> {
        self.doc.get(PROFILE).and_then(Item::as_array_of_tables)
    }

    /// The [[profile]] array; `parse` guarantees that any existing `profile` is one.
    fn profiles_mut(&mut self) -> &mut ArrayOfTables {
        self.doc
            .entry(PROFILE)
            .or_insert_with(|| Item::ArrayOfTables(ArrayOfTables::new()))
            .as_array_of_tables_mut()
            .expect("parse rejects a `profile` that is not [[profile]] tables")
    }

    fn profile_mut(&mut self, index: usize) -> Result<&mut Table, String> {
        let count = self.profiles().map_or(0, ArrayOfTables::len);
        self.profiles_mut().get_mut(index).ok_or_else(|| format!("no profile {index} (there are {count})"))
    }

    fn add_profile(&mut self) {
        let used: Vec<i64> =
            self.profiles().iter().flat_map(|aot| aot.iter()).flat_map(layer_holders).map(|(layer, _)| layer).collect();
        let layer = PROFILE_LAYERS.clone().find(|l| !used.contains(l)).unwrap_or(*PROFILE_LAYERS.start());
        let mut table = Table::new();
        table.set_position(self.next_position());
        table.insert("name", toml_edit::value("New profile"));
        table.insert("apps", toml_edit::value(Array::new()));
        table.insert("layer", toml_edit::value(layer));
        table.insert("color", toml_edit::value("#ffffff"));
        self.profiles_mut().push(table);
    }

    /// Reorders [[profile]] blocks. toml_edit writes tables in `position` order, so the moved
    /// profiles (and any tables nested in them) swap positions. The result is re-read and must mean
    /// exactly the old file with the profiles reordered; otherwise nothing changes.
    fn move_profile(&mut self, from: usize, to: usize) -> Result<(), String> {
        let count = self.profiles().map_or(0, ArrayOfTables::len);
        if from >= count || to >= count {
            return Err(format!("cannot move profile {from} to {to}: there are {count}"));
        }
        let before = self.doc.clone();
        let mut expected: toml::Table = toml::from_str(&self.text()).map_err(|e| e.to_string())?;
        if let Some(toml::Value::Array(list)) = expected.get_mut(PROFILE) {
            let moved = list.remove(from);
            list.insert(to, moved);
        }
        self.reorder(from, to);
        let after: toml::Table = toml::from_str(&self.text()).map_err(|e| e.to_string())?;
        if after != expected {
            self.doc = before;
            return Err("this file's layout cannot be reordered safely; move the [[profile]] blocks by hand".into());
        }
        Ok(())
    }

    fn reorder(&mut self, from: usize, to: usize) {
        let aot = self.profiles_mut();
        let mut tables: Vec<Table> = aot.iter().cloned().collect();
        let mut slots: Vec<usize> = Vec::new();
        tables.iter().for_each(|t| subtree_positions(t, &mut slots));
        slots.sort_unstable();
        // the blank lines above a header stay with its slot; the comments move with the table
        let mut gaps: BTreeMap<usize, Option<String>> = BTreeMap::new();
        for table in &tables {
            walk(table, &mut |t| {
                gaps.extend(t.position().map(|p| (p, prefix(t).map(|text| split_prefix(text).0.to_owned()))));
            });
        }
        let moved = tables.remove(from);
        tables.insert(to, moved);
        let mut free = slots.into_iter();
        for table in &mut tables {
            let mut own = Vec::new();
            subtree_positions(table, &mut own);
            let mut sorted = own.clone();
            sorted.sort_unstable();
            let new: Vec<usize> = free.by_ref().take(own.len()).collect();
            let mut renumbered = own.iter().map(|p| new[sorted.binary_search(p).expect("own position")]);
            set_subtree_positions(table, &mut renumbered);
            walk_mut(table, &mut |t| {
                if let Some(p) = t.position() {
                    set_gap(t, gaps[&p].as_deref());
                }
            });
        }
        aot.clear();
        tables.into_iter().for_each(|t| aot.push(t));
    }

    fn set_action(&mut self, profile: Option<usize>, key: u8, command: &str) -> Result<(), String> {
        let actions = match profile {
            Some(index) => {
                let new = || Item::Value(Value::InlineTable(InlineTable::new()));
                table_like(self.profile_mut(index)?.entry(ACTIONS).or_insert_with(new))?
            }
            None => {
                let mut new = Table::new();
                new.set_position(self.next_position());
                table_like(self.doc.entry(ACTIONS).or_insert(Item::Table(new)))?
            }
        };
        let key = key.to_string();
        if command.is_empty() {
            actions.remove(&key);
        } else {
            put(actions, &key, Value::from(command));
        }
        Ok(())
    }

    /// After every table in the file, so a new table is written last.
    fn next_position(&self) -> usize {
        let mut all = Vec::new();
        subtree_positions(self.doc.as_table(), &mut all);
        all.into_iter().max().map_or(0, |p| p + 1)
    }
}

fn table_like(item: &mut Item) -> Result<&mut dyn TableLike, String> {
    item.as_table_like_mut().ok_or_else(|| format!("`{ACTIONS}` is not a table"))
}

fn set_field(table: &mut Table, field: Field) -> Result<(), String> {
    match field {
        Field::Name(name) => put(table, "name", Value::from(name)),
        Field::Apps(apps) => put(table, "apps", string_array(apps)),
        Field::Titles(titles) => put_or_remove(table, "titles", titles),
        Field::Layer(layer) => put(table, "layer", Value::from(i64::from(layer))),
        Field::Color(color) => put(table, "color", Value::from(color)),
        Field::Labels(labels) => put_or_remove(table, "labels", checked_labels(labels)?),
    }
    Ok(())
}

fn checked_labels(mut labels: Vec<String>) -> Result<Vec<String>, String> {
    if let Some((key, long)) = labels.iter().enumerate().find(|(_, l)| l.chars().count() > LABEL_CHARS) {
        return Err(format!("key {}: {long:?} is longer than {LABEL_CHARS} characters", key + 1));
    }
    while labels.last().is_some_and(String::is_empty) {
        labels.pop();
    }
    Ok(labels)
}

/// Replace a value in place, keeping its key, position and comments; or add it at the end.
fn put(table: &mut dyn TableLike, key: &str, mut new: Value) {
    match table.get_mut(key) {
        Some(item) => {
            if let Some(old) = item.as_value() {
                *new.decor_mut() = old.decor().clone();
            }
            *item = Item::Value(new);
        }
        None => {
            table.insert(key, Item::Value(new));
        }
    }
}

fn put_or_remove(table: &mut Table, key: &str, list: Vec<String>) {
    if list.is_empty() {
        table.remove(key);
    } else {
        put(table, key, string_array(list));
    }
}

fn string_array(list: Vec<String>) -> Value {
    Value::Array(list.into_iter().collect())
}

/// `table` and every table nested in it, in key order.
fn walk<'t>(table: &'t Table, visit: &mut impl FnMut(&'t Table)) {
    visit(table);
    for (_, item) in table.iter() {
        match item {
            Item::Table(sub) => walk(sub, visit),
            Item::ArrayOfTables(aot) => aot.iter().for_each(|sub| walk(sub, visit)),
            _ => {}
        }
    }
}

/// Same order as `walk`.
fn walk_mut(table: &mut Table, visit: &mut impl FnMut(&mut Table)) {
    visit(table);
    for (_, item) in table.iter_mut() {
        match item {
            Item::Table(sub) => walk_mut(sub, visit),
            Item::ArrayOfTables(aot) => aot.iter_mut().for_each(|sub| walk_mut(sub, visit)),
            _ => {}
        }
    }
}

/// The text above a table header, if the file gave one; None means toml_edit's default.
fn prefix(table: &Table) -> Option<&str> {
    table.decor().prefix().and_then(RawString::as_str)
}

/// Splits a header prefix into the blank lines before it and the comment lines right above it.
fn split_prefix(prefix: &str) -> (&str, &str) {
    let blank = prefix.len() - prefix.trim_start().len();
    prefix.split_at(prefix[..blank].rfind('\n').map_or(0, |newline| newline + 1))
}

/// Puts `gap` (None: toml_edit's default) above the table's own comments.
fn set_gap(table: &mut Table, gap: Option<&str>) {
    let comments = prefix(table).map_or("", |text| split_prefix(text).1).to_owned();
    match gap {
        Some(gap) => table.decor_mut().set_prefix(format!("{gap}{comments}")),
        None if comments.is_empty() => {
            let suffix = table.decor().suffix().cloned();
            table.decor_mut().clear();
            if let Some(suffix) = suffix {
                table.decor_mut().set_suffix(suffix);
            }
        }
        // toml_edit's default gap before every header but the first
        None => table.decor_mut().set_prefix(format!("\n{comments}")),
    }
}

fn subtree_positions(table: &Table, out: &mut Vec<usize>) {
    walk(table, &mut |t| out.extend(t.position()));
}

/// The n-th position `subtree_positions` read becomes the n-th value of `new`.
fn set_subtree_positions(table: &mut Table, new: &mut impl Iterator<Item = usize>) {
    walk_mut(table, &mut |t| {
        if t.position().is_some() {
            t.set_position(new.next().expect("one new position per old one"));
        }
    });
}

fn name(table: &Table) -> &str {
    table.get("name").and_then(Item::as_str).unwrap_or_default()
}

/// Every layer a profile holds: its own and those of tables nested in it, such as [[profile.state]].
/// Each comes with its holder's name: "FreeCAD" or "FreeCAD / Sketcher".
fn layer_holders(profile: &Table) -> Vec<(i64, String)> {
    let mut out = Vec::new();
    walk(profile, &mut |t| {
        if let Some(layer) = t.get("layer").and_then(Item::as_integer) {
            let holder =
                if std::ptr::eq(t, profile) { name(t).to_owned() } else { format!("{} / {}", name(profile), name(t)) };
            out.push((layer, holder));
        }
    });
    out
}

/// Layers held by more than one profile, counting their states: those profiles share one keymap in
/// Vial. Each holder comes with the index of its profile.
type SharedLayers = BTreeMap<i64, Vec<(usize, String)>>;

fn shared_layers(profiles: &[&Table]) -> SharedLayers {
    let mut by_layer = SharedLayers::new();
    for (index, profile) in profiles.iter().enumerate() {
        for (layer, holder) in layer_holders(profile) {
            by_layer.entry(layer).or_default().push((index, holder));
        }
    }
    by_layer.retain(|_, holders| holders.iter().any(|(index, _)| *index != holders[0].0));
    by_layer
}

fn profile_view(table: &Table, index: usize, shared: &SharedLayers) -> ProfileView {
    let layer = table.get("layer").and_then(Item::as_integer);
    let others = layer.and_then(|l| shared.get(&l)).into_iter().flatten().filter(|(owner, _)| *owner != index);
    ProfileView {
        name: name(table).to_owned(),
        apps: table.get("apps").map(strings).unwrap_or_default(),
        titles: table.get("titles").map(strings).unwrap_or_default(),
        layer,
        color: table.get("color").and_then(Item::as_str).map(str::to_owned),
        labels: table.get("labels").map(strings).unwrap_or_default(),
        actions: commands(table),
        shares_layer_with: others.map(|(_, holder)| holder.clone()).collect(),
        other_keys: table
            .iter()
            .map(|(k, _)| k)
            .filter(|k| !KNOWN_PROFILE_KEYS.contains(k))
            .map(str::to_owned)
            .collect(),
    }
}

fn strings(item: &Item) -> Vec<String> {
    item.as_array().map(|a| a.iter().filter_map(Value::as_str).map(str::to_owned).collect()).unwrap_or_default()
}

fn commands(parent: &dyn TableLike) -> BTreeMap<String, String> {
    let Some(actions) = parent.get(ACTIONS).and_then(Item::as_table_like) else {
        return BTreeMap::new();
    };
    actions.iter().filter_map(|(key, cmd)| Some((key.to_owned(), cmd.as_str()?.to_owned()))).collect()
}

/// Things greyd accepts but that are probably mistakes.
fn warnings(profiles: &[ProfileView], shared: &SharedLayers) -> Vec<String> {
    let shared = shared.iter().map(|(layer, holders)| {
        let names: Vec<&str> = holders.iter().map(|(_, holder)| holder.as_str()).collect();
        format!("layer {layer} is used by {}", names.join(", "))
    });
    let long = profiles.iter().flat_map(|p| {
        p.labels
            .iter()
            .filter(|l| l.chars().count() > LABEL_CHARS)
            .map(move |l| format!("{}: label {l:?} shows as its first {LABEL_CHARS} characters", p.name))
    });
    shared.chain(long).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    const EXAMPLE: &str = include_str!("../../../host/config.example.toml");

    fn doc(text: &str) -> ConfigDoc {
        ConfigDoc::parse(text).unwrap()
    }

    fn edit(json: &str) -> Edit {
        serde_json::from_str(json).unwrap()
    }

    fn changed_lines(a: &str, b: &str) -> Vec<(String, String)> {
        assert_eq!(a.lines().count(), b.lines().count(), "line count changed:\n{b}");
        a.lines().zip(b.lines()).filter(|(x, y)| x != y).map(|(x, y)| (x.to_owned(), y.to_owned())).collect()
    }

    #[test]
    fn untouched_document_round_trips_byte_for_byte() {
        assert_eq!(doc(EXAMPLE).text(), EXAMPLE);
    }

    #[test]
    fn view_reads_the_example() {
        let view = doc(EXAMPLE).view();
        let names: Vec<_> = view.profiles.iter().map(|p| p.name.as_str()).collect();
        assert_eq!(names, ["FreeCAD", "KiCad PCB", "Browser"]);
        assert_eq!(view.profiles[1].titles, ["PCB Editor"]);
        assert_eq!(view.profiles[2].labels.len(), 9);
        assert_eq!(view.pause_apps.as_deref(), Some(&["vial".to_owned()][..]));
        assert_eq!(view.actions["1"], "makoctl dismiss --all");
        assert!(view.warnings.is_empty());
    }

    #[test]
    fn setting_a_field_changes_one_line_and_keeps_its_comment() {
        let text = "[[profile]]\nname = \"A\"\napps = [\"a\"]\nlayer = 1   # FreeCAD layer\n";
        let mut d = doc(text);
        d.apply(edit(r#"{"op":"set_profile","index":0,"field":{"layer":4}}"#)).unwrap();
        assert_eq!(
            changed_lines(text, &d.text()),
            [("layer = 1   # FreeCAD layer".into(), "layer = 4   # FreeCAD layer".into())]
        );
    }

    #[test]
    fn labels_are_trimmed_limited_and_removed_when_empty() {
        let mut d = doc("[[profile]]\nname = \"A\"\napps = [\"a\"]\nlayer = 1\nlabels = [\"Iso\"]\n");
        let set = |labels: &str| edit(&format!(r#"{{"op":"set_profile","index":0,"field":{{"labels":{labels}}}}}"#));
        d.apply(set(r#"["Iso","","Top","","","","","",""]"#)).unwrap();
        assert_eq!(d.view().profiles[0].labels, ["Iso", "", "Top"]);
        assert!(d.apply(set(r#"["Isometric"]"#)).unwrap_err().contains("longer than 6"));
        d.apply(set(r#"["","","","","","","","",""]"#)).unwrap();
        assert!(!d.text().contains("labels"));
    }

    #[test]
    fn unknown_keys_and_nested_tables_survive_edits() {
        let text = r#"# top comment
future_global = { mode = "x" }

[[profile]]
name = "FreeCAD"
apps = ["freecad"]
layer = 1
labels = ["Iso"]
states = ["sketch"]

[[profile.state]]
when = "sketcher"
labels = ["Line"]

[[profile]]
name = "Browser"
apps = ["firefox"]
layer = 3
"#;
        let mut d = doc(text);
        d.apply(edit(r#"{"op":"set_profile","index":0,"field":{"name":"CAD"}}"#)).unwrap();
        d.apply(edit(r#"{"op":"set_action","profile":0,"key":2,"command":"echo hi"}"#)).unwrap();
        let out = d.text();
        for kept in ["# top comment", "future_global = { mode = \"x\" }", "states = [\"sketch\"]", "[[profile.state]]"]
        {
            assert!(out.contains(kept), "lost {kept:?}:\n{out}");
        }
        assert!(out.contains("actions = { 2 = \"echo hi\" }"), "{out}");
        assert_eq!(d.view().profiles[0].other_keys, ["states", "state"]);
    }

    #[test]
    fn move_carries_nested_tables_and_comments() {
        let text = r#"pause_apps = ["vial"]

# the CAD one
[[profile]]
name = "A"
apps = ["a"]
layer = 1

[[profile.state]]
when = "sketch"

[actions]
0 = "zero"

[[profile]]
name = "B"
apps = ["b"]
layer = 2
"#;
        let mut d = doc(text);
        d.apply(edit(r#"{"op":"move_profile","from":1,"to":0}"#)).unwrap();
        let out = d.text();
        let names: Vec<_> = d.view().profiles.into_iter().map(|p| p.name).collect();
        assert_eq!(names, ["B", "A"]);
        let reread: toml::Table = toml::from_str(&out).unwrap();
        let a = &reread["profile"].as_array().unwrap()[1];
        assert_eq!(a["state"][0]["when"].as_str(), Some("sketch"), "{out}");
        assert!(out.find("# the CAD one").unwrap() < out.find("name = \"A\"").unwrap());
        assert_eq!(reread["actions"]["0"].as_str(), Some("zero"));
        assert!(d.apply(edit(r#"{"op":"move_profile","from":0,"to":2}"#)).unwrap_err().contains("there are 2"));
    }

    #[test]
    fn move_in_the_example_still_parses_in_greyd() {
        let mut d = doc(EXAMPLE);
        d.apply(edit(r#"{"op":"move_profile","from":0,"to":2}"#)).unwrap();
        let cfg = greyd::config::parse(&d.text()).unwrap();
        let names: Vec<_> = cfg.profiles.iter().map(|p| p.name.as_str()).collect();
        assert_eq!(names, ["KiCad PCB", "Browser", "FreeCAD"]);
        d.apply(edit(r#"{"op":"move_profile","from":2,"to":0}"#)).unwrap();
        assert_eq!(d.text(), EXAMPLE);
    }

    #[test]
    fn add_and_delete_profiles() {
        let text = "[[profile]]\nname = \"A\"\napps = [\"a\"]\nlayer = 1\n\n\
                    [[profile.state]]\nname = \"S\"\nlayer = 2\n\n\
                    [[profile]]\nname = \"B\"\napps = [\"b\"]\nlayer = 3\n";
        let mut d = doc(text);
        d.apply(Edit::AddProfile).unwrap();
        let added = d.view().profiles.pop().unwrap();
        assert_eq!((added.name.as_str(), added.layer), ("New profile", Some(4)), "layer 2 is taken by a state");
        assert_eq!(
            d.text(),
            format!("{text}\n[[profile]]\nname = \"New profile\"\napps = []\nlayer = 4\ncolor = \"#ffffff\"\n")
        );
        d.apply(edit(r#"{"op":"delete_profile","index":0}"#)).unwrap();
        assert_eq!(d.view().profiles[0].name, "B");
        assert!(!d.text().contains("profile.state"));
        assert!(d.apply(edit(r#"{"op":"delete_profile","index":9}"#)).unwrap_err().contains("no profile 9"));
    }

    #[test]
    fn add_to_an_empty_file() {
        let mut d = doc("");
        d.apply(Edit::AddProfile).unwrap();
        d.apply(edit(r#"{"op":"set_action","key":0,"command":"true"}"#)).unwrap();
        d.apply(edit(r#"{"op":"set_pause_apps","apps":["vial","obs"]}"#)).unwrap();
        let out = d.text();
        assert!(out.starts_with("pause_apps = [\"vial\", \"obs\"]\n"), "{out}");
        assert!(out.find("[[profile]]").unwrap() < out.find("[actions]").unwrap(), "{out}");
        assert_eq!(d.view().profiles[0].layer, Some(1));
    }

    #[test]
    fn global_and_profile_actions_set_and_clear() {
        let mut d = doc(EXAMPLE);
        d.apply(edit(r#"{"op":"set_action","key":1,"command":""}"#)).unwrap();
        d.apply(edit(r#"{"op":"set_action","key":7,"command":"notify-send hi"}"#)).unwrap();
        let view = d.view();
        assert!(!view.actions.contains_key("1"));
        assert_eq!(view.actions["7"], "notify-send hi");
        assert!(d.text().contains("2 = \"swaymsg 'output * power toggle'\"\n7 = \"notify-send hi\""));
    }

    #[test]
    fn warns_on_shared_layers_and_long_labels() {
        let d = doc("[[profile]]\nname = \"A\"\napps = [\"a\"]\nlayer = 2\nlabels = [\"Toolong\"]\n\
                     [[profile]]\nname = \"B\"\napps = [\"b\"]\nlayer = 2\n");
        assert_eq!(
            d.view().warnings,
            ["layer 2 is used by A, B", "A: label \"Toolong\" shows as its first 6 characters"]
        );
    }

    #[test]
    fn clearing_pause_apps_brings_back_greyds_default() {
        let mut d = doc(EXAMPLE);
        d.apply(edit(r#"{"op":"set_pause_apps","apps":[]}"#)).unwrap();
        assert_eq!(d.view().pause_apps, None);
        assert!(!d.text().contains("pause_apps"));
        greyd::config::parse(&d.text()).unwrap();
    }

    #[test]
    fn a_state_layer_counts_as_taken_by_its_profile() {
        let mut d = doc(EXAMPLE);
        d.apply(edit(r#"{"op":"set_profile","index":1,"field":{"layer":4}}"#)).unwrap();
        let view = d.view();
        assert_eq!(view.warnings, ["layer 4 is used by FreeCAD / Sketcher, KiCad PCB"]);
        assert_eq!(view.profiles[1].shares_layer_with, ["FreeCAD / Sketcher"]);
        assert!(view.profiles[0].shares_layer_with.is_empty(), "FreeCAD's own layer 1 is not shared");
        d.apply(edit(r#"{"op":"set_profile","index":0,"field":{"layer":4}}"#)).unwrap();
        let view = d.view();
        assert_eq!(view.profiles[0].shares_layer_with, ["KiCad PCB"], "its own state does not count");
    }

    #[test]
    fn move_keeps_blank_lines_in_place_and_comments_with_their_profile() {
        let text = "[[profile]]\nname = \"A\"\napps = [\"a\"]\nlayer = 1\n\n\
                    # about B\n[[profile]]\nname = \"B\"\napps = [\"b\"]\nlayer = 2\n";
        let mut d = doc(text);
        d.apply(edit(r#"{"op":"move_profile","from":1,"to":0}"#)).unwrap();
        assert_eq!(
            d.text(),
            "# about B\n[[profile]]\nname = \"B\"\napps = [\"b\"]\nlayer = 2\n\n\
             [[profile]]\nname = \"A\"\napps = [\"a\"]\nlayer = 1\n"
        );
        d.apply(edit(r#"{"op":"move_profile","from":1,"to":0}"#)).unwrap();
        assert_eq!(d.text(), text);
    }

    #[test]
    fn move_after_add_keeps_default_gaps() {
        let mut d = doc("[[profile]]\nname = \"A\"\napps = [\"a\"]\nlayer = 1\n");
        d.apply(Edit::AddProfile).unwrap();
        d.apply(edit(r#"{"op":"move_profile","from":1,"to":0}"#)).unwrap();
        assert_eq!(
            d.text(),
            "[[profile]]\nname = \"New profile\"\napps = []\nlayer = 2\ncolor = \"#ffffff\"\n\n\
             [[profile]]\nname = \"A\"\napps = [\"a\"]\nlayer = 1\n"
        );
    }

    #[test]
    fn rejects_shapes_it_cannot_edit() {
        assert!(ConfigDoc::parse("profile = [{ name = \"A\" }]").unwrap_err().contains("[[profile]]"));
        assert!(ConfigDoc::parse("actions = 3").unwrap_err().contains("table"));
        assert!(ConfigDoc::parse("[[profile]\n").is_err());
    }
}
