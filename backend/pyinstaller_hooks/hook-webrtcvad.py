# PyInstaller hook override.
#
# 표준 hook(_pyinstaller_hooks_contrib)이 `copy_metadata('webrtcvad')`를 호출하는데
# 우리는 prebuilt wheel 패키지(`webrtcvad-wheels`)로 설치해서 dist 이름이 다름 → metadata 못 찾고 실패.
# 또 webrtcvad.py가 top-level의 C extension `_webrtcvad`를 import하는데 PyInstaller 자동 분석이
# top-level .so를 못 잡아서 frozen 바이너리에서 ModuleNotFoundError 남.
import os

from PyInstaller.utils.hooks import copy_metadata

try:
    datas = copy_metadata("webrtcvad-wheels")
except Exception:
    datas = []

# `_webrtcvad`는 패키지가 아니라 site-packages에 단독으로 놓인 C extension이라
# collect_dynamic_libs가 못 잡음 → import해서 __file__ 경로를 직접 binaries에 추가.
hiddenimports = ["_webrtcvad"]
binaries = []
try:
    import _webrtcvad

    binaries.append((_webrtcvad.__file__, "."))
except ImportError:
    pass
