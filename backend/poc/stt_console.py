"""ieum-captions M1 PoC: 마이크 → faster-whisper → 콘솔.

실행:
    python backend/poc/stt_console.py

첫 실행 시 모델 다운로드(약 1.5GB)에 시간이 걸릴 수 있습니다.
종료: Ctrl+C
"""
import sys
import time

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
CHANNELS = 1
DURATION_SEC = 5
MODEL_SIZE = "large-v3-turbo"
COMPUTE_TYPE = "int8"

# RMS 진폭이 이 값 미만이면 침묵으로 간주하고 STT 호출을 건너뜀.
# (Whisper가 무음에 대해 "다음 영상에서 만나요" 같은 환각을 내는 문제 회피.)
SILENCE_RMS_THRESHOLD = 0.01


def record(duration: int) -> np.ndarray:
    print(f"\n[녹음] {duration}초간 말씀해주세요...")
    audio = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
    )
    sd.wait()
    return audio.flatten()


def is_silent(audio: np.ndarray, threshold: float = SILENCE_RMS_THRESHOLD) -> bool:
    return float(np.sqrt(np.mean(audio ** 2))) < threshold


def main() -> None:
    print(f"[모델 로드] {MODEL_SIZE} ({COMPUTE_TYPE})")
    model = WhisperModel(MODEL_SIZE, compute_type=COMPUTE_TYPE)
    print("[준비 완료] 반복 녹음/인식. 종료는 Ctrl+C.")

    while True:
        try:
            audio = record(DURATION_SEC)
        except KeyboardInterrupt:
            print("\n종료합니다.")
            sys.exit(0)

        if is_silent(audio):
            print("[침묵] 인식 건너뜀")
            continue

        t0 = time.perf_counter()
        segments, _ = model.transcribe(
            audio,
            language="ko",
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        text = " ".join(seg.text.strip() for seg in segments)
        elapsed = time.perf_counter() - t0
        rtf = elapsed / DURATION_SEC

        print(f"\n[결과] {text or '(음성 없음)'}")
        print(f"[지연] {elapsed:.2f}s | RTF {rtf:.2f}\n")


if __name__ == "__main__":
    main()
