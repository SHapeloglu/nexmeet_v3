#!/usr/bin/env python3
"""
NexMeet Uzak Kontrol Ajanı
===========================
Bu script kontrol edilmek isteyen bilgisayarda çalışır.
Karşı taraftan gelen fare/klavye komutlarını uygular ve ekran görüntüsü gönderir.

Kurulum:
    pip install pyautogui mss websockets pillow

Kullanım:
    python agent.py --server ws://SUNUCU_IP:8000 --session OTURUM_ID
    veya
    python agent.py  (GUI modunda çalışır, sunucu ve oturum kodu girilir)
"""

import asyncio
import base64
import json
import os
import sys
import time
import argparse
import threading
import io
import platform
import logging

try:
    import websockets
except ImportError:
    print("❌ 'websockets' paketi bulunamadı. Kurun: pip install websockets")
    sys.exit(1)

try:
    import pyautogui
    pyautogui.FAILSAFE = True   # Sol üst köşeye fare götürünce durdur
    pyautogui.PAUSE = 0.01
except ImportError:
    print("❌ 'pyautogui' paketi bulunamadı. Kurun: pip install pyautogui")
    sys.exit(1)

try:
    import mss
    import mss.tools
except ImportError:
    print("❌ 'mss' paketi bulunamadı. Kurun: pip install mss")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("❌ 'pillow' paketi bulunamadı. Kurun: pip install pillow")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("nexmeet-agent")

# ─── Config ──────────────────────────────────────────────────────────────────
FRAME_QUALITY   = 50    # JPEG kalitesi (1-95), düşük = daha hızlı ama kalitesiz
FRAME_WIDTH     = 1280  # Gönderilen frame genişliği (küçültme)
FRAME_INTERVAL  = 0.05  # Saniyede ~20 kare (0.05s aralık)
# Ajan kimliği başlangıç zamanından üretilir. Aynı saniyede iki ajan başlarsa kimlikleri çakışabilir.
AGENT_ID        = f"agent-{int(time.time())}"

# ─── State ───────────────────────────────────────────────────────────────────
running = True
session_active = False
ws_connection = None


# ─── Ekran Yakalama ──────────────────────────────────────────────────────────
def capture_screen_base64(monitor_num: int = 1) -> tuple[str, int, int]:
    """Ekranı yakala, JPEG olarak sıkıştır, base64 döndür."""
    with mss.mss() as sct:
        monitors = sct.monitors
        # monitors[0] = tüm ekranlar birleşik, monitors[1]+ = tek tek
        mon_index = min(monitor_num, len(monitors) - 1)
        monitor = monitors[mon_index]

        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

        # Yeniden boyutlandır (bant genişliği için)
        orig_w, orig_h = img.size
        if orig_w > FRAME_WIDTH:
            ratio = FRAME_WIDTH / orig_w
            new_h = int(orig_h * ratio)
            img = img.resize((FRAME_WIDTH, new_h), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=FRAME_QUALITY, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return b64, img.width, img.height


def get_monitor_count() -> int:
    """Bağlı ekran sayısını döner (en az 1). mss'in ilk öğesi tüm ekranların birleşimidir; bu yüzden sayıdan bir çıkarılır."""
    with mss.mss() as sct:
        return max(len(sct.monitors) - 1, 1)


# ─── Fare & Klavye Komutları ─────────────────────────────────────────────────
def scale_coords(x: float, y: float, frame_w: int, frame_h: int) -> tuple[int, int]:
    """Frontend'deki koordinatları gerçek ekran koordinatlarına çevir."""
    with mss.mss() as sct:
        mon = sct.monitors[1]
        screen_w = mon["width"]
        screen_h = mon["height"]

    real_x = int((x / frame_w) * screen_w)
    real_y = int((y / frame_h) * screen_h)
    return real_x, real_y


def handle_command(data: dict, frame_w: int, frame_h: int):
    """Gelen komutları uygula."""
    cmd = data.get("type")

    try:
        if cmd == "mouse-move":
            rx, ry = scale_coords(data["x"], data["y"], frame_w, frame_h)
            pyautogui.moveTo(rx, ry, duration=0)

        elif cmd == "mouse-click":
            rx, ry = scale_coords(data["x"], data["y"], frame_w, frame_h)
            btn = data.get("button", "left")
            if data.get("double"):
                pyautogui.doubleClick(rx, ry, button=btn)
            else:
                pyautogui.click(rx, ry, button=btn)

        elif cmd == "mouse-down":
            rx, ry = scale_coords(data["x"], data["y"], frame_w, frame_h)
            pyautogui.mouseDown(rx, ry, button=data.get("button", "left"))

        elif cmd == "mouse-up":
            rx, ry = scale_coords(data["x"], data["y"], frame_w, frame_h)
            pyautogui.mouseUp(rx, ry, button=data.get("button", "left"))

        elif cmd == "mouse-scroll":
            rx, ry = scale_coords(data["x"], data["y"], frame_w, frame_h)
            pyautogui.scroll(data.get("delta", 3), x=rx, y=ry)

        elif cmd == "key-press":
            key = data.get("key", "")
            mods = data.get("modifiers", [])
            if mods:
                pyautogui.hotkey(*mods, key)
            else:
                pyautogui.press(key)

        elif cmd == "key-type":
            text = data.get("text", "")
            pyautogui.typewrite(text, interval=0.02)

    except pyautogui.FailSafeException:
        logger.warning("FailSafe tetiklendi - fare sol üst köşeye gitti!")
    except Exception as e:
        logger.error(f"Komut hatası ({cmd}): {e}")


# ─── WebSocket Ana Döngü ─────────────────────────────────────────────────────
async def run_agent(server_url: str, session_id: str, key: str = "", monitor_num: int = 1):
    """Ajanı sunucuya bağlar ve oturumu agent-ready mesajıyla kaydeder. İki işi aynı anda yürütür: ekran karelerini gönderen görev ve sunucudan gelen fare/klavye komutlarını uygulayan döngü. stop-control gelince ya da bağlantı kopunca çıkar. Hataları loglar, dışarı fırlatmaz."""
    global running, session_active, ws_connection

    # Bu adres ajan anahtarını (key) içerir; bu yüzden loga anahtarsız hâli yazılır (terminale/loglara anahtar düşmesin).
    agent_ws_url = server_url.rstrip("/") + f"/ws/agent/{AGENT_ID}?key={key}&session_id={session_id}"
    logger.info(f"Sunucuya bağlanılıyor: {server_url.rstrip('/')}/ws/agent/{AGENT_ID}?key=***&session_id={session_id}")

    frame_w, frame_h = FRAME_WIDTH, 720  # Başlangıç tahmini

    try:
        async with websockets.connect(
            agent_ws_url,
            ping_interval=20,
            ping_timeout=10,
            max_size=10 * 1024 * 1024  # 10MB max mesaj
        ) as ws:
            ws_connection = ws
            logger.info("✅ Sunucuya bağlandı!")

            # Oturumu kaydet
            await ws.send(json.dumps({
                "type": "agent-ready",
                "session_id": session_id,
                "agent_id": AGENT_ID,
                "platform": platform.system(),
                "monitors": get_monitor_count(),
            }))

            session_active = True
            logger.info(f"🎮 Oturum aktif: {session_id}")
            logger.info("⚠️  Kontrolü durdurmak için: fare sol üst köşeye götür (FailSafe)")

            # Frame gönderme görevi
            async def send_frames():
                """Ekranı yaklaşık saniyede 20 kez yakalayıp sunucuya gönderir. Bir kare hata verirse loglanır ve döngü devam eder. Kontrol durunca iptal edilir."""
                nonlocal frame_w, frame_h
                while running and session_active:
                    try:
                        b64, fw, fh = capture_screen_base64(monitor_num)
                        frame_w, frame_h = fw, fh
                        await ws.send(json.dumps({
                            "type": "frame",
                            "session_id": session_id,
                            "frame": b64,
                            "width": fw,
                            "height": fh,
                        }))
                    except Exception as e:
                        logger.error(f"Frame hatası: {e}")
                    await asyncio.sleep(FRAME_INTERVAL)

            frame_task = asyncio.create_task(send_frames())

            # Komut alma döngüsü
            try:
                async for message in ws:
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "stop-control":
                        logger.info("🛑 Kontrol durduruldu")
                        session_active = False
                        frame_task.cancel()
                        break

                    elif msg_type in [
                        "mouse-move", "mouse-click", "mouse-down", "mouse-up",
                        "mouse-scroll", "key-press", "key-type"
                    ]:
                        # Komutları arka planda çalıştır (asyncio'yu bloklamayı önle)
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(
                            None, handle_command, data, frame_w, frame_h
                        )

            except websockets.exceptions.ConnectionClosed:
                logger.info("Bağlantı kapandı")
            finally:
                frame_task.cancel()

    except ConnectionRefusedError:
        logger.error(f"❌ Sunucuya bağlanılamadı: {server_url}")
        logger.error("Sunucunun çalıştığından ve adresi doğru girdiğinizden emin olun.")
    except Exception as e:
        logger.error(f"❌ Bağlantı hatası: {e}")


# ─── GUI (Tkinter) ───────────────────────────────────────────────────────────
def run_gui():
    """Tkinter ile basit bir GUI arayüzü."""
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError:
        print("Tkinter bulunamadı, komut satırı modunda devam ediliyor.")
        run_cli_interactive()
        return

    root = tk.Tk()
    root.title("NexMeet — Uzak Kontrol Ajanı")
    root.geometry("420x320")
    root.configure(bg="#0a0a0f")
    root.resizable(False, False)

    # Stil
    style = ttk.Style()
    style.theme_use('clam')

    fg = "#f0f0f5"
    bg = "#0a0a0f"
    surface = "#13131a"
    accent = "#6EE7B7"

    root.configure(bg=bg)

    # Başlık
    title_frame = tk.Frame(root, bg=bg)
    title_frame.pack(pady=(20, 10))
    tk.Label(title_frame, text="🎮", font=("Arial", 32), bg=bg).pack()
    tk.Label(title_frame, text="NexMeet Uzak Kontrol Ajanı",
             font=("Arial", 14, "bold"), fg=fg, bg=bg).pack()
    tk.Label(title_frame, text="Bu bilgisayarın uzaktan kontrol edilmesine izin verir",
             font=("Arial", 9), fg="#6b6b80", bg=bg).pack(pady=(4, 0))

    # Form
    form = tk.Frame(root, bg=bg)
    form.pack(padx=30, fill="x", pady=10)

    def labeled_entry(parent, label, default=""):
        """Üstünde etiket olan bir metin kutusu oluşturur ve kutuyu döner. default verilirse kutuya ilk değer olarak yazılır."""
        tk.Label(parent, text=label, font=("Arial", 10), fg="#6b6b80", bg=bg,
                 anchor="w").pack(fill="x", pady=(8, 2))
        e = tk.Entry(parent, font=("Arial", 11), bg=surface, fg=fg,
                     insertbackground=fg, relief="flat",
                     highlightthickness=1, highlightcolor=accent,
                     highlightbackground="#1c1c28")
        e.insert(0, default)
        e.pack(fill="x", ipady=6)
        return e

    server_entry = labeled_entry(form, "Sunucu Adresi", "ws://localhost:8000")
    session_entry = labeled_entry(form, "Oturum Kodu (NexMeet'ten kopyala)")
    key_entry = labeled_entry(form, "Ajan Anahtarı (NexMeet'ten kopyala)")

    # Monitor seçimi
    mon_count = get_monitor_count()
    tk.Label(form, text="Ekran Seç", font=("Arial", 10), fg="#6b6b80",
             bg=bg, anchor="w").pack(fill="x", pady=(8, 2))
    mon_var = tk.StringVar(value="1")
    mon_frame = tk.Frame(form, bg=bg)
    mon_frame.pack(fill="x")
    for i in range(1, mon_count + 1):
        tk.Radiobutton(mon_frame, text=f"Ekran {i}", variable=mon_var, value=str(i),
                       bg=bg, fg=fg, selectcolor=surface,
                       activebackground=bg, activeforeground=accent,
                       font=("Arial", 10)).pack(side="left", padx=(0, 10))

    # Durum etiketi
    status_var = tk.StringVar(value="Hazır")
    status_lbl = tk.Label(root, textvariable=status_var, font=("Arial", 10),
                          fg="#6b6b80", bg=bg)
    status_lbl.pack(pady=(5, 0))

    # Bağlan butonu
    connect_btn = tk.Button(root, text="Bağlan & Bekle",
                            font=("Arial", 12, "bold"),
                            bg=accent, fg="#0a0a0f",
                            relief="flat", padx=20, pady=8,
                            cursor="hand2",
                            activebackground="#5dd4a6",
                            activeforeground="#0a0a0f")
    connect_btn.pack(pady=10)

    def on_connect():
        """Bağlan düğmesine basılınca çalışır. Üç alanın dolu olduğunu kontrol eder, ardından ajanı ayrı bir iş parçacığında (thread) başlatır. Böylece pencere bağlantı sırasında donmaz."""
        server = server_entry.get().strip()
        session = session_entry.get().strip()
        key = key_entry.get().strip()
        monitor = int(mon_var.get())

        if not server or not session or not key:
            messagebox.showerror("Hata", "Sunucu adresi, oturum kodu ve ajan anahtarı gerekli!")
            return

        status_var.set("🔄 Bağlanılıyor...")
        connect_btn.config(state="disabled")

        def run():
            """Ajan döngüsünü arka plan thread'inde çalıştırır. Hata olursa sessizce yutulur ve kullanıcıya yalnız bağlantı kesildi mesajı gösterilir. Bitince düğme yeniden etkinleştirilir."""
            try:
                asyncio.run(run_agent(server, session, key, monitor))
            except Exception as e:
                pass
            root.after(0, lambda: [
                status_var.set("❌ Bağlantı kesildi"),
                connect_btn.config(state="normal")
            ])

        threading.Thread(target=run, daemon=True).start()
        status_var.set("✅ Bağlı — Kontrol bekleniyor...")

    connect_btn.config(command=on_connect)
    root.mainloop()


def run_cli_interactive():
    """Komut satırı etkileşimli mod."""
    print("\n" + "="*50)
    print("  NexMeet Uzak Kontrol Ajanı")
    print("="*50)
    server = input("Sunucu adresi (örn: ws://192.168.1.10:8000): ").strip()
    session = input("Oturum kodu: ").strip()
    key = input("Ajan anahtarı (NexMeet'ten kopyala): ").strip()
    mon_count = get_monitor_count()
    if mon_count > 1:
        mon = int(input(f"Ekran numarası (1-{mon_count}): ").strip() or "1")
    else:
        mon = 1
    asyncio.run(run_agent(server, session, key, mon))


# ─── Anahtar Çözümleme ───────────────────────────────────────────────────────
def anahtar_coz(args_key, args_key_file, env=None):
    """
    Ajan anahtarını üç kaynaktan bulup döndürür. Öncelik sırası yukarıdan aşağıya:

      1. --key-file: dosyanın ilk satırı (baş/son boşluklar silinir).
      2. --key: eski yöntem. Çalışmaya devam eder ama komut satırı ps listesinde
         herkes tarafından görülebildiği için uyarı yazılır.
      3. NEXMEET_AGENT_KEY ortam değişkeni.

    Parametreler:
        args_key: --key değeri. "" ise verilmemiş demektir.
        args_key_file: --key-file değeri. None ya da "" ise verilmemiş demektir.
        env: ortam değişkenleri sözlüğü. Verilmezse os.environ kullanılır
             (test ederken sahte bir sözlük verilebilir).

    Dönüş: anahtar metni. Hiçbir kaynakta anahtar yoksa "" döner.
    Hata: --key-file okunamaz ya da boşsa Türkçe hata yazılır ve sys.exit(1) çağrılır.

    Not: Anahtar hiçbir zaman loga ya da ekrana yazılmaz; uyarı ve hata
    mesajları yalnızca dosya/seçenek adını gösterir.
    """
    if env is None:
        env = os.environ

    # --key kullanıldıysa uyarı basılır. Dosya öncelikli olsa bile, kullanıcı eski yöntemi
    # kullanmakta olduğunu öğrensin diye uyarı en başta yazılır.
    if args_key:
        print(
            "UYARI: --key ile anahtar verdiniz. Komut satırındaki anahtar süreç listesinde (ps) "
            "herkese görünür. Bunun yerine NEXMEET_AGENT_KEY ortam değişkenini ya da "
            "--key-file DOSYA seçeneğini kullanın. --key ileride kaldırılacaktır.",
            file=sys.stderr,
        )

    # 1. En yüksek öncelik: --key-file. Dosya okunamazsa başka kaynağa düşmek yerine hemen çıkılır;
    #    yanlış bir dosya sessizce yok sayılırsa kullanıcı neden bağlanamadığını anlayamaz.
    if args_key_file:
        try:
            # encoding: Dosyanın Türkçe karakter içerse de doğru okunması için UTF-8 belirtilir.
            with open(args_key_file, "r", encoding="utf-8") as f:
                # Yalnız ilk satır alınır; dosyada fazladan satır olsa da anahtar ilk satırdır.
                anahtar = f.readline().strip()
        except (OSError, UnicodeDecodeError) as e:
            print(f"HATA: Anahtar dosyası okunamadı: {args_key_file} ({e})", file=sys.stderr)
            sys.exit(1)
        # Boş dosya da hata sayılır. Yoksa ajan boş anahtarla bağlanır ve sebebi anlaşılmaz bir hata verir.
        if not anahtar:
            print(f"HATA: Anahtar dosyası boş: {args_key_file} (ilk satır anahtar olmalı)", file=sys.stderr)
            sys.exit(1)
        return anahtar

    # 2. Eski yöntem: --key değeri olduğu gibi döndürülür (geriye uyum için kırpılmaz).
    if args_key:
        return args_key

    # 3. Ortam değişkeni: ps argümanlarında görünmez. linux_agent.sh ve windows_agent.bat bunu kullanır.
    return env.get("NEXMEET_AGENT_KEY", "").strip()


# ─── Ana Giriş ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NexMeet Uzak Kontrol Ajanı")
    parser.add_argument("--server", help="WebSocket sunucu adresi (ws://host:8000)")
    parser.add_argument("--session", help="Oturum ID")
    # --key ps listesinde görünür; bu yüzden eski ve uyarılı bir seçenek olarak tutuluyor.
    parser.add_argument("--key", help="Ajan anahtarı (ESKİ, ps'te görünür; NEXMEET_AGENT_KEY ya da --key-file kullanın)", default="")
    # --key-file: anahtarı komut satırına yazmadan, dosyadan okutmak için.
    parser.add_argument("--key-file", metavar="DOSYA", help="Ajan anahtarının bulunduğu dosya (ilk satır okunur)")
    parser.add_argument("--monitor", type=int, default=1, help="Ekran numarası (varsayılan: 1)")
    parser.add_argument("--nogui", action="store_true", help="GUI olmadan çalıştır")
    args = parser.parse_args()

    if args.server and args.session:
        # Doğrudan parametrelerle çalıştır. Anahtar, öncelik sırasına göre bulunur (bkz. anahtar_coz).
        logger.info(f"Ekran {args.monitor} paylaşılıyor...")
        anahtar = anahtar_coz(args.key, args.key_file)
        asyncio.run(run_agent(args.server, args.session, anahtar, args.monitor))
    elif args.nogui:
        run_cli_interactive()
    else:
        run_gui()
