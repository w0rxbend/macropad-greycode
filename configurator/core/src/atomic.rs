//! Write a file so readers see the old content or the new content, never half of it.

use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};

/// Temp file in the same directory, fsync, keep the old file's permissions, rename over the target.
/// A symlink is written through: the file it points to is replaced and the link stays a link.
pub fn write(path: &Path, text: &str) -> io::Result<()> {
    let path = &through_symlink(path)?;
    let dir = path.parent().filter(|d| !d.as_os_str().is_empty()).unwrap_or(Path::new("."));
    fs::create_dir_all(dir)?;
    let name = path.file_name().ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "no file name"))?;
    let temp = dir.join(format!(".{}.{}.tmp", name.to_string_lossy(), std::process::id()));
    let written = write_synced(&temp, text, path).and_then(|()| fs::rename(&temp, path));
    if written.is_err() {
        let _ = fs::remove_file(&temp); // best effort; the error that matters is `written`
    }
    written?;
    File::open(dir)?.sync_all() // make the rename itself durable
}

/// Dotfiles managers (stow, chezmoi) link the config into place; renaming over the link would turn it
/// into a plain file and the dotfiles copy would never see the edit. A dangling link is an error.
fn through_symlink(path: &Path) -> io::Result<PathBuf> {
    match fs::symlink_metadata(path) {
        Ok(meta) if meta.file_type().is_symlink() => fs::canonicalize(path)
            .map_err(|e| io::Error::new(e.kind(), format!("symlink target cannot be resolved: {e}"))),
        _ => Ok(path.to_owned()),
    }
}

fn write_synced(temp: &Path, text: &str, target: &Path) -> io::Result<()> {
    let mut file = OpenOptions::new().write(true).create(true).truncate(true).open(temp)?;
    if let Ok(meta) = fs::metadata(target) {
        file.set_permissions(meta.permissions())?;
    }
    file.write_all(text.as_bytes())?;
    file.sync_all()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scratch;
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn creates_directories_and_replaces_content() {
        let path = scratch("atomic").join("greycode/config.toml");
        write(&path, "a = 1\n").unwrap();
        write(&path, "a = 2\n").unwrap();
        assert_eq!(fs::read_to_string(&path).unwrap(), "a = 2\n");
        let leftovers: Vec<_> = fs::read_dir(path.parent().unwrap()).unwrap().collect();
        assert_eq!(leftovers.len(), 1, "temp file left behind");
    }

    #[test]
    fn writes_through_a_symlink_and_keeps_the_link() {
        let dir = scratch("link");
        fs::create_dir_all(dir.join("dotfiles")).unwrap();
        let real = dir.join("dotfiles/config.toml");
        fs::write(&real, "a = 1\n").unwrap();
        fs::set_permissions(&real, fs::Permissions::from_mode(0o640)).unwrap();
        let link = dir.join("config.toml");
        std::os::unix::fs::symlink("dotfiles/config.toml", &link).unwrap();
        write(&link, "a = 2\n").unwrap();
        assert!(fs::symlink_metadata(&link).unwrap().file_type().is_symlink());
        assert_eq!(fs::read_to_string(&real).unwrap(), "a = 2\n");
        assert_eq!(fs::metadata(&real).unwrap().permissions().mode() & 0o777, 0o640);
        assert_eq!(fs::read_dir(&dir).unwrap().count(), 2, "temp file left next to the link");
        assert_eq!(fs::read_dir(dir.join("dotfiles")).unwrap().count(), 1, "temp file left next to the target");
    }

    #[test]
    fn refuses_a_dangling_symlink() {
        let dir = scratch("dangling");
        fs::create_dir_all(&dir).unwrap();
        let link = dir.join("config.toml");
        std::os::unix::fs::symlink("gone/config.toml", &link).unwrap();
        let err = write(&link, "a = 1\n").unwrap_err();
        assert!(err.to_string().contains("symlink target"), "{err}");
        assert!(fs::symlink_metadata(&link).unwrap().file_type().is_symlink(), "link replaced");
    }

    #[test]
    fn keeps_permissions() {
        let path = scratch("perm").join("config.toml");
        write(&path, "a = 1\n").unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        write(&path, "a = 2\n").unwrap();
        assert_eq!(fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o600);
    }
}
