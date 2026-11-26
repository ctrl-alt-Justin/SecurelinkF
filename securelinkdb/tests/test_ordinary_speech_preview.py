import asyncio
from collections import deque
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

server_dir = str(Path(__file__).resolve().parents[1])
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

import server
from ordinary_speech_preview import OrdinarySpeechPreview, PREVIEW_PORT, SUBSCRIBE


class TestOrdinarySpeechPreview(unittest.IsolatedAsyncioTestCase):
    phrase = "This is an ordinary preview fixture."
    pcm = b"\0\0" * 4800

    async def asyncSetUp(self):
        self.preview = OrdinarySpeechPreview()
        await self.preview.start(port=0)
        self.addAsyncCleanup(self.preview.stop)
        self.assertIsNotNone(self.preview.server, "Unable to bind the loopback test listener")
        endpoint = self.preview.server.sockets[0].getsockname()
        self.assertEqual(endpoint[0], "127.0.0.1")
        self.port = endpoint[1]

    def pipeline(self, score, category):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(server, "ordinary_speech_preview", self.preview))
        stack.enter_context(patch.object(server, "usb_audio_diagnostics", Mock(enabled=False)))
        stack.enter_context(patch.object(server, "registered_devices", {}))
        stack.enter_context(patch.object(server, "active_pins", {}))
        self.incidents = stack.enter_context(patch.object(server, "recent_incidents", deque()))
        self.save = stack.enter_context(patch.object(server, "save_wav"))
        self.broadcast = stack.enter_context(patch.object(server, "broadcast_to_ui", new_callable=AsyncMock))
        stack.enter_context(patch.object(server.context_engine, "evaluate", return_value=(score, category)))
        stack.enter_context(patch.object(
            server, "process_audio_buffer", return_value=(
                server.TranscriptionResult(server.TranscriptionStatus.TRANSCRIBED, self.phrase), self.pcm,
            )
        ))
        stack.enter_context(patch.object(server, "get_primary_ip", return_value="127.0.0.1"))
        stack.enter_context(patch.object(server, "get_active_tunnel_url", return_value=None))

    async def connect(self, handshake):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.addAsyncCleanup(writer.wait_closed)
        self.addCleanup(writer.close)
        writer.write(handshake)
        await writer.drain()
        return reader, writer

    async def test_same_benign_clip_is_private_off_and_on(self):
        self.pipeline(1.5, "Conversational")
        log = io.StringIO()
        with redirect_stdout(log):
            await server.handle_completed_audio("preview-test", self.pcm)
            reader, _ = await self.connect(SUBSCRIBE)
            self.assertEqual(json.loads(await asyncio.wait_for(reader.readline(), 1)), {"ready": True})
            # Opting in does not replay the utterance processed while off.
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(reader.readline(), 0.05)
            await server.handle_completed_audio("preview-test", self.pcm)
            self.assertEqual(json.loads(await asyncio.wait_for(reader.readline(), 1)), {
                "transcript": self.phrase, "category": "Conversational", "score": 1.5,
            })
        self.assertNotIn(self.phrase, log.getvalue())
        self.assertEqual(list(self.incidents), [])
        self.save.assert_not_called()
        self.broadcast.assert_not_called()

    async def test_tunnel_origin_has_no_preview_route_and_http_cannot_subscribe(self):
        self.assertEqual(server.tunnel_mgr.port, 8080)
        self.assertNotEqual(server.tunnel_mgr.port, PREVIEW_PORT)
        origin = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=origin, base_url="http://127.0.0.1:8080") as client:
            response = await client.get("/ordinary-speech-preview", headers={
                "Host": "test.trycloudflare.com",
                "Upgrade": "websocket",
            })
        self.assertEqual(response.status_code, 404)
        reader, _ = await self.connect(b"GET / HTTP/1.1\r\n")
        self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
        self.assertIsNone(self.preview._subscriber)

    async def test_flagged_incident_and_alarm_path_is_unchanged(self):
        self.pipeline(8.5, "Direct Threat")
        reader, _ = await self.connect(SUBSCRIBE)
        await asyncio.wait_for(reader.readline(), 1)
        pin = AsyncMock()
        with redirect_stdout(io.StringIO()):
            await server.handle_completed_audio("preview-test", self.pcm, websocket=pin)
        pin.send_text.assert_awaited_once_with("TRIGGER:DANGER")
        self.save.assert_called_once()
        self.assertEqual(len(self.incidents), 1)
        self.assertEqual(self.incidents[0]["score"], 8.5)
        self.assertTrue(self.incidents[0]["video"])
        self.broadcast.assert_any_await(self.incidents[0])
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(reader.readline(), 0.05)

    async def test_disconnect_and_second_client_do_not_leak_the_preview(self):
        active, writer = await self.connect(SUBSCRIBE)
        await asyncio.wait_for(active.readline(), 1)
        second, _ = await self.connect(SUBSCRIBE)
        self.assertEqual(await asyncio.wait_for(second.read(), 1), b"")
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(active.read(), 1)
        self.preview.publish(self.phrase, "Conversational", 0)
        new, _ = await self.connect(SUBSCRIBE)
        self.assertEqual(json.loads(await asyncio.wait_for(new.readline(), 1)), {"ready": True})
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(new.readline(), 0.05)
