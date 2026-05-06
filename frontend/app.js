const captionsEl = document.getElementById('captions');
const inputEl = document.getElementById('caption-input');
const demoBtn = document.getElementById('demo-btn');
const resetBtn = document.getElementById('reset-btn');
const controlsEl = document.getElementById('controls');
const wsStatusEl = document.getElementById('ws-status');

const MAX_LINES = 5;
const ANIM_MS = 350;
const DEMO_INTERVAL_MS = 2500;

const lines = [];

function addCaption(text) {
  const trimmed = text.trim();
  if (!trimmed) return;

  const line = document.createElement('div');
  line.className = 'caption-line';
  line.textContent = trimmed;
  captionsEl.appendChild(line);
  lines.push(line);

  requestAnimationFrame(() => line.classList.add('visible'));

  if (lines.length > MAX_LINES) {
    // 가장 오래된 줄은 즉시 DOM에서 제거. 위로 미는 애니메이션 없음 — 남은 줄들은 한 프레임 안에 새 위치로 스냅.
    lines.shift().remove();
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
