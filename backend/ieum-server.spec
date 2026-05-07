# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=['pyinstaller_hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'pandas',
        'scipy',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ieum-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Windows에서 sidecar 실행 시 cmd 창이 같이 뜨고, 그 창을 닫으면 sidecar 프로세스도 같이 죽어
    # WebSocket 연결까지 끊기는 문제. windowed mode로 변경 (Windows에서 console 미생성).
    # 부수효과: Windows에선 stdout/stderr이 NULL로 가서 print 로그가 안 보임. 디버깅 필요 시
    # 별도 파일 로깅 추가. macOS는 console 옵션 무관 — Tauri stdout inherit으로 그대로 보임.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
