// The wanna.sh desktop app. On first run it sets up wanna.sh's Python environment with the bundled uv; every time,
// it starts the wanna.sh server and shows it in a window. Closing the window stops the server and the model engines
// it started. wanna.sh itself is unchanged: it's the same app the installer and Docker image run.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_opener::OpenerExt;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

const PYTHON: &str = "3.13";
const PREFERRED_PORT: u16 = 7860;
const START_TIMEOUT: Duration = Duration::from_secs(180);

/// What the setup screen shows. It asks for this a few times a second until wanna.sh is ready.
#[derive(Default, Clone, Serialize)]
struct Setup {
    message: String,
    error: Option<String>,
    logs: String,
}

#[derive(Default)]
struct AppState {
    setup: Mutex<Setup>,
    server: Mutex<Option<Child>>,
    port: Mutex<Option<u16>>,
}

struct Paths {
    resources: PathBuf,
    runtime: PathBuf,
    logs: PathBuf,
}

fn paths(app: &AppHandle) -> Result<Paths, String> {
    let resources = app.path().resource_dir().map_err(|e| e.to_string())?;
    let data = app.path().app_local_data_dir().map_err(|e| e.to_string())?;
    // dunce turns Windows' \\?\C:\ paths into plain C:\ ones, which every tool understands.
    let resources = dunce::simplified(&resources).to_path_buf();
    let data = dunce::simplified(&data).to_path_buf();
    let runtime = data.join("runtime");
    let logs = data.join("logs");
    fs::create_dir_all(&runtime).map_err(|e| e.to_string())?;
    fs::create_dir_all(&logs).map_err(|e| e.to_string())?;
    Ok(Paths { resources, runtime, logs })
}

fn uv_path(p: &Paths) -> PathBuf {
    p.resources.join("uv").join(if cfg!(windows) { "uv.exe" } else { "uv" })
}

fn python_path(venv: &Path) -> PathBuf {
    if cfg!(windows) {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

fn set_message(app: &AppHandle, text: &str) {
    let state = app.state::<AppState>();
    let mut setup = state.setup.lock().unwrap();
    setup.message = text.into();
    setup.error = None;
}

fn set_error(app: &AppHandle, text: &str) {
    app.state::<AppState>().setup.lock().unwrap().error = Some(text.into());
}

/// A command that doesn't flash a console window on Windows. Programs it starts share its hidden console, so the
/// model engines wanna.sh starts don't open windows either.
fn hidden(program: &Path) -> Command {
    #[cfg_attr(not(windows), allow(unused_mut))]
    let mut cmd = Command::new(program);
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd
}

/// uv keeps Python and its download cache in the app's own folder. UTF-8 mode avoids Windows' legacy encodings.
fn with_env<'a>(cmd: &'a mut Command, p: &Paths) -> &'a mut Command {
    cmd.env("UV_PYTHON_INSTALL_DIR", p.runtime.join("python"))
        .env("UV_CACHE_DIR", p.runtime.join("uv-cache"))
        .env("UV_NO_PROGRESS", "1")
        .env("PYTHONUTF8", "1")
}

fn last_lines(text: &str, n: usize) -> String {
    let lines: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
    lines[lines.len().saturating_sub(n)..].join("\n")
}

fn run_logged(cmd: &mut Command, log: &Path) -> Result<(), String> {
    let out = cmd
        .stdin(Stdio::null())
        .output()
        .map_err(|e| format!("Couldn't run {:?}: {e}", cmd.get_program()))?;
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(log) {
        let _ = f.write_all(&out.stdout);
        let _ = f.write_all(&out.stderr);
    }
    if out.status.success() {
        Ok(())
    } else {
        Err(last_lines(&String::from_utf8_lossy(&out.stderr), 6))
    }
}

fn port_is_free(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok()
}

fn any_free_port() -> Option<u16> {
    TcpListener::bind(("127.0.0.1", 0)).ok()?.local_addr().ok().map(|a| a.port())
}

/// True once wanna.sh answers its health check.
fn healthy(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(500)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    if stream.write_all(b"GET /healthz HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n").is_err() {
        return false;
    }
    let mut head = [0u8; 12];
    matches!(stream.read(&mut head), Ok(12)) && &head[9..12] == b"200"
}

/// Set up (first run, or after an update) and start wanna.sh. Returns the address to show.
fn prepare(app: &AppHandle) -> Result<String, String> {
    let p = paths(app)?;
    let setup_log = p.logs.join("setup.log");
    let uv = uv_path(&p);
    let venv = p.runtime.join("venv");
    let python = python_path(&venv);
    let version = app.package_info().version.to_string();
    let stamp = p.runtime.join("installed-version");

    if !python.exists() {
        set_message(app, "Setting up Python. This only happens the first time.");
        run_logged(with_env(hidden(&uv).args(["venv", "--python", PYTHON]).arg(&venv), &p), &setup_log)?;
    }
    if fs::read_to_string(&stamp).ok().as_deref() != Some(version.as_str()) {
        set_message(app, "Installing wanna.sh. This only happens the first time, and after updates.");
        run_logged(
            with_env(hidden(&uv).args(["pip", "install", "--python"]).arg(&python).arg(p.resources.join("backend")), &p),
            &setup_log,
        )?;
        let _ = fs::write(&stamp, &version);
    }

    let port = if port_is_free(PREFERRED_PORT) {
        PREFERRED_PORT
    } else {
        any_free_port().ok_or("There's no free network port to run wanna.sh on.")?
    };
    *app.state::<AppState>().port.lock().unwrap() = Some(port);

    set_message(app, "Starting wanna.sh…");
    let server_log = File::create(p.logs.join("server.log")).map_err(|e| e.to_string())?;
    let mut server = hidden(&python);
    #[cfg(target_os = "macos")]
    {
        // Apps opened from the Finder get a short PATH; add where Docker Desktop and Homebrew put their commands,
        // so Code finds Docker.
        let home = std::env::var("HOME").unwrap_or_default();
        let path = std::env::var("PATH").unwrap_or_else(|_| "/usr/bin:/bin:/usr/sbin:/sbin".into());
        server.env("PATH", format!("{path}:/usr/local/bin:/opt/homebrew/bin:{home}/.docker/bin"));
    }
    let child = with_env(server.args(["-m", "wanna", "--port", &port.to_string()]), &p)
        .env("WANNA_UI_DIR", p.resources.join("ui"))
        .env("WANNA_UV", &uv)
        .stdin(Stdio::null())
        .stdout(server_log.try_clone().map_err(|e| e.to_string())?)
        .stderr(server_log)
        .spawn()
        .map_err(|e| format!("Couldn't start wanna.sh: {e}"))?;
    app.state::<AppState>().server.lock().unwrap().replace(child);

    let started = Instant::now();
    loop {
        if healthy(port) {
            return Ok(format!("http://127.0.0.1:{port}/"));
        }
        let exited = app
            .state::<AppState>()
            .server
            .lock()
            .unwrap()
            .as_mut()
            .and_then(|c| c.try_wait().ok().flatten());
        if let Some(status) = exited {
            let log = fs::read_to_string(p.logs.join("server.log")).unwrap_or_default();
            return Err(format!("wanna.sh stopped while starting ({status}).\n{}", last_lines(&log, 8)));
        }
        if started.elapsed() > START_TIMEOUT {
            return Err("wanna.sh didn't start within 3 minutes.".into());
        }
        thread::sleep(Duration::from_millis(300));
    }
}

fn start(app: AppHandle) {
    thread::spawn(move || match prepare(&app) {
        Ok(url) => {
            if let (Some(window), Ok(url)) = (app.get_webview_window("main"), Url::parse(&url)) {
                let _ = window.navigate(url);
            }
        }
        Err(e) => set_error(&app, &e),
    });
}

/// Stop wanna.sh and everything it started (the model engines are its child processes).
fn stop_server(app: &AppHandle) {
    let child = app.state::<AppState>().server.lock().unwrap().take();
    if let Some(mut child) = child {
        #[cfg(windows)]
        {
            let _ = hidden(Path::new("taskkill"))
                .args(["/PID", &child.id().to_string(), "/T", "/F"])
                .status();
        }
        // Elsewhere the engines run in their own process groups, so ask wanna.sh to stop: it stops them first.
        #[cfg(unix)]
        {
            let _ = Command::new("kill").args(["-TERM", &child.id().to_string()]).status();
            let asked = Instant::now();
            while asked.elapsed() < Duration::from_secs(15) && matches!(child.try_wait(), Ok(None)) {
                thread::sleep(Duration::from_millis(200));
            }
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}

/// Pages that stay in the window: the setup screen and wanna.sh itself. Everything else opens in the browser.
fn stays_in_app(app: &AppHandle, url: &Url) -> bool {
    if url.scheme() == "tauri" || url.host_str() == Some("tauri.localhost") {
        return true;
    }
    let port = *app.state::<AppState>().port.lock().unwrap();
    matches!(url.host_str(), Some("127.0.0.1" | "localhost")) && url.port() == port
}

/// The window's first size: 16:9, about 70% of the screen's width, between 1280x720 and 1920x1080, and never taller
/// than the space above the taskbar.
fn default_size(app: &AppHandle) -> (f64, f64) {
    let (screen_w, screen_h) = app
        .primary_monitor()
        .ok()
        .flatten()
        .map(|m| {
            let area = m.work_area().size;
            (area.width as f64 / m.scale_factor(), area.height as f64 / m.scale_factor())
        })
        .unwrap_or((1920.0, 1040.0));
    let mut width = (screen_w * 0.7).clamp(1280.0, 1920.0).min(screen_w * 0.95);
    let mut height = width * 9.0 / 16.0;
    if height > screen_h * 0.9 {
        height = screen_h * 0.9;
        width = height * 16.0 / 9.0;
    }
    (width.round(), height.round())
}

#[tauri::command]
fn setup_state(app: AppHandle) -> Setup {
    let mut setup = app.state::<AppState>().setup.lock().unwrap().clone();
    setup.logs = paths(&app).map(|p| p.logs.display().to_string()).unwrap_or_default();
    setup
}

#[tauri::command]
fn retry(app: AppHandle) {
    stop_server(&app);
    set_message(&app, "Trying again…");
    start(app);
}

#[tauri::command]
fn open_logs(app: AppHandle) {
    if let Ok(p) = paths(&app) {
        let _ = app.opener().open_path(p.logs.display().to_string(), None::<&str>);
    }
}

fn main() {
    tauri::Builder::default()
        // A second launch brings the open window forward instead of starting another wanna.sh.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![setup_state, retry, open_logs])
        .setup(|app| {
            let handle = app.handle().clone();
            let for_navigation = handle.clone();
            let for_popups = handle.clone();
            let (width, height) = default_size(&handle);
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("wanna.sh")
                .inner_size(width, height)
                .min_inner_size(960.0, 540.0)
                .center()
                .on_navigation(move |url| {
                    if stays_in_app(&for_navigation, url) {
                        return true;
                    }
                    let _ = for_navigation.opener().open_url(url.as_str(), None::<&str>);
                    false
                })
                // Links that open a new tab (GitHub, docs, Code's previews) go to the default browser.
                .on_new_window(move |url, _features| {
                    let _ = for_popups.opener().open_url(url.as_str(), None::<&str>);
                    NewWindowResponse::Deny
                })
                .build()?;
            start(handle);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("couldn't start the wanna.sh app")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                stop_server(app);
            }
        });
}
