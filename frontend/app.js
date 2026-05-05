const captionsEl = document.getElementById('captions');
const inputEl = document.getElementById('caption-input');
const demoBtn = document.getElementById('demo-btn');
const resetBtn = document.getElementById('reset-btn');
const controlsEl = document.getElementById('controls');

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
    const oldest = lines.shift();
    // 명시적 픽셀값으로 height을 고정한 뒤 .removing이 0으로 트랜지션하게 함.
    // (max-height 보간이 브라우저에서 매끄럽지 않아 덜컹거림이 발생.)
    oldest.style.height = oldest.offsetHeight + 'px';
    oldest.getBoundingClientRect();
    oldest.classList.add('removing');
    setTimeout(() => oldest.remove(), ANIM_MS + 50);
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
