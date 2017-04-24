"""Grail is an async/await-native web framework.

Grail is based on curio, hyper-h2, h11 and other modern
libraries and techniques.
"""

import collections
import functools
import json
import re
import urllib.parse

from curio.kernel import run
from curio.local import Local
from curio.network import tcp_server
from curio.socket import *

import h11
from http11 import Http11Connection
from reasons import REASONS

_ctx = Local()
request = Local()
log = Local()

def methodsingledispatch(func):
    dispatcher = functools.singledispatch(func)
    def wrapper(*args, **kwds):
        return dispatcher.dispatch(args[1].__class__)(*args, **kwds)
    wrapper.register = dispatcher.register
    functools.update_wrapper(wrapper, func)
    return wrapper

class Grail:
    def __init__(self, import_name):
        self.import_name = import_name
        self.rules = []

    def route(self, query, **kwds):
        def adder(f):
            self.add_url_rule(query, f.__name__, f, **kwds)
        return adder

    def add_url_rule(self, target, name, handler, *, methods=['GET']):
        self.rules.append(Route(target, name, handler))

    def find_rule(self, query):
        for route in self.rules:
            name, handler, params = route.match(query)
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
        # this lets us access the app from free functions
        _ctx.app = self

        conn = Http11Connection(client, addr)
        server = HttpServer(self, conn)
        await server.run()

Handler = collections.namedtuple('Handler', 'name handler params')

class Params:
    def __init__(self, d):
        self.d = d

    def __getattr__(self, name):
        return self.d[name]

    def get(self, name, *, default=None, type=None):
        item = self.d.get(name, default)
        if type is None:
            return item
        if item is None:
            return type()
        return type(item)

class Route:
    def __init__(self, template, name, handler):
        self.name = name
        self.handler = handler
        self.trailing_slash = template.endswith('/')
        pattern = re.sub(r'\{([a-z]+)\}', '(?P<\\1>[^/]+)', template)
        if self.trailing_slash:
            pattern += '?'
        self.pattern = re.compile(f'^{pattern}$')
        print(f'route {name}: {template} => {self.pattern}')

    def match(self, query):
        m = self.pattern.match(query)
        if m is not None:
            if self.trailing_slash and not query.endswith('/'):
                return (self.name, self.redirector, {})
            else:
                return (self.name, self.handler, m.groupdict())
        return (None, None, None)

    async def redirector(self):
        return redirect(url_for(self.name), code=308)

def url_for(name, **kwds):
    for route in _ctx.app.rules:
        if route.name == name:
            query_params = []
            target = route.pattern.pattern[1:-2] # strip ^...?$
            for k, v in kwds.items():
                target, n = re.subn(f'(?P<{k}>[^)]*)', v, target)
                if n == 0:
                    query_params.append((k, v))
            if query_params:
                target += '?' + '&'.join(f'{k}={v}' for k, v in query_params)
            return target
    raise RoutingError(f'no such route: {name}')

def redirect(url, code=302):
    assert 300 <= code <= 399
    return Response(code, headers={'location': url})

def abort(code, reason=None):
    assert 400 <= code <= 599
    raise ResponseException(Response(code, reason=reason))

class Response:
    def __init__(self, status_code, *, headers=None, data=None, reason=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.reason = reason or REASONS[status_code]
        self.data = data
        if self.data is None and 'content-length' not in headers:
            self.headers['content-length'] = b'0'

class HttpServer:
    def __init__(self, app, conn):
        self.app = app
        self.conn = conn
        self.data = []

    async def send_response(self, res):
        headers = collections.ChainMap({}, res.headers)
        headers['connection'] = 'close'
        await self.conn.send(h11.Response(
            status_code=res.status_code,
            headers=list(headers.items()),
            reason=res.reason))

    async def send_data(self, data):
        await self.conn.send(h11.Data(data=data))

    async def dispatch(self, query):
        try:
            name, handler, request.params = self.app.find_rule(query)
        except RoutingError as exc:
            await self.send_response(Response(404))
        else:
            print(f'handling {query} using {name}')
            await self.run_handler(handler)
        await self.conn.send(h11.EndOfMessage())
        await self.conn.send(h11.ConnectionClosed())

    async def run_handler(self, handler):
        try:
            res = await handler()
        except ArgumentError as exc:
            await self.send_response(Response(400))
        except ResponseException as exc:
            await self.send_response(exc.res)
        else:
            await self.handle_response(res)

    @methodsingledispatch
    async def handle_response(self, res):
        raise NotImplementedError(f'response: {res!r}, type: {type(res)}')

    @handle_response.register(Response)
    async def handle_response_Response(self, res):
        await self.send_response(res)
        if res.data is not None:
            await self.send_data(res.data.encode('utf-8'))

    @handle_response.register(bytes)
    async def handle_response_bytes(self, res):
        await self.send_response(Response(200,
            headers={'content-length': len(res)}))
        await self.send_data(res)

    @handle_response.register(str)
    async def handle_response_str(self, res):
        data = res.encode('utf-8')
        await self.send_response(Response(200,
            headers={'content-length': str(len(data)).encode('utf-8')}))
        await self.send_data(data)

    async def run(self):
        e = await self.conn.next_event()
        while not isinstance(e, h11.ConnectionClosed):
            await self.handle_event(e)
            e = await self.conn.next_event()

    @methodsingledispatch
    async def handle_event(self, ev):
        raise NotImplementedError(type(ev))

    @handle_event.register(h11.Request)
    async def handle_event_Request(self, ev):
        self.method = ev.method
        self.headers = dict(ev.headers)
        self.target = ev.target

    @handle_event.register(h11.Data)
    async def handle_event_Data(self, ev):
        self.data.append(ev.data)

    @handle_event.register(h11.EndOfMessage)
    async def handle_event_EndOfMessage(self, ev):
        request.method = self.method
        request.headers = self.headers
        data = b''.join(self.data)
        if 'content-type' in self.headers:
            content_type = self.headers['content-type']
            if content_type == 'application/json':
                self.form = Params(json.loads(data))
            elif content_type == 'application/x-www-form-urlencoded':
                self.form = Params(urllib.parse.parse_qs(data))
            else:
                raise ArgumentError('Unsupported form data Content-type: {content_type}')
        await self.dispatch(self.target.decode('ascii'))

class GrailError(Exception): pass
class RoutingError(GrailError): pass
class ProtocolError(GrailError): pass
class ArgumentError(GrailError, AttributeError): pass
class ResponseException(BaseException):
    def __init__(self, res):
        self.res = res
