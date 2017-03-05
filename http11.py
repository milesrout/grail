# HTTP/1.1-related code for Grail
# This code uses h11 to parse HTTP/1.1.

from meta import HttpConnection

from curio import aopen

import h11

class Http11Connection(HttpConnection):
    """This class represents an HTTP/1.1 connection over curio.

    Http11Connection presents a high-level interface that abstracts away all
    the nasty details of HTTP/1.1.
    """
    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.driver = h11.Connection(our_role=h11.SERVER)

    async def next_event(self):
        while True:
            event = self.driver.next_event()
            if event is h11.NEED_DATA:
                if self.driver.they_are_waiting_for_100_continue:
                    await self.conn.sendall(h11.InformationalResponse(100, ...))
                self.driver.receive_data(await self.conn.recv(1024))
                continue
            return event

    async def send(self, event):
        buf = self.driver.send(event)
        if buf is not None:
            await self.conn.send(buf)
