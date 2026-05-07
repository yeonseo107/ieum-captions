# ieum-captions

한국어 발화를 실시간으로 자막화해 화면에 누적 표시하는 데스크톱 앱.
청각이 불편한 사용자의 일상 대화 보조를 일차 목적으로 설계되었습니다.

- 마이크 입력 → VAD 기반 발화 단위 분리 → faster-whisper 한국어 STT → WebSocket → Tauri Webview 자막 UI
- macOS / Windows 단일 인스톨러 배포 — Python 런타임 사전 설치 불필요
- 시작프로그램 자동 등록으로 PC 부팅 시 자동 실행

## 주요 기능

- **실시간 한국어 STT**: `faster-whisper` (int8 양자화, medium 모델 기본)
- **VAD 발화 단위 segmentation**: 고정 청크 대신 `webrtcvad`로 발화 종료 시점에 즉시 처리. 발화 길이에 비례한 지연만 발생.
- **다층 환각 가드**: 한국어 Whisper의 알려진 환각 패턴 차단
  - 끝맺음·광고 멘트 phrase 화이트리스트
  - 같은 글자/단어/구절 반복 정규식
  - 다단어 구절의 unique-ratio 검사
  - segment 평균 logprob 임계 컷
- **누적형 자막 UI**: 새 발화는 하단에 추가, 이전 줄 위치 유지. 최대 줄 수 도달 시 가장 오래된 줄만 ease-out 페이드아웃.
- **시작프로그램 자동 등록**: Windows 레지스트리 `HKCU\...\Run` / macOS LaunchAgent
- **종료 시 자식 프로세스 트리 정리**: process group(Unix) / JobObject(Windows)로 묶어 좀비 방지

## 아키텍처

```
┌─────────────────────────────────────────────┐
│ Tauri 2 (Rust)                              │
│  ┌─ Webview ──────────────────────────────┐ │
│  │ frontend/ (Vanilla HTML/CSS/JS)        │ │
│  │  • WebSocket client (auto-reconnect)   │ │
│  │  • 자막 큐 + 페이드 트랜지션          │ │
│  └────────────────────────────────────────┘ │
│                    ▲                        │
│                    │ ws://localhost:8765    │
│  ┌─ sidecar ───────┴──────────────────────┐ │
│  │ backend/server.py (PyInstaller bundle) │ │
│  │  • sounddevice 마이크 캡처             │ │
│  │  • webrtcvad 발화 segmentation         │ │
│  │  • faster-whisper 한국어 STT           │ │
│  │  • 환각 필터 (다층 가드)               │ │
│  │  • websockets 브로드캐스트             │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

## 기술 스택

| 영역 | 도구 |
|---|---|
| 데스크톱 셸 | Tauri 2 (Rust) |
| STT 엔진 | faster-whisper (CTranslate2 백엔드) |
| 오디오 | sounddevice (PortAudio), webrtcvad |
| IPC | WebSocket (`websockets` 라이브러리) |
| 프론트엔드 | Vanilla HTML/CSS/JS (빌드 도구 없음) |
| 패키징 | PyInstaller (sidecar) + Tauri externalBin |
| CI | GitHub Actions (macOS / Windows 매트릭스) |

## 디렉토리 구조

```
.
├── backend/
│   ├── server.py              # STT + WebSocket 서버
│   ├── ieum-server.spec       # PyInstaller spec
│   ├── pyinstaller_hooks/     # webrtcvad C extension hook
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── src-tauri/
│   ├── src/lib.rs             # sidecar spawn + autostart + 종료 정리
│   ├── tauri.conf.json
│   ├── Cargo.toml
│   └── binaries/              # PyInstaller 산출물 배치 위치 (gitignored)
└── .github/workflows/build.yml
```

## 개발 환경 셋업

요구 사항: macOS (Apple Silicon 기준 검증) / Python 3.12 / Rust stable

```bash
# 백엔드 가상환경
python3.12 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt

# Tauri 개발 모드 (Python sidecar 자동 spawn, 코드 수정 즉시 반영)
cargo tauri dev
```

`cargo tauri dev`는 debug 빌드에서 `backend/.venv`의 Python 인터프리터로 `server.py`를 직접 실행합니다.
PyInstaller 빌드는 release 빌드 / 배포 인스톨러용으로만 사용됩니다.

## 배포 빌드

GitHub Actions 워크플로우(`.github/workflows/build.yml`)가 macOS / Windows 매트릭스로 실행:

1. `actions/setup-python@v5` + `pip install -r backend/requirements.txt`
2. `pyinstaller backend/ieum-server.spec` → 단일 실행 파일
3. 산출물을 `src-tauri/binaries/ieum-server-{target-triple}{.exe}` 이름으로 이동
4. `tauri-action`이 `externalBin`으로 픽업해 메인 앱 옆에 번들

수동 트리거: GitHub Actions 탭 → **Build** → **Run workflow**

산출물:
- macOS: `.dmg` / `.app` (Apple Silicon)
- Windows: `.msi` / NSIS `.exe`

## 자막 표시 정책

- **누적형**: 한 화면에 여러 발화가 동시에 떠 있음. 새 발화는 하단에 페이드 인.
- **글자 크기 자동 축소 안 함**: 가독성 우선. viewport 대응은 CSS `clamp()`만.
- **줄 초과 시 가장 오래된 줄만** ease-out 페이드아웃 (250–400ms).
- **공백 없는 긴 문자열 wrap**: `word-break: keep-all` + `overflow-wrap: anywhere`. 한국어 단어 보존하면서 viewport 초과 시 강제 줄바꿈.

## 환각 가드

한국어 Whisper에서 관찰되는 환각 5종에 대해 각각 가드를 둠:

| 유형 | 예시 | 가드 |
|---|---|---|
| 끝맺음·광고 멘트 | "감사합니다.", "구독 부탁드립니다.", "이 영상은 유료 광고를…" | phrase 화이트리스트 (정확/정규화 매치) |
| 한 글자 반복 | "ㅋㅋㅋㅋㅋㅋㅋㅋ", "오오오오오오오오" | 정규식 `(.)\1{7,}` |
| 같은 단어/구 반복 | "X X X X" 4회+ | 정규식 `(\S{2,})(?:\s+\1){3,}` |
| 다단어 구절 폭주 | "A B C D A B C D …" 25회+ | unique-ratio < 0.25 |
| 신종/잡음 환각 | 한 글자 "끝", "오!" 등 | segment 평균 logprob < 임계 |

추가로 발화 단위에서:
- 최소 발화 길이 미달(800ms 이하) → STT 호출 자체 스킵 (단발성 잡음)
- utterance 큐 가득 차면 가장 오래된 발화 폐기 (잡음 누적으로 실 발화 묻히는 것 방지)

## 의존성 메모

- **모델 가중치 (~1.5GB)**: 첫 실행 시 `~/.cache/huggingface/hub/`에 자동 다운로드. 첫 실행 시 인터넷 필수.
- **macOS arm64 PortAudio**: sounddevice가 universal2 wheel 사용. 빌드 환경에서 wheel 부재 시 `brew install portaudio` 필요.
- **Windows webrtcvad**: prebuilt `webrtcvad-wheels` 사용 (소스 컴파일 회피).

## 라이선스

[MIT](LICENSE)
