import asyncio
import websockets
import cv2
import base64
import threading
import queue

import asyncio
import cv2
import base64
import websockets

class StreamServer:
    def __init__(self, frame_buffer):
        self.frame_buffer = frame_buffer  # better if asyncio.Queue
        self.clients = set()
        self.lock = asyncio.Lock()  # to avoid race on clients set

    async def register(self, websocket):
        async with self.lock:
            self.clients.add(websocket)
            print(f"Client connected: {len(self.clients)} total.")

    async def unregister(self, websocket):
        async with self.lock:
            self.clients.remove(websocket)
            print(f"Client disconnected: {len(self.clients)} remaining.")

    async def broadcast_frames(self):
        while True:
            try:
                # Get next frame (use await if asyncio.Queue)
                frame = self.frame_buffer.get(block=True, timeout=1)
                ret, jpeg = cv2.imencode('.jpg', frame)
                if not ret:
                    continue
                frame_b64 = base64.b64encode(jpeg.tobytes()).decode('utf-8')
            
                async with self.lock:
                    if not self.clients:
                        await asyncio.sleep(0.1)
                        continue
                    await asyncio.gather(*[client.send(frame_b64) for client in self.clients])

            except Exception as e:
                print(f"Broadcast error: {e}")
                await asyncio.sleep(0.1)

    async def handler(self, websocket):
        await self.register(websocket)
        try:
            while True:
                await asyncio.sleep(10)
        except websockets.ConnectionClosed:
            pass
        finally:
            await self.unregister(websocket)

    async def main(self):
        # Start server and broadcast task
        async with websockets.serve(self.handler, "0.0.0.0", 8765):
            broadcaster = asyncio.create_task(self.broadcast_frames())
            await asyncio.Future()  # run forever
            broadcaster.cancel()

    def run(self):
        asyncio.run(self.main())
