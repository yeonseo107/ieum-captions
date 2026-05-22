const captionsEl = document.getElementById('captions');
const inputEl = document.getElementById('caption-input');
const demoBtn = document.getElementById('demo-btn');
const resetBtn = document.getElementById('reset-btn');
const controlsEl = document.getElementById('controls');
const wsStatusEl = document.getElementById('ws-status');

// 히스토리 누적. 너무 많아지면 가장 오래된 줄부터 정리 (24h 거실 대화 기준 1000줄이면 ~3시간 분량).
// 단, 사용자가 위로 스크롤해 히스토리를 읽는 중에는 trim 안 함 — 스크롤 위치 점프 방지.
const MAX_LINES = 1000;
const ANIM_MS = 350;
const DEMO_INTERVAL_MS = 2500;
// 사용자가 바닥에서 이 거리(px) 안에 있으면 "라이브 모드"로 간주하고 새 자막 도착 시 자동 스크롤.
const SCROLL_STICK_THRESHOLD_PX = 80;

const lines = [];

function isAtBottom() {
  const dist = captionsEl.scrollHeight - captionsEl.scrollTop - captionsEl.clientHeight;
  return dist < SCROLL_STICK_THRESHOLD_PX;
}

function addCaption(text) {
  const trimmed = text.trim();
  if (!trimmed) return;

  // append 전에 라이브 모드였는지 기록 — append 후엔 scrollHeight가 늘어나 isAtBottom 판정이 바뀜.
  const wasAtBottom = isAtBottom();

  const line = document.createElement('div');
  line.className = 'caption-line';
  line.textContent = trimmed;
  captionsEl.appendChild(line);
  lines.push(line);

  requestAnimationFrame(() => line.classList.add('visible'));

  // 라이브 모드일 때만 오래된 줄 정리 + 자동 스크롤. 히스토리 읽는 중엔 둘 다 하지 않음.
  if (wasAtBottom) {
    while (lines.length > MAX_LINES) {
      lines.shift().remove();
    }
    // DOM 반영 직후 scrollHeight가 갱신된 시점에 스크롤.
    requestAnimationFrame(() => {
      captionsEl.scrollTop = captionsEl.scrollHeight;
    });
  }
}

function clearAll() {
  lines.forEach((l) => l.remove());
  lines.length = 0;
}

inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    addCaption(inputEl.value);
    inputEl.value = '';
  }
});

const DEMO_SEQUENCE = [
  '할머니, 안녕히 주무셨어요?',
  '오늘 날씨가 참 좋네요.',
  '약은 잘 챙겨 드셨어요?',
  '점심으로 김치찌개 어떠세요?',
  '비가 와서 우산 챙기셔야 해요.',
  '병원 예약은 내일 오전 열 시예요.',
  '차 한 잔 드릴까요?',
  '잠깐만 기다리세요.',
  'TV 소리가 작죠? 키워 드릴게요.',
];

let demoTimer = null;

demoBtn.addEventListener('click', () => {
  if (demoTimer !== null) {
    clearInterval(demoTimer);
    demoTimer = null;
    demoBtn.textContent = 'Demo 재생';
    return;
  }
  demoBtn.textContent = 'Demo 정지';
  let i = 0;
  const tick = () => {
    addCaption(DEMO_SEQUENCE[i % DEMO_SEQUENCE.length]);
    i += 1;
  };
  tick();
  demoTimer = setInterval(tick, DEMO_INTERVAL_MS);
});

resetBtn.addEventListener('click', clearAll);

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    controlsEl.classList.toggle('hidden');
    if (!controlsEl.classList.contains('hidden')) {
      inputEl.focus();
    }
  }
});

inputEl.focus();

// --- WebSocket 클라이언트 (M3: STT 백엔드 연결) ---
// backend/server.py가 떠 있으면 자동 연결, 없으면 2초마다 재시도. 수동 입력은 항상 동작.
const WS_URL = 'ws://localhost:8765';
const WS_RETRY_MS = 2000;
let wsConnected = false;

function setWSStatus(connected) {
  wsStatusEl.classList.toggle('connected', connected);
  wsStatusEl.classList.toggle('disconnected', !connected);
}

function connectWS() {
  const ws = new WebSocket(WS_URL);

  ws.addEventListener('open', () => {
    if (!wsConnected) console.log('[WS] STT 백엔드 연결됨');
    wsConnected = true;
    setWSStatus(true);
  });

  ws.addEventListener('message', (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === 'caption' && msg.text) {
        addCaption(msg.text);
      }
    } catch (err) {
      console.warn('[WS] 잘못된 메시지', e.data);
    }
  });

  ws.addEventListener('close', () => {
    if (wsConnected) console.log('[WS] 연결 끊김, 재연결 시도 중...');
    wsConnected = false;
    setWSStatus(false);
    setTimeout(connectWS, WS_RETRY_MS);
  });

  ws.addEventListener('error', () => {
    // 연결 실패는 close로 이어짐 — 별도 로그 안 함
  });
}

connectWS();
