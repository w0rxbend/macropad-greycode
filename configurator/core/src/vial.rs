//! Keymaps stay in Vial; the app only starts it.

use std::ffi::OsStr;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::process::{Command, Stdio};

const VIAL: &str = "vial";

/// The first executable `name` in a PATH-style list.
pub fn find(name: &str, path_var: &OsStr) -> Option<PathBuf> {
    std::env::split_paths(path_var).map(|dir| dir.join(name)).find(|candidate| {
        std::fs::metadata(candidate).is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
    })
}

/// Start Vial detached; a thread reaps it when it exits.
pub fn launch() -> Result<(), String> {
    let path =
        find(VIAL, &std::env::var_os("PATH").unwrap_or_default()).ok_or_else(|| format!("`{VIAL}` is not on PATH"))?;
    let mut child = Command::new(&path)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("{}: {e}", path.display()))?;
    std::thread::spawn(move || child.wait());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn finds_only_executables_in_order() {
        let root = std::env::temp_dir().join(format!("greyconf-vial-{}", std::process::id()));
        let (a, b) = (root.join("a"), root.join("b"));
        fs::create_dir_all(&a).unwrap();
        fs::create_dir_all(&b).unwrap();
        fs::write(a.join("vial"), "").unwrap(); // not executable
        fs::write(b.join("vial"), "#!/bin/sh\n").unwrap();
        fs::set_permissions(b.join("vial"), fs::Permissions::from_mode(0o755)).unwrap();
        let path_var = std::env::join_paths([&a, &b]).unwrap();
        assert_eq!(find("vial", &path_var), Some(b.join("vial")));
        assert_eq!(find("vial", &std::env::join_paths([&a]).unwrap()), None);
        fs::remove_dir_all(root).unwrap();
    }
}
