"""Konuşmacı başına ayrı TTS iş kuyruğu. Her konuşmacının sesi kendi kuyruğunda ve kendi worker'ında işlenir; biri diğerini bekletmez.
Kuyruk dolarsa en eski iş atılır (gecikme birikiyor demektir). Worker 30 saniye iş gelmezse kendini durdurur, yeni iş gelince yeniden başlar.
Bu dosya tts paketinin parçasıdır ve canlı sistemde kullanılmaz (bkz. engine.py)."""
import asyncio
import uuid
import time
import logging
from typing import Dict, Callable, Optional

logger = logging.getLogger(__name__)

class TTSQueue:
    """
    Kullanıcı başına ayrı kuyruk.
    10 kişi aynı anda konuşsa bile birbirini bloklamaz.
    """
    def __init__(self):
        """Kuyruk ve worker sözlüklerini boş oluşturur. _running shutdown çağrılana kadar True kalır ve worker döngüsünü ayakta tutar."""
        self._queues: Dict[str, asyncio.Queue] = {}
        self._workers: Dict[str, asyncio.Task] = {}
        self._running = True

    def get_queue(self, peer_id: str) -> asyncio.Queue:
        """Konuşmacının iş kuyruğunu döner, yoksa oluşturur. Kuyruk en fazla 5 iş tutar; böylece gecikme birikmesi sınırlanır."""
        if peer_id not in self._queues:
            self._queues[peer_id] = asyncio.Queue(maxsize=5)
        return self._queues[peer_id]

    async def enqueue(
        self,
        peer_id: str,
        audio_path: str,
        source_lang: str,
        target_lang: str,
        callback: Callable,
    ):
        """
        İşlenecek ses chunk'ını kuyruğa ekle.
        Kuyruk doluysa en eskiyi at (gecikme birikiyor demek).
        """
        queue = self.get_queue(peer_id)
        job = {
            "id": str(uuid.uuid4()),
            "peer_id": peer_id,
            "audio_path": audio_path,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "callback": callback,
            "enqueued_at": time.time(),
        }
        if queue.full():
            try:
                queue.get_nowait()  # En eskiyi at
                logger.warning(f"Queue full for {peer_id}, dropping oldest job")
            except asyncio.QueueEmpty:
                pass
        await queue.put(job)

        # Worker yoksa başlat
        if peer_id not in self._workers or self._workers[peer_id].done():
            self._workers[peer_id] = asyncio.create_task(
                self._worker(peer_id)
            )

    async def _worker(self, peer_id: str):
        """Her kullanıcı için ayrı worker."""
        from .engine import TTSEngine
        engine = TTSEngine.get_instance()
        queue = self.get_queue(peer_id)

        while self._running:
            try:
                job = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                break  # 30sn iş gelmezse worker durur

            try:
                start = time.time()
                output_path = f"/tmp/tts_{job['id']}.wav"

                result = await engine.process_speech(
                    audio_path=job["audio_path"],
                    speaker_peer_id=job["peer_id"],
                    source_lang=job["source_lang"],
                    target_lang=job["target_lang"],
                    output_path=output_path,
                )

                elapsed = time.time() - start
                logger.info(f"TTS processed in {elapsed:.2f}s for {peer_id}")

                if result and job["callback"]:
                    await job["callback"](result, job)

            except Exception as e:
                logger.error(f"Worker error for {peer_id}: {e}")
            finally:
                queue.task_done()

    def remove_peer(self, peer_id: str):
        """Kullanıcı ayrılınca temizle."""
        if peer_id in self._workers:
            self._workers[peer_id].cancel()
            del self._workers[peer_id]
        if peer_id in self._queues:
            del self._queues[peer_id]

    async def shutdown(self):
        """Uygulama kapanırken çalışır. Yeni iş işlenmesini durdurur ve tüm worker görevlerini iptal eder."""
        self._running = False
        for task in self._workers.values():
            task.cancel()


# Singleton
tts_queue = TTSQueue()
