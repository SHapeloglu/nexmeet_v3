/* ─── NexMeet — WebRTC Video Conference ─── */

'use strict';

// ─── State ───────────────────────────────────────────────────────────────────
const state = {
  localStream: null,
  screenStream: null,
  peers: {},           // peerId -> { pc: RTCPeerConnection, audioEnabled, videoEnabled }
  roomId: null,
  peerId: null,
  userName: null,
  ws: null,
  micEnabled: true,
  camEnabled: true,
  screenSharing: false,
  recording: false,
  mediaRecorder: null,
  recordedChunks: [],
  chatOpen: false,
  unreadMessages: 0,
  meetingStartTime: null,
  timerInterval: null,
};

// ─── ICE Config ──────────────────────────────────────────────────────────────
const ICE_CONFIG = {
  iceServers: [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
    { urls: 'stun:stun2.l.google.com:19302' },
  ]
};

// ─── Lobby ───────────────────────────────────────────────────────────────────
async function initLobby() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    document.getElementById('previewVideo').srcObject = stream;
    state.localStream = stream;
  } catch (e) {
    console.warn('Camera/Mic unavailable:', e);
  }

  document.getElementById('previewMicBtn').addEventListener('click', () => {
    state.micEnabled = !state.micEnabled;
    if (state.localStream) {
      state.localStream.getAudioTracks().forEach(t => t.enabled = state.micEnabled);
    }
    document.getElementById('previewMicBtn').textContent = state.micEnabled ? '🎤' : '🔇';
  });

  document.getElementById('previewCamBtn').addEventListener('click', () => {
    state.camEnabled = !state.camEnabled;
    if (state.localStream) {
      state.localStream.getVideoTracks().forEach(t => t.enabled = state.camEnabled);
    }
    document.getElementById('previewCamBtn').textContent = state.camEnabled ? '📷' : '🚫';
  });

  document.getElementById('joinBtn').addEventListener('click', joinMeeting);
  document.getElementById('roomInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') joinMeeting();
  });
  document.getElementById('username').addEventListener('keydown', e => {
    if (e.key === 'Enter') joinMeeting();
  });
}

async function joinMeeting() {
  const nameInput = document.getElementById('username').value.trim();
  const roomInput = document.getElementById('roomInput').value.trim();

  if (!nameInput) {
    showToast('Lütfen adınızı girin.');
    document.getElementById('username').focus();
    return;
  }

  state.userName = nameInput;
  state.roomId = roomInput || generateId(8);
  state.peerId = generateId(12);

  // Ensure we have a stream
  if (!state.localStream) {
    try {
      state.localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    } catch (e) {
      // Try audio only
      try {
        state.localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e2) {
        console.warn('No media available');
        state.localStream = new MediaStream();
      }
    }
  }

  // Apply initial states
  state.localStream.getAudioTracks().forEach(t => t.enabled = state.micEnabled);
  state.localStream.getVideoTracks().forEach(t => t.enabled = state.camEnabled);

  showScreen('meeting');
  initMeetingUI();
  connectWebSocket();
}

// ─── Meeting UI ──────────────────────────────────────────────────────────────
function initMeetingUI() {
  document.getElementById('roomIdDisplay').textContent = state.roomId;

  // Add local video
  addVideoTile('local', state.localStream, state.userName + ' (Sen)', true);

  // Controls
  document.getElementById('micBtn').addEventListener('click', toggleMic);
  document.getElementById('camBtn').addEventListener('click', toggleCam);
  document.getElementById('screenBtn').addEventListener('click', toggleScreen);
  document.getElementById('recordBtn').addEventListener('click', toggleRecording);
  document.getElementById('chatBtn').addEventListener('click', toggleChat);
  document.getElementById('closeChatBtn').addEventListener('click', toggleChat);
  document.getElementById('filesBtn').addEventListener('click', toggleFiles);
  document.getElementById('closeFilesBtn').addEventListener('click', toggleFiles);
  document.getElementById('leaveBtn').addEventListener('click', leaveMeeting);
  document.getElementById('copyRoomBtn').addEventListener('click', copyRoomId);
  document.getElementById('sendChatBtn').addEventListener('click', sendChat);
  document.getElementById('chatInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') sendChat();
  });

  // Update initial button states
  updateMicBtn();
  updateCamBtn();

  // Remote control
  initRemoteControl();

  // Start timer
  state.meetingStartTime = Date.now();
  state.timerInterval = setInterval(updateTimer, 1000);
}

function updateTimer() {
  const elapsed = Math.floor((Date.now() - state.meetingStartTime) / 1000);
  const h = String(Math.floor(elapsed / 3600)).padStart(2, '0');
  const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');
  document.getElementById('meetingTimer').textContent = `${h}:${m}:${s}`;
}

// ─── WebSocket Signaling ─────────────────────────────────────────────────────
function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${proto}://${location.host}/ws/${state.roomId}/${state.peerId}?name=${encodeURIComponent(state.userName)}`;
  state.ws = new WebSocket(url);

  state.ws.onopen = () => {
    console.log('WS connected');
  };

  state.ws.onmessage = async (event) => {
    const msg = JSON.parse(event.data);
    await handleSignal(msg);
  };

  state.ws.onclose = () => {
    console.log('WS disconnected');
    showToast('Sunucu bağlantısı kesildi.');
  };

  state.ws.onerror = (e) => {
    console.error('WS error:', e);
  };
}

function sendSignal(data) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(data));
  }
}

async function handleSignal(msg) {
  const { type, from, from_name } = msg;

  switch (type) {
    case 'room-joined': {
      // We joined — create offers to all existing peers
      for (const peer of msg.peers) {
        await createPeerConnection(peer.id, peer.name, true);
      }
      break;
    }
    case 'peer-joined': {
      // New peer joined — they will send us an offer; create PC ready to receive
      addSystemMessage(`${from_name} toplantıya katıldı`);
      updateParticipantCount();
      // The new peer will initiate offers to us
      if (!state.peers[from]) {
        await createPeerConnection(from, from_name, false);
      }
      break;
    }
    case 'peer-left': {
      removePeer(msg.peer_id);
      addSystemMessage(`${msg.name} toplantıdan ayrıldı`);
      updateParticipantCount();
      break;
    }
    case 'offer': {
      await handleOffer(from, from_name, msg);
      break;
    }
    case 'answer': {
      await handleAnswer(from, msg);
      break;
    }
    case 'ice-candidate': {
      await handleIceCandidate(from, msg);
      break;
    }
    case 'chat': {
      receiveChatMessage(msg);
      break;
    }
    case 'screen-share-started': {
      showToast(`${from_name} ekran paylaşımına başladı`);
      markTileScreenShare(from, true);
      break;
    }
    case 'screen-share-stopped': {
      markTileScreenShare(from, false);
      break;
    }
    case 'media-state': {
      updateRemoteMediaState(from, msg.audio, msg.video);
      break;
    }
    case 'recording-started': {
      showToast(`${from_name} kaydı başlattı`);
      break;
    }
    case 'recording-stopped': {
      showToast(`${msg.from} kaydı durdurdu`);
      break;
    }
    case 'file-shared': {
      receiveFileNotification(msg);
      break;
    }
    case 'control-request': {
      onControlRequest(msg);
      break;
    }
    case 'control-response': {
      if (msg.approved) onControlApproved(msg.session_id);
      else onControlDenied();
      break;
    }
    case 'remote-frame': {
      onRemoteFrame(msg);
      break;
    }
    case 'remote-disconnected': {
      if (remote.isViewing) stopRemoteControl();
      showToast('Ajan bağlantısı kesildi.');
      break;
    }
  }
}

// ─── WebRTC Peer Connections ─────────────────────────────────────────────────
async function createPeerConnection(peerId, peerName, initiator) {
  const pc = new RTCPeerConnection(ICE_CONFIG);
  state.peers[peerId] = { pc, name: peerName, audioEnabled: true, videoEnabled: true };

  // Add local tracks
  if (state.localStream) {
    state.localStream.getTracks().forEach(track => {
      pc.addTrack(track, state.localStream);
    });
  }

  // ICE candidates
  pc.onicecandidate = (e) => {
    if (e.candidate) {
      sendSignal({ type: 'ice-candidate', target: peerId, candidate: e.candidate });
    }
  };

  // Remote stream
  pc.ontrack = (e) => {
    const stream = e.streams[0];
    if (!document.getElementById(`tile-${peerId}`)) {
      addVideoTile(peerId, stream, peerName, false);
    } else {
      const video = document.querySelector(`#tile-${peerId} video`);
      if (video && video.srcObject !== stream) video.srcObject = stream;
    }
  };

  pc.onconnectionstatechange = () => {
    console.log(`Peer ${peerId} connection: ${pc.connectionState}`);
    if (pc.connectionState === 'disconnected' || pc.connectionState === 'failed') {
      removePeer(peerId);
    }
  };

  if (initiator) {
    const offer = await pc.createOffer({ offerToReceiveAudio: true, offerToReceiveVideo: true });
    await pc.setLocalDescription(offer);
    sendSignal({ type: 'offer', target: peerId, sdp: pc.localDescription });
  }

  updateParticipantCount();
  return pc;
}

async function handleOffer(fromId, fromName, msg) {
  if (!state.peers[fromId]) {
    await createPeerConnection(fromId, fromName, false);
  }
  const { pc } = state.peers[fromId];
  await pc.setRemoteDescription(new RTCSessionDescription(msg.sdp));
  const answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);
  sendSignal({ type: 'answer', target: fromId, sdp: pc.localDescription });
}

async function handleAnswer(fromId, msg) {
  const peer = state.peers[fromId];
  if (peer) {
    await peer.pc.setRemoteDescription(new RTCSessionDescription(msg.sdp));
  }
}

async function handleIceCandidate(fromId, msg) {
  const peer = state.peers[fromId];
  if (peer && msg.candidate) {
    try {
      await peer.pc.addIceCandidate(new RTCIceCandidate(msg.candidate));
    } catch (e) {
      console.warn('ICE candidate error:', e);
    }
  }
}

function removePeer(peerId) {
  if (state.peers[peerId]) {
    state.peers[peerId].pc.close();
    delete state.peers[peerId];
  }
  const tile = document.getElementById(`tile-${peerId}`);
  if (tile) tile.remove();
  updateGrid();
  updateParticipantCount();
}

// ─── Video Grid ──────────────────────────────────────────────────────────────
function addVideoTile(peerId, stream, name, isLocal) {
  const grid = document.getElementById('videoGrid');
  const existing = document.getElementById(`tile-${peerId}`);
  if (existing) { existing.remove(); }

  const tile = document.createElement('div');
  tile.className = `video-tile${isLocal ? ' local' : ''}`;
  tile.id = `tile-${peerId}`;

  const video = document.createElement('video');
  video.autoplay = true;
  video.playsInline = true;
  if (isLocal) video.muted = true;
  video.srcObject = stream;

  // Video off overlay
  const overlay = document.createElement('div');
  overlay.className = 'video-off-overlay';
  overlay.style.display = 'none';
  const avatar = document.createElement('div');
  avatar.className = 'avatar-circle';
  avatar.textContent = name.charAt(0).toUpperCase();
  overlay.appendChild(avatar);

  // Name label
  const label = document.createElement('div');
  label.className = 'tile-name';
  label.innerHTML = `<span>${name}</span>`;
  label.id = `name-${peerId}`;

  tile.appendChild(video);
  tile.appendChild(overlay);
  tile.appendChild(label);
  grid.appendChild(tile);

  updateGrid();
}

function updateGrid() {
  const grid = document.getElementById('videoGrid');
  const tiles = grid.querySelectorAll('.video-tile');
  const count = tiles.length;
  grid.className = 'video-grid';
  if (count === 1) grid.classList.add('count-1');
  else if (count === 2) grid.classList.add('count-2');
  else if (count === 3) grid.classList.add('count-3');
  else if (count === 4) grid.classList.add('count-4');
  else if (count <= 6) grid.classList.add(`count-${count}`);
  else grid.classList.add('count-many');
}

function updateRemoteMediaState(peerId, audioEnabled, videoEnabled) {
  const tile = document.getElementById(`tile-${peerId}`);
  if (!tile) return;
  const video = tile.querySelector('video');
  const overlay = tile.querySelector('.video-off-overlay');
  const label = tile.querySelector('.tile-name');

  if (videoEnabled === false) {
    overlay.style.display = 'flex';
    video.style.display = 'none';
  } else {
    overlay.style.display = 'none';
    video.style.display = 'block';
  }

  // Muted icon
  const mutedIcon = label.querySelector('.muted-icon');
  if (audioEnabled === false) {
    if (!mutedIcon) label.insertAdjacentHTML('beforeend', '<span class="muted-icon">🔇</span>');
  } else {
    if (mutedIcon) mutedIcon.remove();
  }
}

function markTileScreenShare(peerId, active) {
  const tile = document.getElementById(`tile-${peerId}`);
  if (!tile) return;
  tile.classList.toggle('screen-share', active);
}

// ─── Controls ────────────────────────────────────────────────────────────────
function toggleMic() {
  state.micEnabled = !state.micEnabled;
  state.localStream?.getAudioTracks().forEach(t => t.enabled = state.micEnabled);
  updateMicBtn();
  broadcastMediaState();
}

function updateMicBtn() {
  const btn = document.getElementById('micBtn');
  const slash = document.getElementById('micOff');
  btn.classList.toggle('active', state.micEnabled);
  slash.style.display = state.micEnabled ? 'none' : 'block';
}

function toggleCam() {
  state.camEnabled = !state.camEnabled;
  state.localStream?.getVideoTracks().forEach(t => t.enabled = state.camEnabled);
  updateCamBtn();
  broadcastMediaState();

  // Show/hide own overlay
  const tile = document.getElementById('tile-local');
  if (tile) {
    tile.querySelector('video').style.display = state.camEnabled ? 'block' : 'none';
    tile.querySelector('.video-off-overlay').style.display = state.camEnabled ? 'none' : 'flex';
  }
}

function updateCamBtn() {
  const btn = document.getElementById('camBtn');
  const slash = document.getElementById('camOff');
  btn.classList.toggle('active', state.camEnabled);
  slash.style.display = state.camEnabled ? 'none' : 'block';
}

function broadcastMediaState() {
  sendSignal({ type: 'media-state', audio: state.micEnabled, video: state.camEnabled });
}

async function toggleScreen() {
  if (!state.screenSharing) {
    try {
      state.screenStream = await navigator.mediaDevices.getDisplayMedia({
        video: { cursor: 'always' },
        audio: true
      });
      state.screenSharing = true;

      const screenTrack = state.screenStream.getVideoTracks()[0];

      // Replace video track in all peer connections
      for (const peerId in state.peers) {
        const sender = state.peers[peerId].pc.getSenders()
          .find(s => s.track?.kind === 'video');
        if (sender) sender.replaceTrack(screenTrack);
      }

      // Update local tile
      const localTile = document.getElementById('tile-local');
      if (localTile) {
        const video = localTile.querySelector('video');
        const combinedStream = new MediaStream([
          screenTrack,
          ...(state.localStream?.getAudioTracks() || [])
        ]);
        video.srcObject = combinedStream;
        localTile.classList.add('screen-share');
      }

      screenTrack.onended = () => stopScreenShare();

      document.getElementById('screenBtn').classList.add('screen-on');
      sendSignal({ type: 'screen-share-started' });
      showToast('Ekran paylaşımı başladı');
    } catch (e) {
      if (e.name !== 'NotAllowedError') console.error('Screen share error:', e);
    }
  } else {
    stopScreenShare();
  }
}

function stopScreenShare() {
  if (!state.screenSharing) return;
  state.screenSharing = false;

  state.screenStream?.getTracks().forEach(t => t.stop());
  state.screenStream = null;

  // Restore camera track
  const camTrack = state.localStream?.getVideoTracks()[0];
  if (camTrack) {
    for (const peerId in state.peers) {
      const sender = state.peers[peerId].pc.getSenders()
        .find(s => s.track?.kind === 'video');
      if (sender) sender.replaceTrack(camTrack);
    }
  }

  // Restore local tile
  const localTile = document.getElementById('tile-local');
  if (localTile) {
    const video = localTile.querySelector('video');
    video.srcObject = state.localStream;
    localTile.classList.remove('screen-share');
  }

  document.getElementById('screenBtn').classList.remove('screen-on');
  sendSignal({ type: 'screen-share-stopped' });
  showToast('Ekran paylaşımı durduruldu');
}

// ─── Recording ───────────────────────────────────────────────────────────────
async function toggleRecording() {
  if (!state.recording) {
    await startRecording();
  } else {
    stopRecording();
  }
}

async function startRecording() {
  try {
    // Capture the full meeting view via canvas
    const canvas = document.createElement('canvas');
    canvas.width = 1280; canvas.height = 720;
    const ctx = canvas.getContext('2d');

    const videoEls = document.querySelectorAll('.video-tile video');
    const count = videoEls.length;

    const drawFrame = () => {
      if (!state.recording) return;
      ctx.fillStyle = '#0a0a0f';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      if (count === 0) { requestAnimationFrame(drawFrame); return; }

      const cols = count <= 2 ? count : Math.ceil(Math.sqrt(count));
      const rows = Math.ceil(count / cols);
      const w = canvas.width / cols;
      const h = canvas.height / rows;

      videoEls.forEach((vid, i) => {
        const col = i % cols;
        const row = Math.floor(i / cols);
        try {
          ctx.drawImage(vid, col * w, row * h, w, h);
        } catch (e) {}
      });

      requestAnimationFrame(drawFrame);
    };

    const canvasStream = canvas.captureStream(25);
    const audioTracks = [];
    if (state.localStream) audioTracks.push(...state.localStream.getAudioTracks());

    const combinedStream = new MediaStream([
      ...canvasStream.getVideoTracks(),
      ...audioTracks
    ]);

    const mimeType = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm']
      .find(m => MediaRecorder.isTypeSupported(m)) || 'video/webm';

    state.recordedChunks = [];
    state.mediaRecorder = new MediaRecorder(combinedStream, { mimeType });
    state.mediaRecorder.ondataavailable = e => {
      if (e.data.size > 0) state.recordedChunks.push(e.data);
    };
    state.mediaRecorder.onstop = downloadRecording;
    state.mediaRecorder.start(1000);

    state.recording = true;
    requestAnimationFrame(drawFrame);

    document.getElementById('recordBtn').classList.add('recording');
    document.getElementById('recordIndicator').style.display = 'flex';
    sendSignal({ type: 'recording-started' });
    showToast('Kayıt başladı');
  } catch (e) {
    console.error('Recording error:', e);
    showToast('Kayıt başlatılamadı: ' + e.message);
  }
}

function stopRecording() {
  state.recording = false;
  state.mediaRecorder?.stop();
  document.getElementById('recordBtn').classList.remove('recording');
  document.getElementById('recordIndicator').style.display = 'none';
  sendSignal({ type: 'recording-stopped' });
  showToast('Kayıt durdu, indiriliyor...');
}

function downloadRecording() {
  const blob = new Blob(state.recordedChunks, { type: 'video/webm' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const now = new Date();
  a.download = `nexmeet-${state.roomId}-${now.toISOString().slice(0,19).replace(/:/g,'-')}.webm`;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Chat ────────────────────────────────────────────────────────────────────
function toggleChat() {
  state.chatOpen = !state.chatOpen;
  document.getElementById('chatPanel').classList.toggle('open', state.chatOpen);
  document.getElementById('chatBtn').classList.toggle('active', state.chatOpen);
  if (state.chatOpen) {
    state.unreadMessages = 0;
    document.getElementById('chatBadge').style.display = 'none';
    document.getElementById('chatInput').focus();
    // close files if open
    if (filesOpen) toggleFiles();
  }
}

function sendChat() {
  const input = document.getElementById('chatInput');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';

  const timestamp = new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
  sendSignal({ type: 'chat', message: msg, timestamp });

  // Show own message
  appendChatMessage({ from: state.peerId, from_name: state.userName, message: msg, timestamp }, true);
}

function receiveChatMessage(msg) {
  appendChatMessage(msg, false);
  if (!state.chatOpen) {
    state.unreadMessages++;
    const badge = document.getElementById('chatBadge');
    badge.textContent = state.unreadMessages;
    badge.style.display = 'flex';
    showToast(`${msg.from_name}: ${msg.message.slice(0, 40)}${msg.message.length > 40 ? '…' : ''}`);
  }
}

function appendChatMessage(msg, isOwn) {
  const container = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = `chat-msg${isOwn ? ' own' : ''}`;
  div.innerHTML = `
    <div class="chat-msg-name">${isOwn ? 'Sen' : msg.from_name}</div>
    <div class="chat-msg-bubble">${escapeHtml(msg.message)}</div>
    <div class="chat-msg-time">${msg.timestamp || ''}</div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function addSystemMessage(text) {
  const container = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'chat-system';
  div.textContent = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

// ─── File Sharing ────────────────────────────────────────────────────────────
let filesOpen = false;
let unreadFiles = 0;

function toggleFiles() {
  filesOpen = !filesOpen;
  document.getElementById('filesPanel').classList.toggle('open', filesOpen);
  document.getElementById('filesBtn').classList.toggle('active', filesOpen);
  if (filesOpen) {
    unreadFiles = 0;
    document.getElementById('filesBadge').style.display = 'none';
    // close chat if open
    if (state.chatOpen) toggleChat();
    initFileDropZone();
  }
}

function initFileDropZone() {
  const zone = document.getElementById('fileDropZone');
  if (zone.dataset.init) return;
  zone.dataset.init = '1';

  zone.addEventListener('click', () => document.getElementById('fileInput').click());
  document.getElementById('fileInput').addEventListener('change', e => {
    handleFiles(Array.from(e.target.files));
    e.target.value = '';
  });

  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    handleFiles(Array.from(e.dataTransfer.files));
  });
}

async function handleFiles(files) {
  for (const file of files) {
    if (file.size > 100 * 1024 * 1024) {
      showToast(`"${file.name}" çok büyük (max 100 MB)`);
      continue;
    }
    await uploadFile(file);
  }
}

async function uploadFile(file) {
  const zone = document.getElementById('fileDropZone');
  const dropContent = document.getElementById('dropContent');
  const progressWrap = document.getElementById('uploadProgress');
  const progressBar = document.getElementById('progressBar');
  const progressLabel = document.getElementById('progressLabel');

  dropContent.style.display = 'none';
  progressWrap.style.display = 'flex';
  progressBar.style.width = '0%';
  progressLabel.textContent = `Yükleniyor: ${file.name}`;

  const formData = new FormData();
  formData.append('file', file);
  formData.append('peer_id', state.peerId);
  formData.append('uploader_name', state.userName);

  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/upload/${state.roomId}`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        progressBar.style.width = `${pct}%`;
        progressLabel.textContent = `Yükleniyor: %${pct}`;
      }
    };

    xhr.onload = () => {
      progressWrap.style.display = 'none';
      dropContent.style.display = 'flex';
      if (xhr.status === 200) {
        const data = JSON.parse(xhr.responseText);
        // Show own upload immediately
        appendFileItem({
          file_id: data.file_id,
          name: file.name,
          size: file.size,
          mime_type: file.type || 'application/octet-stream',
          uploader: state.userName,
          timestamp: new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }),
          own: true
        });
        showToast(`"${file.name}" paylaşıldı ✓`);
      } else {
        showToast('Yükleme başarısız: ' + (JSON.parse(xhr.responseText)?.detail || 'Hata'));
      }
      resolve();
    };

    xhr.onerror = () => {
      progressWrap.style.display = 'none';
      dropContent.style.display = 'flex';
      showToast('Yükleme hatası oluştu');
      resolve();
    };

    xhr.send(formData);
  });
}

function receiveFileNotification(msg) {
  appendFileItem({ ...msg, own: false });

  if (!filesOpen) {
    unreadFiles++;
    const badge = document.getElementById('filesBadge');
    badge.textContent = unreadFiles;
    badge.style.display = 'flex';
  }

  showToast(`📎 ${msg.uploader}: "${msg.name}" paylaştı`);
}

function appendFileItem(file) {
  const list = document.getElementById('filesList');
  const sizeStr = formatBytes(file.size);
  const icon = getFileIcon(file.mime_type, file.name);

  const item = document.createElement('div');
  item.className = 'file-item file-new';
  item.innerHTML = `
    <div class="file-icon">${icon}</div>
    <div class="file-info">
      <div class="file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
      <div class="file-meta">${sizeStr} · ${file.own ? 'Sen' : escapeHtml(file.uploader)} · ${file.timestamp}</div>
    </div>
    <a class="file-download" href="/api/download/${file.file_id}" download="${escapeHtml(file.name)}" target="_blank">⬇ İndir</a>
  `;
  list.prepend(item);
}

function getFileIcon(mime, name) {
  const ext = name.split('.').pop().toLowerCase();
  if (mime?.startsWith('image/')) return '🖼️';
  if (mime?.startsWith('video/')) return '🎬';
  if (mime?.startsWith('audio/')) return '🎵';
  if (mime?.includes('pdf')) return '📄';
  if (['zip','rar','7z','tar','gz'].includes(ext)) return '🗜️';
  if (['doc','docx'].includes(ext)) return '📝';
  if (['xls','xlsx','csv'].includes(ext)) return '📊';
  if (['ppt','pptx'].includes(ext)) return '📊';
  if (['js','ts','py','html','css','json','xml'].includes(ext)) return '💻';
  return '📎';
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// ─── Leave ───────────────────────────────────────────────────────────────────
function leaveMeeting() {
  if (state.recording) stopRecording();
  if (state.screenSharing) stopScreenShare();
  if (remote.isViewing) stopRemoteControl();

  state.ws?.close();
  state.localStream?.getTracks().forEach(t => t.stop());

  for (const peerId in state.peers) {
    state.peers[peerId].pc.close();
  }

  clearInterval(state.timerInterval);

  // Reset
  Object.assign(state, {
    localStream: null, screenStream: null, peers: {},
    roomId: null, peerId: null, ws: null,
    recording: false, screenSharing: false,
    micEnabled: true, camEnabled: true,
    chatOpen: false, unreadMessages: 0,
    meetingStartTime: null
  });

  document.getElementById('videoGrid').innerHTML = '';
  document.getElementById('chatMessages').innerHTML = '';
  document.getElementById('filesList').innerHTML = '';
  document.getElementById('chatPanel').classList.remove('open');
  document.getElementById('filesPanel').classList.remove('open');
  document.getElementById('meetingTimer').textContent = '00:00:00';
  filesOpen = false;
  unreadFiles = 0;

  showScreen('lobby');
  initLobby();
}

// ─── Utilities ───────────────────────────────────────────────────────────────
function showScreen(name) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(name).classList.add('active');
}

function updateParticipantCount() {
  const count = Object.keys(state.peers).length + 1;
  document.getElementById('participantCount').textContent =
    `${count} kişi`;
}

function copyRoomId() {
  const url = `${location.origin}/room/${state.roomId}`;
  navigator.clipboard.writeText(url).then(() => showToast('Davet linki kopyalandı!'));
}

let toastTimeout;
function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => el.classList.remove('show'), 3000);
}

function generateId(len = 8) {
  return Array.from(crypto.getRandomValues(new Uint8Array(len)))
    .map(b => b.toString(36).padStart(2, '0'))
    .join('').slice(0, len);
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

// ─── Init ─────────────────────────────────────────────────────────────────────
initLobby();

// ─── Remote Control ──────────────────────────────────────────────────────────
const remote = {
  sessionId: null,
  controlWs: null,
  targetPeerId: null,
  targetName: null,
  isViewing: false,
  frameCount: 0,
  fpsInterval: null,
  lastFrameW: 1280,
  lastFrameH: 720,
};

// Init remote control buttons
function initRemoteControl() {
  document.getElementById('remoteBtn').addEventListener('click', openRemotePicker);
  document.getElementById('remotePickCancel').addEventListener('click', () => showModal('remotePickModal', false));
  document.getElementById('remoteDenyBtn').addEventListener('click', denyControlRequest);
  document.getElementById('remoteApproveBtn').addEventListener('click', approveControlRequest);
  document.getElementById('remoteAgentClose').addEventListener('click', () => showModal('remoteAgentModal', false));
  document.getElementById('remoteWaitCancel').addEventListener('click', cancelControlRequest);
  document.getElementById('remoteViewerStop').addEventListener('click', stopRemoteControl);
  document.getElementById('remoteViewerFullscreen').addEventListener('click', toggleRemoteFullscreen);
  document.getElementById('copyAgentCmd').addEventListener('click', () => {
    navigator.clipboard.writeText(document.getElementById('agentCmd').textContent);
    showToast('Komut kopyalandı!');
  });

  // Canvas mouse events
  const canvas = document.getElementById('remoteCanvas');
  canvas.addEventListener('mousemove',  onRemoteMouseMove);
  canvas.addEventListener('click',      onRemoteClick);
  canvas.addEventListener('mousedown',  onRemoteMouseDown);
  canvas.addEventListener('mouseup',    onRemoteMouseUp);
  canvas.addEventListener('contextmenu', e => { e.preventDefault(); onRemoteClick(e, 'right'); });
  canvas.addEventListener('wheel',      onRemoteScroll, { passive: true });
  document.addEventListener('keydown',  onRemoteKeyDown);
}

function showModal(id, show) {
  document.getElementById(id).style.display = show ? 'flex' : 'none';
}

// ── Kontrolcü Tarafı ──────────────────────────────────────────────────────────
function openRemotePicker() {
  const peers = Object.entries(state.peers);
  if (peers.length === 0) {
    showToast('Toplantıda başka kimse yok.');
    return;
  }

  const list = document.getElementById('remotePeerList');
  list.innerHTML = '';
  peers.forEach(([peerId, peer]) => {
    const item = document.createElement('div');
    item.className = 'peer-list-item';
    item.innerHTML = `
      <div class="peer-list-avatar">${peer.name.charAt(0).toUpperCase()}</div>
      <div class="peer-list-name">${escapeHtml(peer.name)}</div>
    `;
    item.addEventListener('click', () => {
      showModal('remotePickModal', false);
      requestRemoteControl(peerId, peer.name);
    });
    list.appendChild(item);
  });

  showModal('remotePickModal', true);
}

async function requestRemoteControl(peerId, peerName) {
  remote.targetPeerId = peerId;
  remote.targetName = peerName;

  document.getElementById('remoteWaitText').textContent =
    `"${peerName}" kullanıcısının izin vermesi bekleniyor...`;
  showModal('remoteWaitModal', true);

  try {
    const res = await fetch('/api/control/request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        room_id: state.roomId,
        controller_peer_id: state.peerId,
        target_peer_id: peerId,
        controller_name: state.userName,
      })
    });
    const data = await res.json();
    remote.sessionId = data.session_id;
  } catch (e) {
    showModal('remoteWaitModal', false);
    showToast('Kontrol isteği gönderilemedi.');
  }
}

function cancelControlRequest() {
  showModal('remoteWaitModal', false);
  if (remote.sessionId) {
    fetch('/api/control/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: remote.sessionId })
    });
    remote.sessionId = null;
  }
}

function onControlApproved(sessionId) {
  showModal('remoteWaitModal', false);
  remote.sessionId = sessionId;
  remote.isViewing = true;

  // Open viewer
  document.getElementById('remoteViewerTarget').textContent = remote.targetName;
  document.getElementById('remoteViewer').style.display = 'flex';
  document.getElementById('remoteConnecting').style.display = 'flex';

  // Connect control WebSocket
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const wsUrl = `${proto}://${location.host}/ws/control/${sessionId}/${state.peerId}`;
  remote.controlWs = new WebSocket(wsUrl);

  remote.controlWs.onopen = () => console.log('Control WS open');
  remote.controlWs.onclose = () => {
    if (remote.isViewing) stopRemoteControl();
  };

  // FPS counter
  remote.frameCount = 0;
  remote.fpsInterval = setInterval(() => {
    document.getElementById('remoteFps').textContent = `${remote.frameCount} fps`;
    remote.frameCount = 0;
  }, 1000);
}

function onControlDenied() {
  showModal('remoteWaitModal', false);
  showToast('Kontrol isteği reddedildi.');
  remote.sessionId = null;
}

function onRemoteFrame(msg) {
  const canvas = document.getElementById('remoteCanvas');
  const ctx = canvas.getContext('2d');
  const connecting = document.getElementById('remoteConnecting');

  remote.lastFrameW = msg.width;
  remote.lastFrameH = msg.height;
  canvas.width  = msg.width;
  canvas.height = msg.height;

  connecting.style.display = 'none';
  remote.frameCount++;

  const img = new Image();
  img.onload = () => ctx.drawImage(img, 0, 0);
  img.src = 'data:image/jpeg;base64,' + msg.frame;
}

function sendControlCmd(data) {
  if (remote.controlWs && remote.controlWs.readyState === WebSocket.OPEN) {
    remote.controlWs.send(JSON.stringify(data));
  }
}

function getCanvasCoords(e) {
  const canvas = document.getElementById('remoteCanvas');
  const rect = canvas.getBoundingClientRect();
  const scaleX = remote.lastFrameW / rect.width;
  const scaleY = remote.lastFrameH / rect.height;
  return {
    x: (e.clientX - rect.left) * scaleX,
    y: (e.clientY - rect.top)  * scaleY,
  };
}

function onRemoteMouseMove(e) {
  if (!remote.isViewing) return;
  const { x, y } = getCanvasCoords(e);
  sendControlCmd({ type: 'mouse-move', x, y });
}

function onRemoteClick(e, forcedBtn) {
  if (!remote.isViewing) return;
  const { x, y } = getCanvasCoords(e);
  const button = forcedBtn || (e.button === 2 ? 'right' : 'left');
  const double = e.detail === 2;
  sendControlCmd({ type: 'mouse-click', x, y, button, double });
}

function onRemoteMouseDown(e) {
  if (!remote.isViewing) return;
  const { x, y } = getCanvasCoords(e);
  sendControlCmd({ type: 'mouse-down', x, y, button: e.button === 2 ? 'right' : 'left' });
}

function onRemoteMouseUp(e) {
  if (!remote.isViewing) return;
  const { x, y } = getCanvasCoords(e);
  sendControlCmd({ type: 'mouse-up', x, y, button: e.button === 2 ? 'right' : 'left' });
}

function onRemoteScroll(e) {
  if (!remote.isViewing) return;
  const { x, y } = getCanvasCoords(e);
  sendControlCmd({ type: 'mouse-scroll', x, y, delta: e.deltaY > 0 ? -3 : 3 });
}

// Klavye: sadece viewer açıkken yakala
function onRemoteKeyDown(e) {
  if (!remote.isViewing || !document.getElementById('remoteViewer').style.display === 'flex') return;
  if (['INPUT','TEXTAREA'].includes(document.activeElement?.tagName)) return;

  e.preventDefault();
  const keyMap = {
    'Enter': 'enter', 'Backspace': 'backspace', 'Delete': 'delete',
    'Escape': 'escape', 'Tab': 'tab', 'ArrowUp': 'up', 'ArrowDown': 'down',
    'ArrowLeft': 'left', 'ArrowRight': 'right', 'Home': 'home', 'End': 'end',
    'PageUp': 'pageup', 'PageDown': 'pagedown', 'F5': 'f5', 'F11': 'f11',
  };

  const mods = [];
  if (e.ctrlKey)  mods.push('ctrl');
  if (e.altKey)   mods.push('alt');
  if (e.shiftKey) mods.push('shift');

  const key = keyMap[e.key] || (e.key.length === 1 ? e.key : null);
  if (!key) return;

  sendControlCmd({ type: 'key-press', key, modifiers: mods });
}

function stopRemoteControl() {
  remote.isViewing = false;
  document.getElementById('remoteViewer').style.display = 'none';
  clearInterval(remote.fpsInterval);

  if (remote.controlWs) {
    try {
      remote.controlWs.send(JSON.stringify({ type: 'stop-control' }));
      remote.controlWs.close();
    } catch(e) {}
    remote.controlWs = null;
  }

  if (remote.sessionId) {
    fetch('/api/control/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: remote.sessionId })
    });
    remote.sessionId = null;
  }
  showToast('Uzak kontrol sonlandırıldı.');
}

function toggleRemoteFullscreen() {
  const el = document.getElementById('remoteViewer');
  if (!document.fullscreenElement) {
    el.requestFullscreen?.();
  } else {
    document.exitFullscreen?.();
  }
}

// ── Hedef Tarafı (İzin veren) ─────────────────────────────────────────────────
let pendingControlSession = null;

function onControlRequest(msg) {
  pendingControlSession = msg.session_id;
  document.getElementById('remoteRequestText').textContent =
    `"${msg.controller_name}" adlı kullanıcı bilgisayarınızı kontrol etmek istiyor.`;
  showModal('remoteRequestModal', true);
}

function approveControlRequest() {
  showModal('remoteRequestModal', false);
  if (!pendingControlSession) return;

  // Kullanıcıya ajan komutunu göster
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const serverAddr = `${proto}://${location.host}`;
  const cmd = `python agent.py --server ${serverAddr} --session ${pendingControlSession}`;
  document.getElementById('agentCmd').textContent = cmd;
  showModal('remoteAgentModal', true);

  // Backend'e onayla
  fetch('/api/control/respond', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: pendingControlSession, approved: true })
  });
  pendingControlSession = null;
}

function denyControlRequest() {
  showModal('remoteRequestModal', false);
  if (!pendingControlSession) return;
  fetch('/api/control/respond', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: pendingControlSession, approved: false })
  });
  pendingControlSession = null;
}
