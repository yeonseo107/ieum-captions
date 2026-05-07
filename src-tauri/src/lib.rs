use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, RunEvent};

// Python sidecar 자식 프로세스 핸들 보관 (Tauri 종료 시 정리용).
struct PythonSidecar(Mutex<Option<Child>>);

fn spawn_backend() -> std::io::Result<Child> {
    // dev 모드: backend/.venv/bin/python backend/server.py — 코드 수정 즉시 반영
    // release 모드: tauri.conf.json `bundle.externalBin`으로 번들된 PyInstaller 바이너리 (main exe와 같은 폴더)
    if cfg!(debug_assertions) {
        let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .expect("src-tauri의 부모 디렉토리가 있어야 함")
            .to_path_buf();

        let python = project_root
            .join("backend")
            .join(".venv")
            .join("bin")
            .join("python");
        let script = project_root.join("backend").join("server.py");

        log::info!("[sidecar] dev spawn: {} {}", python.display(), script.display());

        Command::new(&python)
            .arg(&script)
            .current_dir(&project_root)
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .spawn()
    } else {
        // externalBin은 main exe와 같은 디렉토리에 target-triple 접미사 제거된 이름으로 배치됨.
        // macOS .app/Contents/MacOS/ieum-server, Windows: ieum-server.exe (main exe 옆).
        let mut sidecar = std::env::current_exe()?;
        sidecar.pop();
        sidecar.push(if cfg!(windows) { "ieum-server.exe" } else { "ieum-server" });

        log::info!("[sidecar] release spawn: {}", sidecar.display());

        Command::new(&sidecar)
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .spawn()
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sidecar_state = PythonSidecar(Mutex::new(None));

    tauri::Builder::default()
        .manage(sidecar_state)
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            match spawn_backend() {
                Ok(child) => {
                    let state = app.state::<PythonSidecar>();
                    *state.0.lock().unwrap() = Some(child);
                    log::info!("[sidecar] 시작 완료");
                }
                Err(e) => {
                    // spawn 실패해도 앱은 계속 — 사용자가 수동으로 server.py 띄울 수 있음.
                    // WS 클라이언트의 auto-reconnect가 그 케이스를 흡수함.
                    log::error!("[sidecar] 시작 실패: {} — 백엔드 없이 앱 계속 실행", e);
                }
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                let state = app.state::<PythonSidecar>();
                // lock().take() 한 줄에서 MutexGuard drop, 그 결과(Option<Child>)만 다음 줄로 넘김.
                let child = state.0.lock().unwrap().take();
                if let Some(mut child) = child {
                    log::info!("[sidecar] 종료");
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        });
}
