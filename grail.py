"""Grail is an async/await-native web framework.

Grail is based on curio, hyper-h2, h11 and other modern
libraries and techniques.
"""

from collections import namedtuple, OrderedDict
from functools import partial
import re

from curio.kernel import run
from curio.local import Local
from curio.meta import AsyncObject
from curio.network import tcp_server
from curio.socket import *
import curio.ssl as ssl
from curio.task import spawn

import h11
from http11 import Http11Connection

request = Local()

class Grail:
    def __init__(self, import_name):
        self.import_name = import_name
        self.rules = []

    def route(self, query, **kwds):
        def adder(f):
            self.add_url_rule(query, f.__name__, f, **kwds)
        return adder

    def add_url_rule(self, target, name, handler, *, methods=['GET']):
        route = Route(target)
        self.rules.append((route, name, handler))

    def find_rule(self, query):
        for (route, name, handler) in self.rules:
            params = route.match(query)
            if params is not None:
                return Handler(name, handler, Params(params))
        raise RoutingError(f'No such route: {query}')

    def run_forever(self):
        try:
            run(tcp_server('', 8080, self.handle_client))
        except Exception as exc:
            print('EXCEPTION!!')
            print(exc)
        except KeyboardInterrupt as exc:
            # Clear the "^C" and extra line
            print('\r  \033[F')

    async def handle_client(self, client, addr):
        conn = Http11Connection(client, addr)
        server = HttpServer(self, conn)
        await server.run()

Handler = namedtuple('Handler', 'name handler params')

class Params:
    def __init__(self, d):
        self.d = d

    def __getattr__(self, name):
        return self.d[name]

    def get(self, name, *, default=None, type=type(None)):
        item = self.d.get(name, default)
        if item is None:
            return type()
        else:
            return type(item)

class Route:
    def __init__(self, template):
        pattern = re.sub(r'\{([a-z]+)\}', '(?P<\\1>[^/]+)', template)
        self.pattern = re.compile('^' + pattern + '/?$')
        print(f'Route: {template} => {self.pattern}')

    def match(self, query):
        m = self.pattern.match(query)
        if m is not None:
            return m.groupdict()

class HttpServer:
    def __init__(self, app, conn):
        self.app = app
        self.conn = conn

    async def dispatch(self, query):
        try:
            name, handler, request.params = self.app.find_rule(query)
        except RoutingError as exc:
            await self.conn.send(h11.Response(
                status_code=404,
                headers=[('connection', 'close')],
                reason=b'Not Found'))
        else:
            print(f'handling {query} using {name}')
            try:
                res = await handler()
            except ArgumentError as exc:
                await self.conn.send(h11.Response(
                    status_code=400,
                    headers=[('connection', 'close')],
                    reason=b'Bad Request'))
            else:
                await self.conn.send(h11.Response(
                    status_code=200,
                    headers=[('connection', 'close')],
                    reason=b'OK'))
                await self.conn.send(h11.Data(data=res.encode('utf-8')))
        await self.conn.send(h11.EndOfMessage())
        await self.conn.send(h11.ConnectionClosed())

    async def run(self):
        e = await self.conn.next_event()
        while not isinstance(e, h11.ConnectionClosed):
            await self.handle_event(e)
            e = await self.conn.next_event()

    async def handle_event(self, ev):
        handle = 'handle_' + type(ev).__name__
        try:
            handler = getattr(self, handle)
        except AttributeError as exc:
            raise NotImplementedError(repr(ev)) from exc
        await handler(ev)

    async def handle_Request(self, ev):
        request.method = ev.method
        request.headers = dict(ev.headers)
        request.form = {}
        request.args = {}
        await self.dispatch(ev.target.decode('ascii'))

    async def handle_Data(self, ev):
        raise NotImplementedError

    async def handle_EndOfMessage(self, ev):
        pass

class GrailError(Exception): pass
class RoutingError(GrailError): pass
class ProtocolError(GrailError): pass
class ArgumentError(GrailError, AttributeError): pass
