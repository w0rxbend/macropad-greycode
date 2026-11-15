//! greyd [CONFIG]: run the bridge. CONFIG defaults to ~/.config/greycode/config.toml.

use std::path::PathBuf;
use std::process::ExitCode;

fn main() -> ExitCode {
    let path = std::env::args_os().nth(1).map(PathBuf::from).unwrap_or_else(greyd::config::default_path);
    match greyd::daemon::run(path) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("greyd: {e}");
            ExitCode::FAILURE
        }
    }
}
