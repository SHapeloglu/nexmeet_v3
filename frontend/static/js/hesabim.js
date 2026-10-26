/* NexMeet — Hesabım sayfası: oturum bilgisi ve hesap silme. Metinler textContent ile yazılır (innerHTML yok). */

(function () {
  'use strict';

  const mesajEl = document.getElementById('mesaj');
  const adEl = document.getElementById('hesapAd');
  const epostaEl = document.getElementById('hesapEposta');
  const form = document.getElementById('hesapSilForm');
  const silBtn = document.getElementById('silBtn');

  function bildir(metin, tur) {
    mesajEl.textContent = metin || '';
    mesajEl.className = 'auth-mesaj ' + (tur || 'hata');
    mesajEl.hidden = !metin;
  }

  function girisEkrani() {
    location.href = '/giris?' + new URLSearchParams({ next: '/hesabim' }).toString();
  }

  // Düğme yalnız parola girilip onay kutusu işaretlendiğinde açılır.
  function dugmeyiGuncelle() {
    silBtn.disabled = !(form.onay.checked && form.parola.value.length > 0);
  }

  form.parola.addEventListener('input', dugmeyiGuncelle);
  form.onay.addEventListener('change', dugmeyiGuncelle);

  // Oturum bilgisi: çerez yoksa / süresi dolmuşsa girişe dön.
  (async () => {
    let res;
    try {
      res = await fetch('/api/ben', { credentials: 'same-origin' });
    } catch (e) {
      bildir('Sunucuya ulaşılamadı. Sayfayı yenileyip tekrar deneyin.', 'hata');
      return;
    }
    if (res.status === 401) {
      girisEkrani();
      return;
    }
    if (!res.ok) {
      bildir('Hesap bilgisi alınamadı. Lütfen daha sonra tekrar deneyin.', 'hata');
      return;
    }
    const veri = await res.json();
    adEl.textContent = veri.display_name || '';
    epostaEl.textContent = veri.email ? '(' + veri.email + ')' : '';
  })();

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (silBtn.disabled) return;
    silBtn.disabled = true;

    let res;
    try {
      res = await fetch('/api/auth/hesabi-sil', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ parola: form.parola.value }),
      });
    } catch (err) {
      bildir('Sunucuya ulaşılamadı. İnternet bağlantınızı kontrol edin.', 'hata');
      dugmeyiGuncelle();
      return;
    }

    if (res.ok) {
      // Hesap ve oturum silindi; çerez sunucuda temizlendi.
      location.href = '/giris';
      return;
    }

    form.parola.value = '';
    if (res.status === 401) {
      girisEkrani();
      return;
    }
    if (res.status === 403) {
      bildir('Parola hatalı.', 'hata');
    } else if (res.status === 429) {
      bildir('Çok fazla hatalı deneme yapıldı. Lütfen bir süre bekleyip tekrar deneyin.', 'hata');
    } else {
      bildir('Hesap silinemedi. Lütfen daha sonra tekrar deneyin.', 'hata');
    }
    form.parola.focus();
    dugmeyiGuncelle();
  });
})();
