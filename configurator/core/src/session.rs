//! One open config file: the edited document, what is on disk, and the save that greyd picks up.

use std::io::ErrorKind;
use std::path::{Path, PathBuf};

use serde::Serialize;

use crate::atomic;
use crate::document::{ConfigDoc, Edit, View};

/// `$XDG_CONFIG_HOME/greycode/config.toml`, else `~/.config/greycode/config.toml`: where greyd reads.
pub fn default_path() -> PathBuf {
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")))
        .unwrap_or_else(|| PathBuf::from("."));
    base.join("greycode/config.toml")
}

pub struct Session {
    path: PathBuf,
    /// The file as last read or written; None when it does not exist.
    on_disk: Option<String>,
    doc: ConfigDoc,
}

#[derive(Debug, Serialize)]
pub struct SessionView {
    pub path: String,
    pub dirty: bool,
    /// greyd's own parser on the edited text; Some blocks saving.
    pub problem: Option<String>,
    #[serde(flatten)]
    pub config: View,
}

impl Session {
    /// A missing file opens as an empty document; saving creates it.
    pub fn open(path: &Path) -> Result<Session, String> {
        let on_disk = read(path)?;
        let doc =
            ConfigDoc::parse(on_disk.as_deref().unwrap_or_default()).map_err(|e| format!("{}: {e}", path.display()))?;
        Ok(Session { path: path.to_owned(), on_disk, doc })
    }

    pub fn apply(&mut self, edit: Edit) -> Result<(), String> {
        self.doc.apply(edit)
    }

    pub fn view(&self) -> SessionView {
        let text = self.doc.text();
        SessionView {
            path: self.path.display().to_string(),
            dirty: self.on_disk.as_deref() != Some(text.as_str()),
            problem: greyd::config::parse(&text).err(),
            config: self.doc.view(),
        }
    }

    /// Validate with greyd's parser, refuse if someone else changed the file, then write atomically.
    /// greyd reloads the file within a second of the write.
    pub fn save(&mut self) -> Result<(), String> {
        let text = self.doc.text();
        greyd::config::parse(&text).map_err(|e| format!("not saved, greyd would reject it: {e}"))?;
        if read(&self.path)? != self.on_disk {
            return Err(format!("not saved: {} changed on disk since it was opened; reload it", self.path.display()));
        }
        atomic::write(&self.path, &text).map_err(|e| format!("{}: {e}", self.path.display()))?;
        self.on_disk = Some(text);
        Ok(())
    }
}

fn read(path: &Path) -> Result<Option<String>, String> {
    match std::fs::read_to_string(path) {
        Ok(text) => Ok(Some(text)),
        Err(e) if e.kind() == ErrorKind::NotFound => Ok(None),
        Err(e) => Err(format!("{}: {e}", path.display())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scratch;
    use std::fs;

    const EXAMPLE: &str = include_str!("../../../host/config.example.toml");

    fn layer(n: u8) -> Edit {
        serde_json::from_str(&format!(r#"{{"op":"set_profile","index":0,"field":{{"layer":{n}}}}}"#)).unwrap()
    }

    #[test]
    fn edit_validate_save_reopen() {
        let path = scratch("session").join("config.toml");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, EXAMPLE).unwrap();
        let mut s = Session::open(&path).unwrap();
        assert!(!s.view().dirty);
        s.apply(layer(5)).unwrap();
        assert!(s.view().dirty);
        s.save().unwrap();
        assert!(!s.view().dirty);
        let saved = fs::read_to_string(&path).unwrap();
        assert_eq!(greyd::config::parse(&saved).unwrap().profiles[0].layer, 5);
        assert_eq!(saved, EXAMPLE.replacen("layer = 1", "layer = 5", 1));
    }

    #[test]
    fn greyd_rejection_blocks_save() {
        let path = scratch("reject").join("config.toml");
        let mut s = Session::open(&path).unwrap();
        s.apply(Edit::AddProfile).unwrap(); // no apps or titles yet
        assert!(s.view().problem.unwrap().contains("needs `apps` or `titles`"));
        assert!(s.save().unwrap_err().contains("greyd would reject"));
        assert!(!path.exists());
        s.apply(layer(15)).unwrap();
        assert!(s.view().problem.unwrap().contains("outside 1-14"));
    }

    #[test]
    fn refuses_to_overwrite_an_outside_change() {
        let path = scratch("conflict").join("config.toml");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, EXAMPLE).unwrap();
        let mut s = Session::open(&path).unwrap();
        s.apply(layer(5)).unwrap();
        fs::write(&path, format!("{EXAMPLE}# edited in vim\n")).unwrap();
        assert!(s.save().unwrap_err().contains("changed on disk"));
        assert!(fs::read_to_string(&path).unwrap().ends_with("# edited in vim\n"));
    }

    /// The field names and op names ui/app.js relies on.
    #[test]
    fn json_contract_with_the_ui() {
        let path = scratch("contract").join("config.toml");
        let mut s = Session::open(&path).unwrap();
        s.apply(serde_json::from_str(r#"{"op":"add_profile"}"#).unwrap()).unwrap();
        let view = serde_json::to_value(s.view()).unwrap();
        let mut keys: Vec<_> = view.as_object().unwrap().keys().cloned().collect();
        keys.sort();
        assert_eq!(keys, ["actions", "dirty", "path", "pause_apps", "problem", "profiles", "warnings"]);
        let profile = view["profiles"][0].as_object().unwrap();
        let mut keys: Vec<_> = profile.keys().cloned().collect();
        keys.sort();
        assert_eq!(
            keys,
            ["actions", "apps", "color", "labels", "layer", "name", "other_keys", "shares_layer_with", "titles"]
        );
    }

    #[test]
    fn save_writes_through_a_symlinked_config() {
        let dir = scratch("session-link");
        fs::create_dir_all(dir.join("dotfiles")).unwrap();
        fs::write(dir.join("dotfiles/config.toml"), EXAMPLE).unwrap();
        let link = dir.join("config.toml");
        std::os::unix::fs::symlink("dotfiles/config.toml", &link).unwrap();
        let mut s = Session::open(&link).unwrap();
        s.apply(layer(5)).unwrap();
        s.save().unwrap();
        assert!(fs::symlink_metadata(&link).unwrap().file_type().is_symlink());
        assert_eq!(
            fs::read_to_string(dir.join("dotfiles/config.toml")).unwrap(),
            EXAMPLE.replacen("layer = 1", "layer = 5", 1)
        );
        assert!(!s.view().dirty);
    }

    #[test]
    fn missing_file_opens_empty_and_save_creates_it() {
        let path = scratch("create").join("greycode/config.toml");
        let mut s = Session::open(&path).unwrap();
        assert!(s.view().dirty && s.view().config.profiles.is_empty());
        s.save().unwrap();
        assert_eq!(fs::read_to_string(&path).unwrap(), "");
    }
}
