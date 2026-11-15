//! greycode configurator core: everything the app does, testable without the Tauri runtime.
//! The Tauri shell in `../src-tauri` is a thin layer of commands over these modules.

pub mod atomic;
pub mod client;
pub mod document;
pub mod session;
pub mod vial;

/// An empty directory under the system temp dir, unique to this test name and process.
#[cfg(test)]
pub(crate) fn scratch(name: &str) -> std::path::PathBuf {
    let dir = std::env::temp_dir().join(format!("greyconf-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir); // a leftover from an earlier run with the same pid
    dir
}
