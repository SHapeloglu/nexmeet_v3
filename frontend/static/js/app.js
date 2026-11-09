/**
 * NexMeet tarayıcı tarafı: WebRTC ile görüntülü toplantı arayüzü.
 * Bu dosya index.html içinde /static/js/app.js olarak yüklenir.
 * Akış: lobi -> joinMeeting (sunucudan join token alınır) -> WebSocket ile sinyalleşme (offer, answer, ICE) -> RTCPeerConnection ile kişiler arası doğrudan medya.
 * Sunucu tarafı (token üretimi, WebSocket yönlendirme) backend klasöründedir; bu dosya yalnızca tarayıcıda çalışır.
 * Tüm anlık durum en üstteki state nesnesinde tutulur. Uzak masaüstü kontrolü ve anlık çeviri (TTS) bölümleri dosyanın alt kısmındadır.
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
  // TTS
  ttsEnabled: false,
  ttsRecording: false,
  ttsMediaRecorder: null,
  ttsAudioChunks: [],
  ttsProcessing: false,
  pinnedPeerId: null,
  autoPinEnabled: true,
  speakingPeerId: null,
  hasVoiceProfile: false,
  voiceProfileRecorder: null,
  voiceProfileChunks: [],
};

// ─── ICE Config ──────────────────────────────────────────────────────────────
// TURN sunucusu: simetrik NAT'ın arkasındaki kullanıcılar için şart.
// Ücretsiz test: coturn (kendi sunucunuz) veya Metered.ca / Twilio gibi sağlayıcılar.
//TURN_URLS, TURN_USER, TURN_PASS değerlerini kendi sunucunuzla doldurun.
// TURN bilgileri koddan okunur ve bu repo herkese açıktır; değerler bu yoruma yazılmadı.
// DİKKAT: sabit TURN kullanıcı adı ve parolası kodda duruyor. Canlıda gizli tutulmalı, koddan çıkarılmalı.
const TURN_URLS  = 'turn:nexmeet.powerbi.com.tr:3478';
const TURN_USER  = 'nexmeet';
const TURN_PASS  = 'nexmeet123';
const ICE_SERVERS = [
  { urls: 'stun:stun.l.google.com:19302' },
  { urls: 'stun:stun1.l.google.com:19302' },
];

// TURN_URLS boşsa TURN sunucusu eklenmez; yalnızca STUN kullanılır. STUN, kullanıcının dış IP adresini öğrenmesini sağlar.
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
 * Lobi ekranını hazırlar: kamera ve mikrofon önizlemesini açar (izin yoksa uyarı verir), düğmelerin ve Enter tuşunun olaylarını bağlar.
 * Oda kodu kutusunu /room/<kod> adresinden otomatik doldurur.
 * Oturum doğrulanınca ve toplantıdan çıkılınca çağrılır.
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
  // /room/<kod> bağlantısıyla gelindiyse oda kodu kutusu otomatik dolar. Kod 20 karakterle sınırlanır.
  // Oda bağlantısıyla gelindiyse (/room/<id>) kodu önceden doldur
  const odaYolu = location.pathname.match(/^\/room\/(.+)$/);
  if (odaYolu && !document.getElementById('roomInput').value) {
    try {
      document.getElementById('roomInput').value = decodeURIComponent(odaYolu[1]).slice(0, 20);
    } catch (e) { /* bozuk kodlama: boş bırak */ }
  }
}

// ─── Üyelik: oturum kontrolü ─────────────────────────────────────────────────
/**
 * Giriş sayfasının adresini üretir. Giriş sonrası dönülecek sayfa (next) olarak şu anki adres eklenir.
 * Döner: '/giris?next=...' biçiminde metin.
 */
function girisAdresi() {
  return '/giris?' + new URLSearchParams({ next: location.pathname || '/' }).toString();
}

// Oturum yoksa girişe yönlendirir; varsa görünen adı alır. true/false döner.
async function oturumYukle() {
  let res;
  try {
    res = await fetch('/api/ben', { credentials: 'same-origin' });
  } catch (e) {
    showToast('Sunucuya ulaşılamadı.');
    return false;
  }
  if (res.status === 401) {
    location.href = girisAdresi();
    return false;
  }
  if (!res.ok) {
    showToast('Oturum bilgisi alınamadı. Sayfayı yenileyin.');
    return false;
  }
  const kullanici = await res.json();
  state.userName = kullanici.display_name;
  document.getElementById('kullaniciAd').textContent = kullanici.display_name;
  document.getElementById('kullaniciCubugu').hidden = false;
  document.getElementById('cikisBtn').addEventListener('click', async () => {
    try {
      await fetch('/api/auth/cikis', { method: 'POST', credentials: 'same-origin' });
    } finally {
      location.href = '/giris';
    }
  });
  return true;
}

/**
 * Lobiden 'Katıl' denince çalışır: kamera ve mikrofonu açar, sunucudan join token alır ve toplantı ekranına geçer.
 * Kamera ve mikrofon alınamazsa önce görüntülü, sonra yalnızca sesli dener; ikisi de olmazsa boş akışla devam eder.
 * Oda kodu boşsa rastgele 8 karakterlik kod üretilir.
 * Oturum yoksa girişe yönlendirir. Token alınamazsa toplantıya girilmez.
 */
async function joinMeeting() {
  const roomInput = document.getElementById('roomInput').value.trim();

  if (!state.userName) {
    showToast('Oturum bilgisi yok. Lütfen giriş yapın.');
    location.href = girisAdresi();
    return;
  }

  state.roomId = roomInput || generateId(8);

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
      body: JSON.stringify({ room_id: state.roomId }),
      credentials: 'same-origin',
    });
    if (res.status === 401) {
      location.href = girisAdresi();
      return;
    }
    if (!res.ok) throw new Error('Token alınamadı');
    const tokenData = await res.json();
    state.joinToken = tokenData.token;
    state.peerId = tokenData.peer_id;
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
 * Sunucudan gelen her WebSocket mesajını türüne göre işler (switch).
 * Başlıca türler: room-joined ve peer-joined (kişi bağlantıları), offer, answer, ice-candidate (WebRTC sinyalleri), peer-left, chat, file-shared, media-state (mikrofon/kamera), screen-share-*, control-* ve remote-* (uzak kontrol), tts-audio (çeviri sesi).
 * Bilinmeyen tür sessizce yok sayılır.
 * Hata olursa çağıran (onmessage) yakalar ve konsola yazar.
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
    case 'tts-audio': {
      if (msg.audio_base64) {
        await playTTSAudio(msg.audio_base64);
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
      // Bildirimde kullanıcı adı (from_name) gösterilir; yoksa kimlik (from) yedek olarak kullanılır.
      showToast(`${msg.from_name || msg.from} kaydı durdurdu`);
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
 * Bir kişi için video kutusu oluşturur: video, kamera kapalıyken avatar, isim etiketi ve sabitleme düğmesi.
 * Kendi kutumuz (isLocal) sessize alınır; kendi sesimizi duymayalım diye.
 * Konuşma algılama için ses seviyesi analizi başlatılır.
 * stream: video ve ses akışı; name: görünen ad; isLocal: kendi kutumuz mu.
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
  // Ad HTML olarak değil metin olarak basılır (XSS koruması).
  const nameSpan = document.createElement('span');
  nameSpan.textContent = name;
  label.appendChild(nameSpan);
  label.id = `name-${peerId}`;

  tile.appendChild(video);
  tile.appendChild(overlay);
  tile.appendChild(label);
  const pinBtn = document.createElement("button");
  pinBtn.className = "pin-btn";
  pinBtn.title = "Sabitle";
  pinBtn.innerHTML = "📌";
  pinBtn.onclick = (e) => { e.stopPropagation(); togglePin(peerId); };
  tile.appendChild(pinBtn);
  grid.appendChild(tile);

  // Ses seviyesi algılama
  if (stream) {
    try {
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      let lastSpeak = 0;
      (function checkVolume() {
        analyser.getByteFrequencyData(data);
        const avg = data.reduce((a,b)=>a+b,0)/data.length;
        const t = document.getElementById("tile-"+peerId);
        if (!t) { audioCtx.close(); return; }
        if (avg > 15) { lastSpeak=Date.now(); setSpeaking(peerId); t.classList.add("speaking"); }
        else if (Date.now()-lastSpeak > 1500) { t.classList.remove("speaking"); }
        requestAnimationFrame(checkVolume);
      })();
    } catch(e) {}
  }
  updateGrid();
}

/**
 * Video kutularını (tile) ekran düzenine göre yerleştirir.
 * Bir kişi sabitlenmişse (pin) veya konuşan kişi otomatik sabitleniyorsa o kutu büyük alana alınır, diğerleri kenar çubuğuna geçer.
 * Sabit yoksa veya tek kişiyse fallbackGrid ile eşit ızgara kullanılır.
 */
function updateGrid() {
  const grid = document.getElementById('videoGrid');
  const allTiles = Array.from(grid.querySelectorAll('.video-tile:not(.sidebar-tiles .video-tile)'));
  const count = allTiles.length;

  // Pin varsa veya auto-pin aktifse
  const activePinId = state.pinnedPeerId || (state.autoPinEnabled ? state.speakingPeerId : null);

  if (activePinId && count > 1) {
    const pinnedTile = document.getElementById(`tile-${activePinId}`);
    if (!pinnedTile) { fallbackGrid(grid, allTiles, count); return; }

    grid.className = 'video-grid pinned';

    // Sidebar oluştur
    let sidebar = grid.querySelector('.sidebar-tiles');
    if (!sidebar) {
      sidebar = document.createElement('div');
      sidebar.className = 'sidebar-tiles';
      grid.appendChild(sidebar);
    }

    // Pinned tile ana alana
    pinnedTile.classList.add('pinned-tile');
    grid.insertBefore(pinnedTile, sidebar);

    // Diğerlerini sidebar'a
    allTiles.forEach(tile => {
      if (tile.id !== `tile-${activePinId}`) {
        tile.classList.remove('pinned-tile');
        sidebar.appendChild(tile);
      }
    });

    // Auto-pin göstergesi
    allTiles.forEach(tile => {
      const existing = tile.querySelector('.auto-pin-indicator');
      if (existing) existing.remove();
    });
    if (!state.pinnedPeerId && state.autoPinEnabled && activePinId) {
      const indicator = document.createElement('div');
      indicator.className = 'auto-pin-indicator';
      indicator.textContent = '🎤 Aktif';
      pinnedTile.appendChild(indicator);
    }
  } else {
    fallbackGrid(grid, allTiles, count);
  }
}

/**
 * Kenar çubuğu varsa kutuları ana alana geri taşıyıp kaldırır, ardından kutu sayısına göre (count-1 ... count-many) düzen sınıfını ayarlar.
 * grid: video ızgarası; allTiles: tüm kutular; count: kutu sayısı.
 */
function fallbackGrid(grid, allTiles, count) {
  // Sidebar varsa temizle
  const sidebar = grid.querySelector('.sidebar-tiles');
  if (sidebar) {
    Array.from(sidebar.querySelectorAll('.video-tile')).forEach(t => grid.insertBefore(t, sidebar));
    sidebar.remove();
  }
  allTiles.forEach(t => t.classList.remove('pinned-tile'));
  grid.className = 'video-grid';
  if (count === 1) grid.classList.add('count-1');
  else if (count === 2) grid.classList.add('count-2');
  else if (count === 3) grid.classList.add('count-3');
  else if (count === 4) grid.classList.add('count-4');
  else if (count <= 6) grid.classList.add(`count-${count}`);
  else grid.classList.add('count-many');
}

/**
 * Bir kişiyi sabitler veya sabitlemeyi kaldırır (pin). Aynı kişiye tekrar basılırsa sabit kalkar.
 * Elle sabitleme yapılınca otomatik konuşmacı sabitleme kapanır.
 * peerId: sabitlenecek kişinin kimliği.
 */
function togglePin(peerId) {
  if (state.pinnedPeerId === peerId) {
    state.pinnedPeerId = null;
    showToast('Pin kaldırıldı');
  } else {
    state.pinnedPeerId = peerId;
    state.autoPinEnabled = false;
    showToast('Ekran sabitlendi 📌');
  }
  updateGrid();
}

/**
 * Konuşan kişiyi kaydeder ve gerekiyorsa düzeni yeniden çizer.
 * Kendi kutumuz için işlem yapılmaz; aynı kişi tekrar konuşursa boşuna çizim yapılmaz.
 */
function setSpeaking(peerId) {
  // Kendi ekranında otomatik pin olmasın
  if (peerId === state.peerId) return;
  if (state.speakingPeerId === peerId) return;
  state.speakingPeerId = peerId;
  if (!state.pinnedPeerId && state.autoPinEnabled) {
    updateGrid();
  }
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
    <div class="chat-msg-name">${isOwn ? 'Sen' : escapeHtml(String(msg.from_name ?? ''))}</div>
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
 * Tek bir dosyayı XMLHttpRequest ile odaya yükler ve yükleme yüzdesini gösterir.
 * Başarılıysa dosya kendi listemize eklenir; diğer kişilere sunucu file-shared mesajıyla bildirir.
 * Hata durumunda kullanıcıya mesaj gösterilir. Promise her durumda tamamlanır (çözülür), böylece sıradaki dosya beklemez.
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
  formData.append('token', state.joinToken);

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
// Önce oturum kontrol edilir; giriş yapılmamışsa kullanıcı girişe yönlenir.
oturumYukle().then(ok => { if (ok) initLobby(); });

// ─── Remote Control ──────────────────────────────────────────────────────────
// Uzak kontrol durumu. Bu tarayıcı başka bir kişinin ekranını izlerken (kontrolcü) bu alanlar dolar.
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
 * Bekleme penceresindeki İptal düğmesi. Oturum zaten açılmışsa sunucuya /api/control/stop isteği gönderip oturum kimliğini temizler.
 */
function cancelControlRequest() {
  showModal('remoteWaitModal', false);
  if (remote.sessionId) {
    // Oturum kapatma isteğinde join token POST gövdesinde gönderilir (URL'de değil).
    fetch('/api/control/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: state.joinToken, session_id: remote.sessionId })
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
  // Yalnızca uzak ekran görüntüleyici açıkken tuşları yakala.
  if (!remote.isViewing || document.getElementById('remoteViewer').style.display !== 'flex') return;
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
 * Uzak kontrolü bitirir: izleme penceresini kapatır, FPS sayacını durdurur, kontrol WebSocket'ine stop-control gönderip kapatır ve /api/control/stop ile oturumu sunucuda da sonlandırır.
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
      body: JSON.stringify({ token: state.joinToken, session_id: remote.sessionId })
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
// Hedef taraf (ekranı paylaşan kişi) için bekleyen kontrol isteği bilgileri. Onay ya da red sonrası sıfırlanır.
let pendingControlSession = null;
let pendingAgentKey = null;

/**
 * Hedef taraf: başka bir kişi kontrol istediğinde çalışır. Oturum kimliğini ve ajan anahtarını saklar, onay penceresini açar.
 * msg.controller_name: isteyen kişinin adı; msg.session_id, msg.agent_key: sunucudan gelen bilgiler.
 */
function onControlRequest(msg) {
  pendingControlSession = msg.session_id;
  pendingAgentKey = msg.agent_key;
  document.getElementById('remoteRequestText').textContent =
    `"${msg.controller_name}" adlı kullanıcı bilgisayarınızı kontrol etmek istiyor.`;
  showModal('remoteRequestModal', true);
}

/**
 * Hedef kişi 'İzin ver' dediğinde çalışır. Sunucuya onay gönderir ve Windows/Linux için ajan kurulum bilgilerini gösterir.
 * Ajan bu bilgilerle sunucuya bağlanıp ekranı paylaşır; bekleyen istek bilgisi sıfırlanır.
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
  const winInfo = `Sunucu: ${serverAddr}\nOturum Kodu: ${session}\nAjan Anahtarı: ${pendingAgentKey}`;
  document.getElementById('agentCmdWindows').textContent = winInfo;

  // Linux komutu
  const linuxCmd = `chmod +x linux_agent.sh && ./linux_agent.sh\n# Sunucu: ${serverAddr}\n# Oturum: ${session}\n# Ajan anahtarı: ${pendingAgentKey}`;
  document.getElementById('agentCmdLinux').textContent = linuxCmd;

  showModal('remoteAgentModal', true);
  pendingControlSession = null;
  pendingAgentKey = null;
}

/**
 * Ajan penceresindeki Windows / Linux sekmelerini değiştirir. Seçilen sekmenin içeriğini gösterir, diğerini gizler.
 * Not: event genel değişkeninden okunur; bu fonksiyon yalnızca tıklama olayından çağrılmalıdır.
 */
function switchOsTab(os, ev) {
  document.querySelectorAll('.os-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('osWindows').style.display = os === 'windows' ? 'flex' : 'none';
  document.getElementById('osLinux').style.display  = os === 'linux'   ? 'flex' : 'none';
  ev.target.classList.add('active');
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

// ─── TTS Pipeline ─────────────────────────────────────────────────────────────

/**
 * Sunucuya bu kişinin kayıtlı bir ses profili olup olmadığını sorar. Ses profili, çeviri sesinin kendi sesimize benzetilmesi için kullanılır (şu an sabit ses kullanılıyor).
 * Hata olursa false döner.
 * DİKKAT: join token URL sorgusunda gönderiliyor.
 */
async function checkVoiceProfile() {
  try {
    const res = await fetch(`/api/tts/voice-profile/status?token=${encodeURIComponent(state.joinToken)}`);
    const data = await res.json();
    state.hasVoiceProfile = data.exists;
    return data.exists;
  } catch (e) {
    console.error('Voice profile check error:', e);
    return false;
  }
}

/**
 * Mikrofondan 30 saniyelik ses kaydı alır ve bitince uploadVoiceProfile ile sunucuya yükler.
 * Süre dolunca kayıt otomatik durur. Mikrofon izni yoksa kullanıcıya bildirim gösterilir.
 */
async function startVoiceProfileRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    state.voiceProfileChunks = [];
    state.voiceProfileRecorder = new MediaRecorder(stream);

    state.voiceProfileRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) state.voiceProfileChunks.push(e.data);
    };

    state.voiceProfileRecorder.onstop = async () => {
      const blob = new Blob(state.voiceProfileChunks, { type: 'audio/wav' });
      await uploadVoiceProfile(blob);
      stream.getTracks().forEach(t => t.stop());
    };

    state.voiceProfileRecorder.start();
    showToast('🎙️ Ses profili kaydediliyor... 30 saniye konuşun');

    // 30 saniye sonra otomatik durdur
    setTimeout(() => {
      if (state.voiceProfileRecorder && state.voiceProfileRecorder.state === 'recording') {
        state.voiceProfileRecorder.stop();
      }
    }, 30000);

  } catch (e) {
    console.error('Voice profile recording error:', e);
    showToast('Mikrofon erişimi sağlanamadı');
  }
}

/**
 * Kaydedilen ses dosyasını base64'e çevirip sunucuya yükler. Parçalar halinde kodlanır, çünkü çok büyük diziler String.fromCharCode'da taşma yapar.
 * Başarılıysa hasVoiceProfile true olur. Hata olursa kullanıcıya bildirilir.
 */
async function uploadVoiceProfile(blob) {
  try {
    showToast('⏳ Ses profili işleniyor...');
    const arrayBuffer = await blob.arrayBuffer();
    const bytes = new Uint8Array(arrayBuffer);
    let binary = '';
    const chunkSize = 8192;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
    }
    const base64 = btoa(binary);

    const res = await fetch('/api/tts/voice-profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token: state.joinToken,
        audio_base64: base64,
      }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.success) {
      state.hasVoiceProfile = true;
      showToast('✅ Ses profili kaydedildi!');
    }
  } catch (e) {
    console.error('Voice profile upload error:', e);
    showToast('Ses profili yüklenemedi');
  }
}

/**
 * Anlık çeviri düğmesi. Açılınca konuşma tanımayı başlatır, kapanınca durdurur. Düğmenin rengi ve başlığı durumu gösterir.
 */
function toggleTTS() {
  state.ttsEnabled = !state.ttsEnabled;
  const btn = document.getElementById('ttsBtn');
  if (btn) {
    btn.classList.toggle('active', state.ttsEnabled);
    btn.title = state.ttsEnabled ? 'Çeviriyi Kapat' : 'Çeviriyi Aç';
  }

  if (state.ttsEnabled) {
    showToast('🌐 Anlık çeviri açıldı');
    startTTSCapture();
  } else {
    showToast('Çeviri kapatıldı');
    stopTTSCapture();
  }
}

/**
 * Türkçe konuşmayı yazıya çevirmeye (Web Speech API) başlar. Her cümle bitince processTTSText ile İngilizceye çevrilir.
 * Tanıma bittiğinde (onend) çeviri hâlâ açıksa otomatik yeniden başlatılır; böylece sürekli dinleme sağlanır.
 * Tarayıcı desteklemezse bildirim gösterilir.
 */
// Tarayıcının konuşma tanıma API'si. Chrome ve Edge'de webkit önekiyle gelir; Firefox desteklemez.
function startTTSCapture() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    showToast('Tarayıcınız konuşma tanımayı desteklemiyor');
    return;
  }
  state.ttsRecognition = new SpeechRecognition();
  state.ttsRecognition.lang = 'tr-TR';
  state.ttsRecognition.continuous = true;
  state.ttsRecognition.interimResults = false;
  state.ttsRecognition.onresult = async (event) => {
    const text = event.results[event.results.length - 1][0].transcript.trim();
    if (text && state.ttsEnabled) {
      await processTTSText(text);
    }
  };
  state.ttsRecognition.onerror = (e) => {
    console.error('Speech recognition error:', e.error);
  };
  state.ttsRecognition.onend = () => {
    if (state.ttsEnabled) {
      state.ttsRecognition.start();
    }
  };
  state.ttsRecognition.start();
}
/**
 * Konuşma tanımayı durdurur. onend olayı önce temizlenir ki durdurunca otomatik yeniden başlatma tetiklenmesin.
 */
function stopTTSCapture() {
  if (state.ttsRecognition) {
    state.ttsRecognition.onend = null;
    state.ttsRecognition.stop();
    state.ttsRecognition = null;
  }
}
let currentTTSAudio = null;
/**
 * Base64 kodlu WAV sesini çalar. Önce çalan ses varsa durdurulur, böylece çeviri sesleri üst üste binmez.
 * Bitince nesne URL'si serbest bırakılır (bellek sızıntısı olmaz).
 */
async function playTTSAudio(base64Audio) {
  try {
    if (currentTTSAudio) {
      currentTTSAudio.pause();
      currentTTSAudio = null;
    }
    const binary = atob(base64Audio);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: 'audio/wav' });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentTTSAudio = audio;
    audio.play();
    audio.onended = () => { URL.revokeObjectURL(url); currentTTSAudio = null; };
  } catch (e) {
    console.error('TTS audio play error:', e);
  }
}
/**
 * Konuşulan Türkçe metni sunucunun çeviri servisine gönderir (TR -> EN) ve dönen sesi çalar.
 * Aynı anda yalnızca bir çeviri işlenir (ttsProcessing kilidi).
 * Ses, diğer kişilere tts-audio mesajıyla da gönderilir.
 * Hata olursa en fazla 10 saniyede bir uyarı gösterilir.
 * text: tanınan Türkçe cümle.
 */
async function processTTSText(text) {
  if (state.ttsProcessing) return;
  state.ttsProcessing = true;
  try {
    const res = await fetch('/api/tts/synthesize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token: state.joinToken,
        audio_base64: '',
        text: text,
        source_lang: 'tr',
        target_lang: 'en',
        session_id: state.roomId,
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.audio_base64) {
      playTTSAudio(data.audio_base64);
      sendSignal({
        type: 'tts-audio',
        audio_base64: data.audio_base64,
        from_name: state.userName,
      });
    }
  } catch (e) {
    console.error('TTS text error:', e);
    const simdi = Date.now();
    if (simdi - (state.ttsSonHataToast || 0) > 10000) {  // toast'ı tekrar tekrar basma
      state.ttsSonHataToast = simdi;
      showToast('Çeviri servisi şu an yanıt vermiyor.');
    }
  } finally {
    state.ttsProcessing = false;
  }
}

