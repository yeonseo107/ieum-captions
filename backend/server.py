"""ieum-captions M3 통합 서버: 마이크 → VAD segmentation → faster-whisper → WebSocket 푸시.

실행:
    source backend/.venv/bin/activate
    python backend/server.py

브라우저로 frontend/index.html 열면 자동 연결됨 (재시도 포함).
종료: Ctrl+C
"""
import asyncio
import collections
import json
import re
import sys
import time

import numpy as np
import sounddevice as sd
import webrtcvad
import websockets
from faster_whisper import WhisperModel

# 오디오 / 모델
SAMPLE_RATE = 16000
CHANNELS = 1
MODEL_SIZE = "medium"
COMPUTE_TYPE = "int8"

# VAD segmentation — 5초 고정 청크 대신 발화 단위로 잘라서 STT.
VAD_AGGRESSIVENESS = 3          # 0(느슨)~3(엄격). 카페 등 잡음 환경 견디려면 3.
FRAME_MS = 30                   # webrtcvad가 받는 프레임 길이 (10/20/30 중 30이 가장 안정)
SILENCE_END_MS = 600            # 침묵이 600ms 지속되면 발화 종료로 간주
MAX_UTTERANCE_MS = 15000        # 너무 긴 독백은 강제 컷 (그 안에서 한 번 끊고 다음 발화 계속)
MIN_UTTERANCE_MS = 800          # 이 이하 발화는 단발성 잡음으로 보고 STT 호출 자체 안 함
PREROLL_MS = 200                # 발화 시작 직전 200ms도 같이 transcribe (첫 음절 잘림 방지)
UTTERANCE_QUEUE_MAX = 2         # 큐가 이 이상 쌓이면 가장 오래된 발화 버림(잡음에 실 발화가 묻히는 것 방지)

FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
SILENCE_END_FRAMES = SILENCE_END_MS // FRAME_MS
MAX_UTTERANCE_FRAMES = MAX_UTTERANCE_MS // FRAME_MS
MIN_UTTERANCE_SAMPLES = SAMPLE_RATE * MIN_UTTERANCE_MS // 1000
PREROLL_FRAMES = PREROLL_MS // FRAME_MS

# 네트워크
WS_HOST = "localhost"
WS_PORT = 8765

# 평균 log probability가 이 임계 미만이면 환각으로 간주. 정상 발화는 보통 -0.6 이상,
# 환각/잡음은 -1.0 이하인 경향. 너무 빡빡하면 정상 발화도 폐기되니 보수적으로.
LOGPROB_THRESHOLD = -1.0

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
    "구독과 좋아요 부탁드립니다",
    "구독과 좋아요 부탁드립니다.",
    "좋아요와 구독 부탁드립니다",
    "좋아요와 구독 부탁드립니다.",
    "다음 영상에서 만나요",
    "다음 영상에서 만나요.",
    "다음 영상에서 뵙겠습니다",
    "다음 영상에서 뵙겠습니다.",
    "다음 영상에서 만납시다",
    "안녕히 계세요",
    "안녕히 계세요.",
    "이 영상은 유료 광고를 포함하고 있습니다",
    "이 영상은 유료 광고를 포함하고 있습니다.",
    "영상이 마음에 드셨다면 구독과 좋아요를 눌러주세요",
    "영상이 마음에 드셨다면 구독과 좋아요를 눌러주세요.",
    "Thanks for watching.",
    "Thank you.",
}

# 같은 글자가 8회 이상 연속되면 환각 (ㅋㅋㅋ, 크크크, 고고고 폭주 패턴).
_REPEATED_CHAR_PATTERN = re.compile(r"(.)\1{7,}")
# 같은 단어/구(2글자 이상)가 4회 이상 연속 반복 (예: "사회초가 사회초가 사회초가 사회초가").
_REPEATED_PHRASE_PATTERN = re.compile(r"(\S{2,})(?:\s+\1){3,}")


def _normalize_text(s: str) -> str:
    return s.strip().rstrip(".!?,。").strip().lower()


_HALLUCINATION_NORMALIZED = {_normalize_text(p) for p in _HALLUCINATION_PHRASES}


def _has_excessive_word_repetition(text: str) -> bool:
    """다단어 구절 폭주 감지. 8단어 이상에서 유니크 단어 비율이 낮으면 반복 패턴.

    예: "이 경기에서 가장 큰 차이로는" 25회 반복 → 5종 단어 / 125개 = 0.04
    """
    words = text.split()
    if len(words) < 8:
        return False
    return len(set(words)) / len(words) < 0.25


def is_hallucination(text: str) -> bool:
    norm = _normalize_text(text)
    if not norm:
        return True
    if norm in _HALLUCINATION_NORMALIZED:
        return True
    if _REPEATED_CHAR_PATTERN.search(text):
        return True
    if _REPEATED_PHRASE_PATTERN.search(text):
        return True
    if _has_excessive_word_repetition(text):
        return True
    return False


clients: set = set()


class VADSegmenter:
    """프레임을 흘려넣으면서 발화 시작/끝을 검출. 발화가 끝나면 float32 audio를 반환."""

    def __init__(self) -> None:
        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self.preroll: collections.deque = collections.deque(maxlen=PREROLL_FRAMES)
        self.utterance: list[np.ndarray] = []
        self.silence_count = 0
        self.in_speech = False

    def feed(self, frame_bytes: bytes) -> np.ndarray | None:
        is_speech = self.vad.is_speech(frame_bytes, SAMPLE_RATE)
        frame_f32 = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        if not self.in_speech:
            self.preroll.append(frame_f32)
            if is_speech:
                self.in_speech = True
                self.utterance = list(self.preroll)
                self.utterance.append(frame_f32)
                self.silence_count = 0
            return None

        # 발화 중
        self.utterance.append(frame_f32)
        self.silence_count = 0 if is_speech else self.silence_count + 1

        ended_by_silence = self.silence_count >= SILENCE_END_FRAMES
        ended_by_cap = len(self.utterance) >= MAX_UTTERANCE_FRAMES
        if ended_by_silence or ended_by_cap:
            audio = np.concatenate(self.utterance)
            self._reset()
            # 너무 짧은 발화는 단발성 잡음(기침, 식기 소리 등)일 가능성이 커서 STT 안 돌림.
            if len(audio) < MIN_UTTERANCE_SAMPLES:
                return None
            return audio
        return None

    def _reset(self) -> None:
        self.in_speech = False
        self.preroll.clear()
        self.utterance = []
        self.silence_count = 0


async def broadcast(message: dict) -> None:
    if not clients:
        return
    payload = json.dumps(message)
    await asyncio.gather(
        *(c.send(payload) for c in clients),
        return_exceptions=True,
    )


async def capture_and_segment(seg: VADSegmenter, utterance_q: asyncio.Queue) -> None:
    """마이크 스트림 → VAD segmenter → 발화가 끝날 때마다 utterance_q에 audio를 넣음."""
    loop = asyncio.get_running_loop()
    frame_q: asyncio.Queue = asyncio.Queue()

    def callback(indata, frames, time_info, status):
        if status:
            print(f"[mic] {status}", file=sys.stderr)
        # webrtcvad는 16-bit PCM bytes를 받음 — float32 [-1,1] → int16으로 변환.
        pcm = (indata[:, 0] * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
        loop.call_soon_threadsafe(frame_q.put_nowait, pcm)

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=FRAME_SAMPLES,
        callback=callback,
    )
    stream.start()
    print("[mic] 스트림 시작 (VAD segmentation 모드)")

    try:
        while True:
            frame = await frame_q.get()
            audio = seg.feed(frame)
            if audio is not None:
                duration = len(audio) / SAMPLE_RATE
                # 큐 가득 차면 가장 오래된 거 버리고 새 발화 우선 (잡음 누적으로 실 발화 지연되는 것 방지).
                while utterance_q.qsize() >= UTTERANCE_QUEUE_MAX:
                    try:
                        dropped = utterance_q.get_nowait()
                        dropped_dur = len(dropped) / SAMPLE_RATE
                        print(f"[큐] 누적으로 발화 폐기 — {dropped_dur:.2f}s")
                    except asyncio.QueueEmpty:
                        break
                print(f"[VAD] 발화 종료 — {duration:.2f}s")
                await utterance_q.put(audio)
    finally:
        stream.stop()
        stream.close()


async def transcribe_worker(model: WhisperModel, utterance_q: asyncio.Queue) -> None:
    """utterance_q에서 발화 audio를 꺼내 STT(직렬) → broadcast.

    캡처/세그멘터 코루틴과 분리되어 있어, transcribe 도중에도 다음 발화 검출은 계속 진행됨.
    """
    loop = asyncio.get_running_loop()

    def transcribe(audio: np.ndarray) -> tuple[str, float]:
        segs, _ = model.transcribe(
            audio,
            language="ko",
            # 이미 webrtcvad로 발화 단위로 잘랐으니 Silero VAD는 다시 안 돌림.
            vad_filter=False,
            # 이전 출력을 컨텍스트로 끌어다 쓰지 않음 — 환각 패턴 자기강화 방지.
            condition_on_previous_text=False,
            # 짧은 발화 + 잡음에서 기본 [0.0..1.0] temperature fallback이 6배 느려지게 하므로 단일값으로 고정.
            temperature=0.0,
            beam_size=1,
            # 자막 출력에 timestamp 안 쓰니 디코딩 비용 절감.
            without_timestamps=True,
            # 모델이 "이건 무음/잡음" 으로 판단하는 임계 — 잡음 audio에서 환각 출력 폐기 강화.
            no_speech_threshold=0.8,
        )
        seg_list = list(segs)
        text = " ".join(s.text.strip() for s in seg_list).strip()
        # segment별 avg_logprob을 길이 가중 평균. 환각은 보통 -1.0 미만으로 떨어짐.
        if seg_list:
            total_chars = sum(len(s.text) for s in seg_list) or 1
            avg_logprob = sum(s.avg_logprob * len(s.text) for s in seg_list) / total_chars
        else:
            avg_logprob = 0.0
        return text, avg_logprob

    while True:
        audio = await utterance_q.get()
        duration = len(audio) / SAMPLE_RATE

        t0 = time.perf_counter()
        text, avg_logprob = await loop.run_in_executor(None, transcribe, audio)
        elapsed = time.perf_counter() - t0

        if not text:
            continue
        if is_hallucination(text):
            print(f"[필터] {text!r} (환각 후보)")
            continue
        if avg_logprob < LOGPROB_THRESHOLD:
            print(f"[필터] {text!r} (logprob {avg_logprob:.2f} < {LOGPROB_THRESHOLD})")
            continue

        rtf = elapsed / duration if duration > 0 else 0.0
        print(f"[STT] {text}  (발화 {duration:.2f}s, 처리 {elapsed:.2f}s, RTF {rtf:.2f}, logprob {avg_logprob:.2f})")
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

    seg = VADSegmenter()
    utterance_q: asyncio.Queue = asyncio.Queue()

    async with websockets.serve(handle_client, WS_HOST, WS_PORT):
        await asyncio.gather(
            capture_and_segment(seg, utterance_q),
            transcribe_worker(model, utterance_q),
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n종료합니다.")
        sys.exit(0)
