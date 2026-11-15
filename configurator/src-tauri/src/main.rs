//! Tauri shell: each command forwards to greyconf. All logic and its tests live in ../core.

use std::sync::{Mutex, MutexGuard};

use greyconf::client::{self, Link};
use greyconf::document::Edit;
use greyconf::session::{self, Session, SessionView};
use greyconf::vial;
use tauri::State;

/// The config file the window is editing; None until `open` succeeds.
#[derive(Default)]
struct Open(Mutex<Option<Session>>);

impl Open {
    fn lock(&self) -> Result<MutexGuard<'_, Option<Session>>, String> {
        self.0.lock().map_err(|_| "internal error: an earlier command panicked".to_string())
    }

    fn with<T>(&self, act: impl FnOnce(&mut Session) -> Result<T, String>) -> Result<T, String> {
        act(self.lock()?.as_mut().ok_or("no config file is open")?)
    }
}

/// (Re)read greyd's config file, dropping unsaved edits.
#[tauri::command]
fn open(state: State<'_, Open>) -> Result<SessionView, String> {
    let session = Session::open(&session::default_path())?;
    let view = session.view();
    *state.lock()? = Some(session);
    Ok(view)
}

#[tauri::command]
fn apply(state: State<'_, Open>, edit: Edit) -> Result<SessionView, String> {
    state.with(|s| s.apply(edit).map(|()| s.view()))
}

/// Validate with greyd's parser and write atomically; greyd reloads within a second.
#[tauri::command]
fn save(state: State<'_, Open>) -> Result<SessionView, String> {
    state.with(|s| s.save().map(|()| s.view()))
}

// Socket calls block for up to the client timeout, so they run off the main thread.
#[tauri::command]
async fn status() -> Link {
    client::status(&greyd::control::socket_path())
}

#[tauri::command]
async fn alert(level: String, text: String, timeout: u16) -> Result<(), String> {
    client::alert(&greyd::control::socket_path(), &level, &text, timeout)
}

#[tauri::command]
fn open_vial() -> Result<(), String> {
    vial::launch()
}

fn main() {
    tauri::Builder::default()
        .manage(Open::default())
        .invoke_handler(tauri::generate_handler![open, apply, save, status, alert, open_vial])
        .run(tauri::generate_context!())
        .expect("the greycode configurator window failed to start");
}
