"""ieum-captions M3 통합 서버: 마이크 → faster-whisper → WebSocket 푸시.

실행:
    source backend/.venv/bin/activate
    python backend/server.py

브라우저로 frontend/index.html 열면 자동 연결됨 (재시도 포함).
종료: Ctrl+C
"""
import asyncio
import json
import sys
import time

import numpy as np
import sounddevice as sd
import websockets
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
CHANNELS = 1
DURATION_SEC = 5
MODEL_SIZE = "large-v3-turbo"
COMPUTE_TYPE = "int8"
SILENCE_RMS_THRESHOLD = 0.01

WS_HOST = "localhost"
WS_PORT = 8765

# Whisper가 무음/잡음에 자주 출력하는 환각 문구.
# 전체 출력이 정확히 이 중 하나일 때만 필터 (긴 발화 안에 같은 단어가 들어 있을 수 있어 부분 매치는 X).
_HALLUCINATION_PHRASES = {
    "감사합니다",
    "감사합니다.",
    "시청해주셔서 감사합니다",
    "시청해주셔서 감사합니다.",
    "시청해 주셔서 감사합니다.",
    "구독 부탁드립니다",
    "구독 부탁드립니다.",
    "구독해주세요",
    "구독해주세요.",
    "다음 영상에서 만나요",
    "다음 영상에서 만나요.",
    "다음 영상에서 뵙겠습니다",
    "다음 영상에서 뵙겠습니다.",
    "다음 영상에서 만납시다",
    "안녕히 계세요",
    "안녕히 계세요.",
    "Thanks for watching.",
    "Thank you.",
}


def _normalize_text(s: str) -> str:
    return s.strip().rstrip(".!?,。").strip().lower()


_HALLUCINATION_NORMALIZED = {_normalize_text(p) for p in _HALLUCINATION_PHRASES}


def is_hallucination(text: str) -> bool:
    norm = _normalize_text(text)
    return not norm or norm in _HALLUCINATION_NORMALIZED


clients: set = set()


def record(duration: int) -> np.ndarray:
    audio = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
    )
    sd.wait()
    return audio.flatten()


def is_silent(audio: np.ndarray) -> bool:
    return float(np.sqrt(np.mean(audio ** 2))) < SILENCE_RMS_THRESHOLD


async def broadcast(message: dict) -> None:
    if not clients:
        return
    payload = json.dumps(message)
    await asyncio.gather(
        *(c.send(payload) for c in clients),
        return_exceptions=True,
    )


async def stt_loop(model: WhisperModel) -> None:
    loop = asyncio.get_running_loop()
    print("[STT] 루프 시작. 마이크 입력 대기 중.")
    while True:
        audio = await loop.run_in_executor(None, record, DURATION_SEC)
        if is_silent(audio):
            continue

        def transcribe() -> str:
            segs, _ = model.transcribe(
                audio,
                language="ko",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
                # 이전 출력을 컨텍스트로 끌어다 쓰지 않음 — 환각 패턴 자기강화 방지.
                condition_on_previous_text=False,
            )
            return " ".join(s.text.strip() for s in segs)

        t0 = time.perf_counter()
        text = await loop.run_in_executor(None, transcribe)
        elapsed = time.perf_counter() - t0
        if not text:
            continue
        if is_hallucination(text):
            print(f"[필터] {text!r} (환각 후보)")
            continue

        rtf = elapsed / DURATION_SEC
        print(f"[STT] {text}  (지연 {elapsed:.2f}s, RTF {rtf:.2f})")
        await broadcast({"type": "caption", "text": text})


async def handle_client(websocket) -> None:
    clients.add(websocket)
    print(f"[WS] 클라이언트 연결 ({len(clients)}개)")
    try:
        async for _ in websocket:
            pass
    finally:
        clients.discard(websocket)
        print(f"[WS] 클라이언트 끊김 ({len(clients)}개)")


async def main() -> None:
    print(f"[모델 로드] {MODEL_SIZE} ({COMPUTE_TYPE})")
    model = WhisperModel(MODEL_SIZE, compute_type=COMPUTE_TYPE)
    print(f"[WS 서버] ws://{WS_HOST}:{WS_PORT}")

    async with websockets.serve(handle_client, WS_HOST, WS_PORT):
        await stt_loop(model)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n종료합니다.")
        sys.exit(0)
