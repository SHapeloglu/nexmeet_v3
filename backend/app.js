/**
 * ESKİ SÜRÜM: bu dosya frontend/static/js/app.js dosyasının giriş sistemi ve anlık çeviri (TTS) eklenmeden önceki kopyasıdır.
 * Hiçbir HTML sayfası bunu yüklemez; sunucu frontend klasörünü servis eder, backend klasörünü değil. Tarayıcıda çalışmaz, yalnızca referans içindir.
 * Güncel kod için frontend/static/js/app.js dosyasına bakın. Bu dosyanın silinmesi task.md'de planlıdır.
 */
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
  joinToken: null,     // Sunucudan alınan JWT benzeri token
  ws: null,
  wsReconnectTimer: null,
  wsReconnectAttempts: 0,
  wsReconnectMax: 5,
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
// TURN sunucusu: simetrik NAT'ın arkasındaki kullanıcılar için şart.
// Ücretsiz test: coturn (kendi sunucunuz) veya Metered.ca / Twilio gibi sağlayıcılar.
// TURN_URLS, TURN_USER, TURN_PASS değerlerini kendi sunucunuzla doldurun.
// TURN bilgileri bu eski sürümde boş. Gerçek değerler bu yoruma yazılmadı.
const TURN_URLS  = '';   // örn: 'turn:sizin-sunucu.com:3478'
const TURN_USER  = '';
const TURN_PASS  = '';

const ICE_SERVERS = [
  { urls: 'stun:stun.l.google.com:19302' },
  { urls: 'stun:stun1.l.google.com:19302' },
];

if (TURN_URLS) {
  ICE_SERVERS.push({
    urls:       TURN_URLS,
    username:   TURN_USER,
    credential: TURN_PASS,
  });
}

const ICE_CONFIG = { iceServers: ICE_SERVERS };

/**
 * Lobi ekranında uyarı kutusu gösterir (ör. HTTPS gerektiren kamera hatası).
 * Kutu ilk kez oluşturulur, sonra mevcut kutunun içeriği değiştirilir.
 * msg HTML olarak basılır; bu yüzden içine dışarıdan gelen metin koymayın.
 */
function showLobbyWarning(msg) {
  let el = document.getElementById('lobbyWarning');
  if (!el) {
    el = document.createElement('div');
    el.id = 'lobbyWarning';
    el.style.cssText = 'background:rgba(248,113,113,0.15);border:1px solid rgba(248,113,113,0.4);border-radius:10px;padding:10px 14px;font-size:13px;color:#f87171;text-align:center;max-width:440px;line-height:1.5';
    document.querySelector('.lobby-form').after(el);
  }
  el.innerHTML = msg;
}

// ─── Lobby ───────────────────────────────────────────────────────────────────
/**
 * Lobi ekranını hazırlar: kamera ve mikrofon önizlemesini açar, düğmeleri ve Enter tuşunu bağlar.
 * Bu eski sürümde kullanıcı adı girişi vardır, giriş zorunluluğu yoktur. Sayfa açılışta bir kez çağrılır.
 */
async function initLobby() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    document.getElementById('previewVideo').srcObject = stream;
    state.localStream = stream;
  } catch (e) {
    console.warn('Camera/Mic unavailable:', e);
    // HTTP üzerinden kamera açılamaz — kullanıcıya bildir
    if (!navigator.mediaDevices) {
      showLobbyWarning('⚠️ Kamera/mikrofon için HTTPS gerekli. Sunucuyu <b>https://</b> ile açın veya ngrok kullanın. Yine de katılabilirsiniz.');
    }
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

/**
 * Lobiden 'Katıl' denince çalışır: adı kontrol eder, oda ve kişi kimliği üretir, kamera ve mikrofonu açar, sunucudan join token alır ve toplantı ekranına geçer.
 * Bu eski sürümde ad formdan alınır (giriş yoktur). Ad boşsa işlem durur. Token alınamazsa toplantıya girilmez.
 */
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

  // Sunucudan join token al
  try {
    const res = await fetch('/api/join-token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: state.userName, room_id: state.roomId, peer_id: state.peerId }),
    });
    if (!res.ok) throw new Error('Token alınamadı');
    const tokenData = await res.json();
    state.joinToken = tokenData.token;
  } catch (e) {
    showToast('Sunucuya bağlanılamadı. Lütfen tekrar deneyin.');
    console.error('Token fetch error:', e);
    return;
  }

  showScreen('meeting');
  initMeetingUI();
  connectWebSocket();
}

// ─── Meeting UI ──────────────────────────────────────────────────────────────
/**
 * Toplantı ekranı açılınca düğmeleri bağlar, kendi kutumuzu ekler, uzak kontrol düğmelerini hazırlar ve süre sayacını başlatır.
 * joinMeeting içinde, sunucudan token alındıktan sonra çağrılır.
 */
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

/**
 * Toplantı süresini her saniye HH:MM:SS biçiminde üst çubuğa yazar.
 * Süre, meetingStartTime alanından hesaplanır; bu yüzden sekme arka planda kalsa bile doğru kalır.
 */
function updateTimer() {
  const elapsed = Math.floor((Date.now() - state.meetingStartTime) / 1000);
  const h = String(Math.floor(elapsed / 3600)).padStart(2, '0');
  const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');
  document.getElementById('meetingTimer').textContent = `${h}:${m}:${s}`;
}

// ─── WebSocket Signaling ─────────────────────────────────────────────────────
/**
 * Sinyalleşme sunucusuna WebSocket bağlantısı kurar. Bağlantı koparsa 2, 4, 8 ve 16 saniye arayla en fazla wsReconnectMax kez yeniden dener.
 * Kapanma kodu 4001 veya 4003 ise (token geçersiz / yetkisiz) yeniden denemez.
 * Kod 1000 ise (kasıtlı çıkış) yeniden denemez.
 * Gelen her mesaj handleSignal ile işlenir.
 */
function connectWebSocket() {
  if (state.wsReconnectAttempts >= state.wsReconnectMax) {
    showToast('Sunucu bağlantısı kurulamadı. Sayfayı yenileyin.');
    return;
  }

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  // DİKKAT: join token WebSocket adresinde sorgu parametresi olarak gider; sunucu erişim günlüklerine düşebilir.
  const url = `${proto}://${location.host}/ws/${state.roomId}/${state.peerId}?token=${encodeURIComponent(state.joinToken)}`;
  state.ws = new WebSocket(url);

  state.ws.onopen = () => {
    console.log('WS connected');
    state.wsReconnectAttempts = 0;  // Başarılı bağlantıda sayacı sıfırla
  };

  state.ws.onmessage = async (event) => {
    // JSON parse hatasında uygulamayı çökertme
    try {
      const msg = JSON.parse(event.data);
      await handleSignal(msg);
    } catch (e) {
      console.error('WS mesaj parse hatası:', e);
    }
  };

  state.ws.onclose = (event) => {
    console.log('WS disconnected, code:', event.code);
    // 4001 = geçersiz token, 4003 = yetkisiz — yeniden bağlanma
    if (event.code === 4001 || event.code === 4003) {
      showToast('Oturum süresi doldu. Lütfen tekrar katılın.');
      return;
    }
    // Toplantıdan kasıtlı ayrılma (code 1000) ise yeniden bağlanma
    if (event.code === 1000) return;

    state.wsReconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, state.wsReconnectAttempts), 16000);
    showToast(`Bağlantı kesildi. ${delay / 1000}s içinde tekrar denenecek... (${state.wsReconnectAttempts}/${state.wsReconnectMax})`);
    state.wsReconnectTimer = setTimeout(() => connectWebSocket(), delay);
  };

  state.ws.onerror = (e) => {
    console.error('WS error:', e);
  };
}

/**
 * Sunucuya WebSocket üzerinden JSON mesaj gönderir.
 * Socket açık değilse mesaj gönderilmez, yalnızca konsola uyarı yazılır (hata fırlatmaz).
 * data: type alanı olan bir nesne (ör. { type: 'chat', message }).
 */
function sendSignal(data) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(data));
  } else {
    console.warn('WS hazır değil, mesaj gönderilemedi:', data.type);
  }
}

/**
 * Sunucudan gelen WebSocket mesajını türüne göre işler (switch).
 * Bu eski sürümde tts-audio türü yoktur; diğer türler güncel sürümle aynıdır: room-joined, peer-joined, offer, answer, ice-candidate, peer-left, chat, file-shared, media-state, screen-share-*, control-* ve remote-*.
 * Bilinmeyen tür yok sayılır. Hatayı çağıran (onmessage) yakalar.
 */
async function handleSignal(msg) {
  const { type, from, from_name } = msg;

  switch (type) {
    case 'room-joined': {
      // Geçmiş sohbet mesajlarını göster
      if (msg.chat_history && msg.chat_history.length > 0) {
        for (const chatMsg of msg.chat_history) {
          addChatMessage(chatMsg.from_name, chatMsg.message, chatMsg.timestamp, false);
        }
        addSystemMessage(`── ${msg.chat_history.length} geçmiş mesaj yüklendi ──`);
      }
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
      // DİKKAT: kayıt durdurma bildiriminde kişi adı yerine msg.from (kişi kimliği) gösterilir; kullanıcı adı için from_name kullanılmalı.
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
    case 'control-session-created': {
      // Sunucu session_id atadı, kaydet
      remote.sessionId = msg.session_id;
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
/**
 * Bir kişiyle WebRTC bağlantısı (RTCPeerConnection) kurar. Yerel parçaları ekler, ICE adaylarını ve gelen videoyu bağlar.
 * initiator true ise teklifi (offer) bu taraf gönderir; false ise karşı taraftan teklif bekler.
 * Bağlantı failed veya disconnected olursa kişi kaldırılır.
 * Döner: RTCPeerConnection nesnesi.
 */
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

/**
 * Karşı tarafın offer (teklif) mesajını işler.
 * O kişi için bağlantı yoksa önce oluşturur; uzak açıklamayı (SDP) kaydeder, answer (cevap) üretip geri gönderir.
 * fromId: teklifi gönderen kişinin kimliği; msg.sdp: teklif metni.
 */
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

/**
 * Karşı tarafın answer (cevap) mesajını işler: uzak açıklamayı (SDP) kaydeder.
 * Bu kişi için bağlantı yoksa hiçbir şey yapmaz.
 */
async function handleAnswer(fromId, msg) {
  const peer = state.peers[fromId];
  if (peer) {
    await peer.pc.setRemoteDescription(new RTCSessionDescription(msg.sdp));
  }
}

/**
 * Karşı tarafın ICE adayını ekler. ICE adayı, iki tarayıcının birbirine ulaşabileceği ağ adresidir.
 * Aday hatalıysa veya bağlantı yoksa sessizce atlanır, uyarı konsola yazılır.
 */
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

/**
 * Bir kişiyi toplantıdan çıkarır: bağlantıyı kapatır, state.peers kaydını siler, video kutusunu kaldırır ve sayıları günceller.
 * Bağlantı yoksa bile kutu varsa kaldırılır.
 */
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
/**
 * Bir kişi için video kutusu oluşturur: video, kamera kapalıyken avatar ve isim etiketi.
 * Kendi kutumuz (isLocal) sessize alınır. Bu eski sürümde sabitleme (pin) ve ses analizi yoktur.
 * stream: akış; name: görünen ad; isLocal: kendi kutumuz mu.
 */
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
  // DİKKAT: name burada HTML olarak basılıyor ve kaçış yapılmıyor. Görünen ad HTML içeriyorsa sayfaya kod enjekte edilebilir (XSS). escapeHtml ile kaçırılması önerilir.
  label.innerHTML = `<span>${name}</span>`;
  label.id = `name-${peerId}`;

  tile.appendChild(video);
  tile.appendChild(overlay);
  tile.appendChild(label);
  grid.appendChild(tile);

  updateGrid();
}

/**
 * Video kutularını kutu sayısına göre ızgara düzenine koyar (count-1 ... count-many sınıfları).
 * Bu eski sürümde sabitleme (pin) ve konuşan kişiyi büyütme yoktur; düzen her zaman eşit ızgaradır.
 */
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

/**
 * Uzak kişinin mikrofon ve kamera durumunu kutuya yansıtır.
 * Kamera kapalıysa avatar gösterilir; mikrofon kapalıysa isme sessiz simgesi eklenir.
 * videoEnabled / audioEnabled false ise kapalı kabul edilir. Kutu yoksa hiçbir şey yapmaz.
 */
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

/**
 * Bir kişinin kutusuna ekran paylaşımı işaretini ekler (active true) ya da kaldırır (false).
 */
function markTileScreenShare(peerId, active) {
  const tile = document.getElementById(`tile-${peerId}`);
  if (!tile) return;
  tile.classList.toggle('screen-share', active);
}

// ─── Controls ────────────────────────────────────────────────────────────────
/**
 * Mikrofonu açar veya kapatır, düğmenin görünümünü günceller ve yeni durumu diğer kişilere bildirir.
 */
function toggleMic() {
  state.micEnabled = !state.micEnabled;
  state.localStream?.getAudioTracks().forEach(t => t.enabled = state.micEnabled);
  updateMicBtn();
  broadcastMediaState();
}

/**
 * Mikrofon düğmesinin görünümünü (aktif rengi ve üstü çizgisi) state.micEnabled değerine göre günceller.
 */
function updateMicBtn() {
  const btn = document.getElementById('micBtn');
  const slash = document.getElementById('micOff');
  btn.classList.toggle('active', state.micEnabled);
  slash.style.display = state.micEnabled ? 'none' : 'block';
}

/**
 * Kamerayı açar veya kapatır. Yerel parçanın enabled değeri değişir, düğme ve kendi kutumuz güncellenir.
 * Durum diğer kişilere media-state mesajıyla bildirilir.
 */
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

/**
 * Kamera düğmesinin görünümünü state.camEnabled değerine göre günceller.
 */
function updateCamBtn() {
  const btn = document.getElementById('camBtn');
  const slash = document.getElementById('camOff');
  btn.classList.toggle('active', state.camEnabled);
  slash.style.display = state.camEnabled ? 'none' : 'block';
}

/**
 * Mikrofon ve kamera durumunu tüm kişilere media-state mesajıyla gönderir. Karşı taraf kutusundaki simgeleri bu mesajla günceller.
 */
function broadcastMediaState() {
  sendSignal({ type: 'media-state', audio: state.micEnabled, video: state.camEnabled });
}

/**
 * Ekran paylaşımını başlatır veya durdurur.
 * Başlatırken tarayıcının ekran seçme penceresi açılır; seçilen görüntü, her bağlantıdaki video göndericisinin parçası (track) yerine konur.
 * Kullanıcı pencereyi iptal ederse (NotAllowedError) sessizce çıkılır.
 */
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

/**
 * Ekran paylaşımını durdurur: ekran akışını kapatır, kamera parçasını tüm bağlantılara geri koyar ve kendi kutumuzu eski haline döndürür.
 * Not: ekran paylaşımı tarayıcının kendi 'Paylaşımı durdur' düğmesiyle de bitebilir; o durumda da bu fonksiyon çağrılır.
 */
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
/**
 * Kayıt düğmesi: kayıt yoksa başlatır, varsa durdurur.
 */
async function toggleRecording() {
  if (!state.recording) {
    await startRecording();
  } else {
    stopRecording();
  }
}

/**
 * Toplantı görüntüsünü kayıt altına alır.
 * Katılımcı videoları 1280x720 bir tuvale (canvas) her karede çizilir, tuval görüntüsü ve yerel ses MediaRecorder ile WebM olarak kaydedilir.
 * Kayıt bittiğinde downloadRecording dosyayı indirir. Tarayıcı MediaRecorder desteklemezse hata mesajı gösterilir.
 */
async function startRecording() {
  try {
    // Capture the full meeting view via canvas
    const canvas = document.createElement('canvas');
    canvas.width = 1280; canvas.height = 720;
    const ctx = canvas.getContext('2d');

    const videoEls = document.querySelectorAll('.video-tile video');
    const count = videoEls.length;

    /**
     * Kayıt sırasında her karede çağrılır (requestAnimationFrame). Videoları ızgara halinde tuvale çizer, sonra bir sonraki kareyi planlar.
     * Kayıt durunca kendini durdurur.
     */
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

/**
 * Kaydı durdurur. MediaRecorder durunca onstop olayı downloadRecording'i çağırıp dosyayı indirir.
 */
function stopRecording() {
  state.recording = false;
  state.mediaRecorder?.stop();
  document.getElementById('recordBtn').classList.remove('recording');
  document.getElementById('recordIndicator').style.display = 'none';
  sendSignal({ type: 'recording-stopped' });
  showToast('Kayıt durdu, indiriliyor...');
}

/**
 * Kayıt parçalarını tek WebM dosyasına birleştirip tarayıcıya indirir. Dosya adına oda kodu ve zaman damgası eklenir.
 */
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
/**
 * Sohbet panelini açar veya kapatır.
 * Açılınca okunmamış mesaj sayısını sıfırlar ve yazı kutusuna odaklanır. Dosya paneli açıksa onu kapatır.
 */
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

/**
 * Sohbet kutusundaki mesajı gönderir. Boş mesaj gönderilmez.
 * Mesaj önce sunucuya chat türüyle gider, sonra kendi ekranımıza da eklenir (sunucu kendi mesajımızı geri göndermez).
 */
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

/**
 * Başkasından gelen sohbet mesajını ekler. Sohbet paneli kapalıysa okunmamış sayısını artırır ve kısa bildirim gösterir.
 */
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

/**
 * Sohbet paneline bir mesaj balonu ekler. isOwn true ise mesaj 'Sen' olarak görünür.
 * Mesaj metni escapeHtml ile kaçırılır, bu XSS (sayfaya kod enjeksiyonu) riskini azaltır.
 * DİKKAT: kullanıcı adı (from_name) kaçırılmadan basılır; ad HTML içeriyorsa risk oluşur.
 */
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

/**
 * Sohbete sistem mesajı ekler (ör. 'X toplantıya katıldı'). textContent kullanıldığı için metin HTML olarak yorumlanmaz.
 */
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

/**
 * Dosya panelini açar veya kapatır. Açılırsa okunmamış sayısını sıfırlar, sohbet paneli açıksa onu kapatır ve dosya bırakma alanını hazırlar.
 */
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

/**
 * Dosya bırakma alanına tıklama, dosya seçme ve sürükle-bırak olaylarını bağlar.
 * dataset.init işaretiyle olayları yalnızca bir kez bağlar; panel her açıldığında tekrar bağlanmaz.
 */
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

/**
 * Seçilen dosyaları sırayla yükler. 100 MB'tan büyük dosyalar atlanır ve kullanıcıya bildirilir.
 * files: dosya listesi (File nesnelerinin dizisi).
 */
async function handleFiles(files) {
  for (const file of files) {
    if (file.size > 100 * 1024 * 1024) {
      showToast(`"${file.name}" çok büyük (max 100 MB)`);
      continue;
    }
    await uploadFile(file);
  }
}

/**
 * Tek bir dosyayı odaya yükler ve yükleme yüzdesini gösterir.
 * Bu eski sürümde istek gövdesinde join token gönderilmez.
 * Başarılıysa dosya kendi listemize eklenir; hata olursa kullanıcıya bildirilir. Promise her durumda tamamlanır.
 */
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
        // Sunucu cevabı geçerli JSON değilse bu satır hata verir ve dosya listesi güncellenmez. Yanıt kontrolü yoktur.
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

/**
 * Başkasının paylaştığı dosyayı listeye ekler, panel kapalıysa okunmamış sayısını artırır ve bildirim gösterir.
 */
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

/**
 * Dosya listesinin en üstüne bir satır ekler: ikon, ad, boyut, gönderen, saat ve indirme bağlantısı.
 * Ad ve gönderen HTML olarak basılmadan önce escapeHtml ile kaçırılır.
 */
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

/**
 * Dosyanın MIME türüne ve uzantısına göre bir emoji ikonu seçer. Tanınmayan dosyalar için kağıt klip simgesi kullanılır.
 */
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

/**
 * Bayt sayısını okunabilir metne çevirir (ör. 1536 -> '1.5 KB'). 1024 tabanlı hesaplanır.
 */
function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// ─── Leave ───────────────────────────────────────────────────────────────────
/**
 * Toplantıdan çıkar: kayıt, ekran paylaşımı ve uzak kontrol varsa durdurur.
 * WebSocket'i kasıtlı olarak kapatır (kod 1000, yeniden bağlanma olmaz), tüm bağlantıları ve medya akışlarını kapatır, sonra lobiye döner.
 */
function leaveMeeting() {
  if (state.recording) stopRecording();
  if (state.screenSharing) stopScreenShare();
  if (remote.isViewing) stopRemoteControl();

  // Kasıtlı ayrılma — yeniden bağlanma zamanlayıcısını iptal et
  if (state.wsReconnectTimer) {
    clearTimeout(state.wsReconnectTimer);
    state.wsReconnectTimer = null;
  }
  state.ws?.close(1000, 'User left');  // 1000 = normal kapanma
  state.localStream?.getTracks().forEach(t => t.stop());

  for (const peerId in state.peers) {
    state.peers[peerId].pc.close();
  }

  clearInterval(state.timerInterval);

  // Reset
  Object.assign(state, {
    localStream: null, screenStream: null, peers: {},
    roomId: null, peerId: null, ws: null,
    joinToken: null,
    wsReconnectAttempts: 0, wsReconnectTimer: null,
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
/**
 * Verilen kimlikli ekranı (lobi veya toplantı) görünür yapar; diğer ekranları gizler.
 * name: HTML'de ekranın id değeri.
 */
function showScreen(name) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(name).classList.add('active');
}

/**
 * Kendimiz dahil katılımcı sayısını üst çubukta gösterir (bağlantısı olan kişi sayısı + 1).
 */
function updateParticipantCount() {
  const count = Object.keys(state.peers).length + 1;
  document.getElementById('participantCount').textContent =
    `${count} kişi`;
}

/**
 * Oda davet bağlantısını (site adresi + /room/kod) panoya kopyalar ve bildirim gösterir.
 */
function copyRoomId() {
  const url = `${location.origin}/room/${state.roomId}`;
  navigator.clipboard.writeText(url).then(() => showToast('Davet linki kopyalandı!'));
}

let toastTimeout;
/**
 * Ekranın altında 3 saniye kadar kısa bildirim (toast) gösterir. Yeni mesaj gelirse önceki zamanlayıcı iptal edilir.
 * msg düz metin olarak yazılır (textContent), HTML yorumlanmaz.
 */
function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => el.classList.remove('show'), 3000);
}

/**
 * Tarayıcının güvenli rastgele sayı üretecini kullanarak verilen uzunlukta (varsayılan 8) rastgele bir kod üretir.
 * Oda kodu ve kimlik olarak kullanılır.
 */
function generateId(len = 8) {
  return Array.from(crypto.getRandomValues(new Uint8Array(len)))
    .map(b => b.toString(36).padStart(2, '0'))
    .join('').slice(0, len);
}

/**
 * Metindeki & < > " ' karakterlerini HTML kaçış dizilerine çevirir.
 * Kullanıcıdan gelen her metni innerHTML ile basmadan önce bu fonksiyondan geçirin. str metin olmalıdır (null verilirse hata olur).
 */
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

/**
 * Bir pencereyi (modal) gösterir (show true) veya gizler (show false). id: HTML'deki pencere kutusunun kimliği.
 */
function showModal(id, show) {
  document.getElementById(id).style.display = show ? 'flex' : 'none';
}

// ── Kontrolcü Tarafı ──────────────────────────────────────────────────────────
/**
 * Uzak kontrol için kişi seçme penceresini açar. Toplantıdaki diğer kişiler listelenir.
 * Kimse yoksa uyarı gösterilir ve pencere açılmaz.
 */
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

/**
 * Kontrolcü tarafı: seçilen kişiye uzak kontrol isteği gönderir ve 'izin bekleniyor' penceresini açar.
 * İstek sunucuya control-request mesajıyla WebSocket üzerinden gider.
 * peerId: hedef kişinin kimliği; peerName: ekranda gösterilecek ad.
 */
async function requestRemoteControl(peerId, peerName) {
  remote.targetPeerId = peerId;
  remote.targetName = peerName;

  document.getElementById('remoteWaitText').textContent =
    `"${peerName}" kullanıcısının izin vermesi bekleniyor...`;
  showModal('remoteWaitModal', true);

  // WebSocket üzerinden gönder (API değil)
  sendSignal({
    type: 'control-request',
    target_peer_id: peerId,
  });
}

/**
 * Kontrol isteğini iptal eder: bekleme penceresini kapatır, oturum varsa /api/control/stop isteği gönderir.
 * Bu eski sürümde istekte token yoktur, yalnızca oturum kodu gider.
 */
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

/**
 * Hedef kişi isteği onayladığında çalışır. Kontrol WebSocket'ini açar ve saniyede kaç kare geldiğini (FPS) hesaplayan sayacı başlatır.
 * sessionId: sunucunun verdiği oturum kimliği.
 */
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

/**
 * Hedef kişi isteği reddettiğinde çalışır: bekleme penceresini kapatır, bilgi mesajı gösterir ve oturum kimliğini siler.
 */
function onControlDenied() {
  showModal('remoteWaitModal', false);
  showToast('Kontrol isteği reddedildi.');
  remote.sessionId = null;
}

/**
 * Hedef bilgisayardan gelen bir ekran karesini (base64 JPEG) kontrolcünün tuvaline çizer ve FPS sayacını artırır.
 * İlk karede 'bağlanıyor' yazısı gizlenir.
 * msg.width ve msg.height karenin boyutudur; tuval de aynı boyuta ayarlanır.
 */
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

/**
 * Kontrol WebSocket'i açıksa komutu (fare, klavye) JSON olarak gönderir; değilse sessizce atlar.
 */
function sendControlCmd(data) {
  if (remote.controlWs && remote.controlWs.readyState === WebSocket.OPEN) {
    remote.controlWs.send(JSON.stringify(data));
  }
}

/**
 * Fare olayının koordinatını uzak ekranın çözünürlüğüne çevirir.
 * Tuval ekranda küçük görünse bile tıklanan nokta hedef bilgisayardaki doğru piksele gider.
 * Dönen değer: { x, y }.
 */
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

/**
 * Fare hareketini uzak bilgisayara iletir (mouse-move). Kontrol açık değilse hiçbir şey yapmaz.
 */
function onRemoteMouseMove(e) {
  if (!remote.isViewing) return;
  const { x, y } = getCanvasCoords(e);
  sendControlCmd({ type: 'mouse-move', x, y });
}

/**
 * Tıklamayı uzak bilgisayara iletir. Sağ tık (contextmenu) için forcedBtn 'right' olarak verilir. e.detail === 2 ise çift tıklama kabul edilir.
 */
function onRemoteClick(e, forcedBtn) {
  if (!remote.isViewing) return;
  const { x, y } = getCanvasCoords(e);
  const button = forcedBtn || (e.button === 2 ? 'right' : 'left');
  const double = e.detail === 2;
  sendControlCmd({ type: 'mouse-click', x, y, button, double });
}

/**
 * Fare tuşuna basılmasını (mouse-down) uzak bilgisayara iletir. Sürükleme için mouseup ile birlikte kullanılır.
 */
function onRemoteMouseDown(e) {
  if (!remote.isViewing) return;
  const { x, y } = getCanvasCoords(e);
  sendControlCmd({ type: 'mouse-down', x, y, button: e.button === 2 ? 'right' : 'left' });
}

/**
 * Fare tuşunun bırakılmasını (mouse-up) uzak bilgisayara iletir.
 */
function onRemoteMouseUp(e) {
  if (!remote.isViewing) return;
  const { x, y } = getCanvasCoords(e);
  sendControlCmd({ type: 'mouse-up', x, y, button: e.button === 2 ? 'right' : 'left' });
}

/**
 * Tekerlek hareketini uzak bilgisayara iletir. Aşağı kaydırma -3, yukarı kaydırma +3 değerinde gönderilir.
 */
function onRemoteScroll(e) {
  if (!remote.isViewing) return;
  const { x, y } = getCanvasCoords(e);
  sendControlCmd({ type: 'mouse-scroll', x, y, delta: e.deltaY > 0 ? -3 : 3 });
}

// Klavye: sadece viewer açıkken yakala
function onRemoteKeyDown(e) {
  // DİKKAT: bu koşul hatalı yazılmış. '!x === flex' ifadesi her zaman false olur; yani asıl etkili kontrol sadece remote.isViewing. Davranış değişmesin diye kod düzeltilmedi.
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

/**
 * Uzak kontrolü bitirir: izleme penceresini kapatır, kontrol WebSocket'ine stop-control gönderip kapatır ve /api/control/stop ile oturumu sunucuda sonlandırır.
 * Bu eski sürümde istekte yalnızca oturum kodu gider (token yok).
 */
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

/**
 * Uzak ekran penceresini tam ekran açar veya kapatır (Fullscreen API). Tarayıcı desteklemezse hiçbir şey olmaz.
 */
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

/**
 * Hedef taraf: başka bir kişi kontrol istediğinde çalışır. Oturum kimliğini saklar ve onay penceresini açar.
 * msg.controller_name: isteyen kişinin adı; msg.session_id: oturum kimliği. Bu eski sürümde ajan anahtarı yoktur.
 */
function onControlRequest(msg) {
  pendingControlSession = msg.session_id;
  document.getElementById('remoteRequestText').textContent =
    `"${msg.controller_name}" adlı kullanıcı bilgisayarınızı kontrol etmek istiyor.`;
  showModal('remoteRequestModal', true);
}

/**
 * Hedef kişi 'İzin ver' dediğinde çalışır: sunucuya onay gönderir ve Windows/Linux ajan bilgilerini gösterir.
 * Bu eski sürümde ajan anahtarı yoktur; yalnızca sunucu adresi ve oturum kodu gösterilir.
 */
function approveControlRequest() {
  showModal('remoteRequestModal', false);
  if (!pendingControlSession) return;

  // Sunucuya WebSocket üzerinden onayla
  sendSignal({
    type: 'control-response',
    session_id: pendingControlSession,
    approved: true,
  });

  // Ajan modalını doldur
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const serverAddr = `${proto}://${location.host}`;
  const session = pendingControlSession;

  // Windows bilgileri
  const winInfo = `Sunucu: ${serverAddr}\nOturum Kodu: ${session}`;
  document.getElementById('agentCmdWindows').textContent = winInfo;

  // Linux komutu
  const linuxCmd = `chmod +x linux_agent.sh && ./linux_agent.sh\n# Sunucu: ${serverAddr}\n# Oturum: ${session}`;
  document.getElementById('agentCmdLinux').textContent = linuxCmd;

  showModal('remoteAgentModal', true);
  pendingControlSession = null;
}

/**
 * Ajan penceresindeki Windows / Linux sekmelerini değiştirir. Seçilen sekmenin içeriğini gösterir, diğerini gizler.
 * Not: event genel değişkeninden okunur; bu fonksiyon yalnızca tıklama olayından çağrılmalıdır.
 */
function switchOsTab(os) {
  document.querySelectorAll('.os-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('osWindows').style.display = os === 'windows' ? 'flex' : 'none';
  document.getElementById('osLinux').style.display  = os === 'linux'   ? 'flex' : 'none';
  // DİKKAT: event genel değişkeninden okunuyor; fonksiyon bir olay dinleyicisi dışında çağrılırsa event tanımsız olur.
  event.target.classList.add('active');
}

/**
 * Windows için ajan bilgilerini (sunucu, oturum kodu, anahtar) panoya kopyalar.
 */
function copyAgentInfo() {
  const txt = document.getElementById('agentCmdWindows').textContent;
  navigator.clipboard.writeText(txt);
  showToast('Bilgiler kopyalandı!');
}

/**
 * Linux için ajan çalıştırma komutunu panoya kopyalar.
 */
function copyAgentCmd() {
  const txt = document.getElementById('agentCmdLinux').textContent;
  navigator.clipboard.writeText(txt);
  showToast('Komut kopyalandı!');
}

/**
 * Hedef kişi 'Reddet' dediğinde çalışır: isteği sunucuya approved false olarak bildirir ve bekleyen istek bilgisini siler.
 */
function denyControlRequest() {
  showModal('remoteRequestModal', false);
  if (!pendingControlSession) return;

  sendSignal({
    type: 'control-response',
    session_id: pendingControlSession,
    approved: false,
  });

  pendingControlSession = null;
}
