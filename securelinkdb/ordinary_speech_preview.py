"""A private loopback stream for the desktop's temporary speech preview."""

import asyncio
import json
import logging


PREVIEW_PORT = 8081
SUBSCRIBE = b"securelink-desktop-preview/1\n"
MAX_BUFFER_BYTES = 16 * 1024
logger = logging.getLogger("securelink.speech_preview")


class OrdinarySpeechPreview:
    def __init__(self):
        self.server = None
        self._subscriber = None

    async def start(self, port: int = PREVIEW_PORT):
        try:
            self.server = await asyncio.start_server(
                self._subscribe, "127.0.0.1", port, limit=128
            )
        except OSError:
            logger.warning("Local ordinary-speech preview port is unavailable")

    async def stop(self):
        if self.server is not None:
            self.server.close()
        if self._subscriber is not None:
            self._subscriber.close()
            self._subscriber = None
        if self.server is not None:
            await self.server.wait_closed()

    async def _subscribe(self, reader, writer):
        try:
            if await asyncio.wait_for(reader.readline(), 2) != SUBSCRIBE:
                return
            if self._subscriber is not None and not self._subscriber.is_closing():
                return
            self._subscriber = writer
            writer.write(b'{"ready":true}\n')
            await writer.drain()
            # Close on disconnect or on any unexpected client data.
            await reader.read(1)
        except (OSError, ValueError, TimeoutError):
            pass
        finally:
            if self._subscriber is writer:
                self._subscriber = None
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    def publish(self, transcript: str, category: str, score: float):
        writer = self._subscriber
        if writer is None or writer.is_closing():
            return
        payload = json.dumps({
            "transcript": transcript,
            "category": category,
            "score": float(score),
        }, ensure_ascii=False).encode("utf-8") + b"\n"
        if writer.transport.get_write_buffer_size() + len(payload) > MAX_BUFFER_BYTES:
            return
        try:
            writer.write(payload)
        except OSError:
            writer.close()
