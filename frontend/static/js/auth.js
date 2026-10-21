/* NexMeet — üyelik sayfaları ortak betiği (giriş, kayıt, doğrulama, parola sıfırlama). */

(function () {
  'use strict';

  // Sunucudaki YONLENDIRME_RE ile aynı kural: yalnız "/" veya "/room/<id>"
  const YONLENDIRME_RE = /^\/(room\/[^/\\?#%\s\x00-\x1f\x7f]{1,64})?$/;

  function guvenliYonlendirme(ham) {
    return ham && YONLENDIRME_RE.test(ham) ? ham : '/';
  }

  function parametre(ad) {
    return new URLSearchParams(location.search).get(ad);
  }

  function bildir(el, metin, tur) {
    el.textContent = metin || '';
    el.className = 'auth-mesaj ' + (tur || 'hata');
    el.hidden = !metin;
  }

  async function istek(url, govde) {
    let res;
    try {
      res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(govde || {}),
      });
    } catch (e) {
      return { ok: false, durum: 0, mesaj: 'Sunucuya ulaşılamadı. İnternet bağlantınızı kontrol edin.', veri: {} };
    }
    let veri = {};
    try { veri = await res.json(); } catch (e) { veri = {}; }
    let mesaj = typeof veri.detail === 'string' ? veri.detail : (typeof veri.mesaj === 'string' ? veri.mesaj : '');
    if (res.status === 429) {
      mesaj = 'Çok fazla istek gönderdiniz. Lütfen biraz bekleyip tekrar deneyin.';
    } else if (res.status === 503) {
      mesaj = 'Üyelik servisi şu an kullanılamıyor. Lütfen daha sonra tekrar deneyin.';
    } else if (!res.ok && !mesaj) {
      mesaj = 'Beklenmeyen bir hata oluştu.';
    }
    return { ok: res.ok, durum: res.status, mesaj: mesaj, veri: veri };
  }

  // ── Giriş ──
  const girisForm = document.getElementById('girisForm');
  if (girisForm) {
    const mesajEl = document.getElementById('mesaj');
    const girisBtn = document.getElementById('girisBtn');
    const tekrarBtn = document.getElementById('tekrarBtn');
    let sonEposta = '';

    girisForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const eposta = girisForm.eposta.value.trim();
      const parola = girisForm.parola.value;
      sonEposta = eposta;
      tekrarBtn.hidden = true;
      girisBtn.disabled = true;
      const r = await istek('/api/auth/giris', {
        eposta: eposta,
        parola: parola,
        yonlendirme: parametre('next'),
      });
      if (r.ok) {
        location.href = guvenliYonlendirme(r.veri.yonlendirme);
        return;
      }
      girisBtn.disabled = false;
      if (r.veri && r.veri.kod === 'dogrulanmamis') {
        bildir(mesajEl, r.mesaj, 'uyari');
        tekrarBtn.hidden = false;
      } else {
        bildir(mesajEl, r.mesaj, 'hata');
      }
    });

    tekrarBtn.addEventListener('click', async () => {
      tekrarBtn.disabled = true;
      const r = await istek('/api/auth/dogrulama-tekrar', { eposta: sonEposta });
      bildir(mesajEl, r.mesaj, r.ok ? 'basari' : 'hata');
      tekrarBtn.disabled = false;
    });
  }

  // ── Kayıt ──
  const kayitForm = document.getElementById('kayitForm');
  if (kayitForm) {
    const mesajEl = document.getElementById('mesaj');
    const kayitBtn = document.getElementById('kayitBtn');
    kayitForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      kayitBtn.disabled = true;
      const r = await istek('/api/auth/kayit', {
        ad_soyad: kayitForm.ad_soyad.value,
        eposta: kayitForm.eposta.value,
        parola: kayitForm.parola.value,
      });
      if (r.ok) {
        kayitForm.hidden = true;
        bildir(mesajEl, r.mesaj + ' Gelen kutunuzdaki bağlantıya tıklayarak hesabınızı etkinleştirin. Mail gelmediyse spam klasörünü kontrol edin.', 'basari');
        return;
      }
      bildir(mesajEl, r.mesaj, 'hata');
      kayitBtn.disabled = false;
    });
  }

  // ── E-posta doğrulama (sayfa açılınca otomatik gönderilir; e-posta tarayıcıları bağlantıyı tüketmez) ──
  const dogrulaMesaj = document.getElementById('dogrulaMesaj');
  if (dogrulaMesaj) {
    const token = parametre('token');
    const sonuc = document.getElementById('dogrulaSonuc');
    (async () => {
      if (!token) {
        bildir(dogrulaMesaj, 'Doğrulama bağlantısı eksik. E-postadaki bağlantının tamamını açın.', 'hata');
        return;
      }
      const r = await istek('/api/auth/dogrula', { token: token });
      if (r.ok) {
        bildir(dogrulaMesaj, r.mesaj, 'basari');
      } else {
        bildir(dogrulaMesaj, r.mesaj + ' Giriş sayfasından yeni bir doğrulama bağlantısı isteyebilirsiniz.', 'hata');
      }
      if (sonuc) sonuc.hidden = false;
    })();
  }

  // ── Şifremi unuttum ──
  const sifreUnutForm = document.getElementById('sifreUnutForm');
  if (sifreUnutForm) {
    const mesajEl = document.getElementById('mesaj');
    const btn = document.getElementById('gonderBtn');
    sifreUnutForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      btn.disabled = true;
      const r = await istek('/api/auth/sifre-unuttum', { eposta: sifreUnutForm.eposta.value });
      bildir(mesajEl, r.mesaj, r.ok ? 'basari' : 'hata');
      if (r.ok) sifreUnutForm.hidden = true; else btn.disabled = false;
    });
  }

  // ── Parola sıfırlama ──
  const sifreSifirlaForm = document.getElementById('sifreSifirlaForm');
  if (sifreSifirlaForm) {
    const mesajEl = document.getElementById('mesaj');
    const btn = document.getElementById('sifirlaBtn');
    const token = parametre('token');
    sifreSifirlaForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const p1 = sifreSifirlaForm.parola.value;
      const p2 = sifreSifirlaForm.parola2.value;
      if (p1 !== p2) {
        bildir(mesajEl, 'Parolalar eşleşmiyor.', 'hata');
        return;
      }
      if (!token) {
        bildir(mesajEl, 'Sıfırlama bağlantısı eksik. E-postadaki bağlantıyı açın.', 'hata');
        return;
      }
      btn.disabled = true;
      const r = await istek('/api/auth/sifre-sifirla', { token: token, parola: p1 });
      if (r.ok) {
        bildir(mesajEl, r.mesaj, 'basari');
        sifreSifirlaForm.hidden = true;
      } else {
        bildir(mesajEl, r.mesaj, 'hata');
        btn.disabled = false;
      }
    });
  }
})();
