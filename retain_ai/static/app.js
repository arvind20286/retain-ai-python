const wsUrl = (() => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/review`;
})();

const chatBox = document.getElementById('chatBox');
const statusEl = document.getElementById('status');
const statusLine = document.getElementById('statusLine');
const audioIndicator = document.getElementById('audioIndicator');
const connectBtn = document.getElementById('connectBtn');
const micBtn = document.getElementById('micBtn');
const sendBtn = document.getElementById('sendBtn');
const textInput = document.getElementById('textInput');
const syncBtn = document.getElementById('syncBtn');
const refreshDueBtn = document.getElementById('refreshDueBtn');
const dueSummary = document.getElementById('dueSummary');

let socket = null;
let micActive = false;
let audioContext = null;
let mediaStream = null;
let scriptNode = null;
let nextStartTime = 0;
let scheduledSources = [];

function addMessage(text, kind = 'bot') {
  const el = document.createElement('div');
  el.className = `message ${kind}`;
  el.textContent = text;
  chatBox.appendChild(el);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function setStatus(kind, text) {
  statusEl.className = `status ${kind}`;
  statusEl.textContent = text;
}

function ensureAudioContext() {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioContext.state === 'suspended') {
    audioContext.resume();
  }
  return audioContext;
}

function int16ToFloat32(int16Array) {
  const float32 = new Float32Array(int16Array.length);
  for (let i = 0; i < int16Array.length; i++) {
    float32[i] = int16Array[i] / 32768;
  }
  return float32;
}

function float32ToInt16(float32Array) {
  const int16 = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return int16;
}

function downsampleBuffer(buffer, inputRate, outputRate) {
  if (inputRate === outputRate) return buffer;

  const ratio = inputRate / outputRate;
  const outputLength = Math.floor(buffer.length / ratio);
  const output = new Float32Array(outputLength);

  for (let i = 0; i < outputLength; i++) {
    const position = i * ratio;
    const left = Math.floor(position);
    const fraction = position - left;
    const right = Math.min(left + 1, buffer.length - 1);
    output[i] = buffer[left] * (1 - fraction) + buffer[right] * fraction;
  }

  return output;
}

function playPcmAudio(buffer, sampleRate = 24000) {
  try {
    const ctx = ensureAudioContext();
    const bytes = new Uint8Array(buffer);
    const int16 = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
    const float32 = int16ToFloat32(int16);
    const audioBuffer = ctx.createBuffer(1, float32.length, sampleRate);
    audioBuffer.getChannelData(0).set(float32);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);

    const now = ctx.currentTime;
    nextStartTime = Math.max(now, nextStartTime);
    source.start(nextStartTime);
    nextStartTime += audioBuffer.duration;

    if (audioIndicator) audioIndicator.style.opacity = '1';
    scheduledSources.push(source);
    source.onended = () => {
      const idx = scheduledSources.indexOf(source);
      if (idx > -1) scheduledSources.splice(idx, 1);
      if (scheduledSources.length === 0 && audioIndicator) {
        audioIndicator.style.opacity = '0';
      }
    };
  } catch (error) {
    console.error('Failed to play audio response:', error);
  }
}

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    stopMic();
    socket.close();
    return;
  }

  setStatus('connecting', 'Connecting');
  statusLine.textContent = 'Opening Gemini Live session...';
  connectBtn.textContent = 'Disconnect';
  connectBtn.className = 'danger';

  socket = new WebSocket(wsUrl);
  socket.binaryType = 'arraybuffer';

  socket.onopen = () => {
    setStatus('connected', 'Connected');
    statusLine.textContent = 'Live session ready';
    addMessage('Connected to Gemini Live study partner. You can speak or type.', 'system');
  };

  socket.onmessage = (event) => {
    try {
      if (event.data instanceof ArrayBuffer) {
        playPcmAudio(event.data, 24000);
        return;
      }

      if (event.data instanceof Blob) {
        event.data.arrayBuffer().then((buf) => playPcmAudio(buf, 24000));
        return;
      }

      const msg = JSON.parse(event.data);
      if (msg.type === 'gemini' && msg.text) {
        addMessage(msg.text, 'bot');
      } else if (msg.type === 'grade') {
        addMessage(`Grading: ${msg.score}/100 — ${msg.feedback}`, 'grade');
      } else if (msg.type === 'card') {
        addMessage(`Question: ${msg.question}`, 'system');
      } else if (msg.type === 'turn_complete') {
        statusLine.textContent = 'Partner turn complete • Your turn to speak';
      } else if (msg.type === 'interaction_status') {
        statusLine.textContent = 'Ready for speech';
      } else if (msg.error) {
        addMessage(`Error: ${msg.error}`, 'system');
      }
    } catch (e) {
      console.log('Non-JSON message', event.data);
    }
  };

  socket.onclose = () => {
    setStatus('disconnected', 'Disconnected');
    statusLine.textContent = 'Session closed';
    connectBtn.textContent = 'Connect Live';
    connectBtn.className = 'primary';
    stopMic();
  };

  socket.onerror = (err) => {
    setStatus('error', 'Error');
    statusLine.textContent = 'Connection error';
    connectBtn.textContent = 'Connect Live';
    connectBtn.className = 'primary';
    stopMic();
  };
}

function sendText() {
  const text = textInput.value.trim();
  if (!text) return;
  ensureAudioContext();
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ text }));
    addMessage(text, 'user');
    textInput.value = '';
  } else {
    addMessage('Please connect first.', 'system');
  }
}

async function startMic() {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    addMessage('Connect live session before starting microphone.', 'system');
    return;
  }

  if (micActive) {
    stopMic();
    return;
  }

  try {
    const ctx = ensureAudioContext();
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate: 16000,
        echoCancellation: true,
        noiseSuppression: true,
      }
    });

    const source = ctx.createMediaStreamSource(mediaStream);
    scriptNode = ctx.createScriptProcessor(4096, 1, 1);

    scriptNode.onaudioprocess = (event) => {
      if (!micActive || !socket || socket.readyState !== WebSocket.OPEN) return;
      const input = event.inputBuffer.getChannelData(0);
      const mono16k = downsampleBuffer(input, ctx.sampleRate, 16000);
      const int16 = float32ToInt16(mono16k);
      socket.send(int16.buffer);
    };

    source.connect(scriptNode);
    const mutedOutput = ctx.createGain();
    mutedOutput.gain.value = 0;
    scriptNode.connect(mutedOutput);
    mutedOutput.connect(ctx.destination);

    micActive = true;
    micBtn.textContent = 'Stop Mic';
    micBtn.className = 'danger';
    statusLine.textContent = 'Mic live • Listening to your answer...';
  } catch (e) {
    console.error(e);
    addMessage('Microphone access failed. Please grant permission in browser.', 'system');
  }
}

function stopMic() {
  if (micActive && socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ audioStreamEnd: true }));
  }
  micActive = false;
  micBtn.textContent = 'Start Mic';
  micBtn.className = 'secondary';
  statusLine.textContent = 'Mic off';
  if (scriptNode) {
    scriptNode.disconnect();
    scriptNode = null;
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
  }
}

async function fetchDueCards() {
  try {
    const resp = await fetch('/api/cards/due');
    if (resp.ok) {
      const cards = await resp.json();
      dueSummary.textContent = `${cards.length} card(s) due for spaced review`;
    } else {
      dueSummary.textContent = 'Could not fetch due cards';
    }
  } catch (e) {
    dueSummary.textContent = 'Server offline';
  }
}

async function triggerSync() {
  syncBtn.disabled = true;
  syncBtn.textContent = 'Syncing...';
  try {
    const resp = await fetch('/api/sync', { method: 'POST' });
    const data = await resp.json();
    if (resp.ok) {
      addMessage(`Notion Sync complete: ${data.articles_synced || 0} articles synced, ${data.cards_generated || 0} cards generated.`, 'system');
      fetchDueCards();
    } else {
      addMessage(`Sync error: ${data.detail || 'Failed to sync'}`, 'system');
    }
  } catch (e) {
    addMessage(`Sync failed: ${e.message}`, 'system');
  } finally {
    syncBtn.disabled = false;
    syncBtn.textContent = 'Sync Notion';
  }
}

connectBtn.addEventListener('click', connect);
micBtn.addEventListener('click', startMic);
sendBtn.addEventListener('click', sendText);
textInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendText();
});
syncBtn.addEventListener('click', triggerSync);
refreshDueBtn.addEventListener('click', fetchDueCards);

// Initial check
fetchDueCards();

