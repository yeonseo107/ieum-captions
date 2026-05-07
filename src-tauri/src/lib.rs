use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Mutex;
use command_group::{CommandGroup, GroupChild};
use tauri::{Manager, RunEvent, WindowEvent};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};

// Python sidecar 핸들 — GroupChild로 묶어서 종료 시 자식 프로세스 트리 전체 정리.
// (faster-whisper/ctranslate2가 multiprocessing.resource_tracker 등 손주 프로세스를 띄우는데
// std::process::Child::kill만으론 그 손주들이 PPID=1 고아로 남음.)
struct PythonSidecar(Mutex<Option<GroupChild>>);

fn spawn_backend() -> std::io::Result<GroupChild> {
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

        let mut cmd = Command::new(&python);
        cmd.arg(&script)
            .current_dir(&project_root)
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit());
        cmd.group_spawn()
    } else {
        // externalBin은 main exe와 같은 디렉토리에 target-triple 접미사 제거된 이름으로 배치됨.
        // macOS .app/Contents/MacOS/ieum-server, Windows: ieum-server.exe (main exe 옆).
        let mut sidecar = std::env::current_exe()?;
        sidecar.pop();
        sidecar.push(if cfg!(windows) { "ieum-server.exe" } else { "ieum-server" });

        log::info!("[sidecar] release spawn: {}", sidecar.display());

        let mut cmd = Command::new(&sidecar);
        cmd.stdout(Stdio::inherit()).stderr(Stdio::inherit());
        cmd.group_spawn()
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sidecar_state = PythonSidecar(Mutex::new(None));

    tauri::Builder::default()
        .manage(sidecar_state)
        // 시작프로그램 자동 등록 — Windows: HKCU\...\Run 레지스트리, macOS: ~/Library/LaunchAgents plist.
        // dev에선 enable 호출 안 함 — 개발 중에 시작프로그램 등록되면 곤란.
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            None,
        ))
        // macOS 기본 동작은 윈도우 close 시 앱이 dock에 잔존(메뉴바 마이크 인디케이터도 살아있음).
        // 운용 시나리오(autostart로 항상 실행)에선 윈도우 close = 앱 종료가 자연스러움.
        // exit(0) 호출이 RunEvent::Exit를 트리거 → sidecar 정리 코드까지 실행됨.
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                window.app_handle().exit(0);
            }
        })
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            } else {
                // release 첫 실행 시 자동 등록. enable()은 idempotent라 매번 호출해도 OK.
                let autostart = app.autolaunch();
                match autostart.enable() {
                    Ok(()) => log::info!("[autostart] 등록 완료 (enabled={:?})", autostart.is_enabled()),
                    Err(e) => log::error!("[autostart] 등록 실패: {}", e),
                }
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
