import asyncio
import errno
import io
import json
import time
import wifi
from collections import namedtuple
from socketpool import SocketPool

import babyxml


DEFAULT_TIMEOUT = 60

pool = SocketPool(wifi.radio)


async def _sock():
    s = None
    while s is None:
        try:
            s = pool.socket(SocketPool.AF_INET, SocketPool.SOCK_STREAM, SocketPool.IPPROTO_TCP)
            s.setsockopt(SocketPool.SOL_SOCKET, SocketPool.SO_REUSEADDR, 1)
        except RuntimeError:
            await asyncio.sleep_ms(100)
    # this works fine on CircuitPython 9.0.x
    # this does not work fine on CircuitPython >= 9.1.0
    s.setblocking(False)
    return s


ParsedUrl = namedtuple('ParsedUrl', ['scheme', 'netloc', 'path'])


def urlparse(url):
    scheme = None
    netloc = None
    path = None
    query = None
    fragment = None
    if '://' in url:
        scheme, _, url = url.partition('://')
    if '/' in url and not url.startswith('/'):
        netloc_end = url.index('/')
        netloc, path = url[:netloc_end], url[netloc_end:]
    else:
        path = url
    path, *_ = path.split('#')
    return ParsedUrl(scheme, netloc, path)


SCHEME_DEFAULT_PORTS = {
    'http': 80,
    'https': 443,
}

Request = namedtuple('Request', ['verb', 'url', 'headers'])



class Response:
    def __init__(self, request, status_code, reason, headers, body):
        self.request = request
        self.status_code = status_code
        self.reason = reason
        self.headers = headers
        self.body = body
        self._json = None
        self._xml = None

    @classmethod
    def from_response(cls, request, response):
        header, body = response.split(b'\r\n\r\n', 1)
        status, *header_lines = header.decode().split('\r\n')

        httpver, status_code, reason = status.split(' ', 2)
        headers = {}
        for header_line in header_lines:
            header_name, header_value = header_line.split(': ')
            header_name = header_name.lower()
            if header_name not in headers:
                headers[header_name] = header_value
            else:
                existing = headers[header_name]
                if isinstance(existing, list):
                    existing.append(header_value)
                else:
                    headers[header_name] = [existing, header_value]

        if 'chunked' in headers.get('transfer-encoding', ''):
            chunks = []
            reader = io.BytesIO(body)
            while reader.tell() < len(body):
                chunk_len = int(reader.readline(), 16)
                chunks.append(reader.read(chunk_len))
                reader.seek(reader.tell() + 2)
            body = b''.join(chunks).decode()
        else:
            body = body.decode()

        return cls(request, int(status_code), reason, headers, body)

    def __repr__(self):
        return f'<Response status_code={self.status_code} {self.reason}>'

    # TODO: awaitable versions of these?
    def json(self):
        if 'json' in self.headers.get('content-type'):
            if not self._json:
                self._json = json.loads(self.body)
            return self._json

    def xml(self):
        if 'xml' in self.headers.get('content-type'):
            if not self._xml:
                self._xml = babyxml.xmltodict(self.body)
            return self._xml


async def request(verb, url, headers, body=None):
    # TODO: DNS -- fortunately I'm only working with IPs for now
    # pool.getaddrinfo blocks so that's no good for this
    # maybe an lru_cache would help....
    # anyway, for another time
    url_parsed = urlparse(url)
    if ':' in url_parsed.netloc:
        host, port = url_parsed.netloc.split(':')
        port = int(port)
    else:
        host = url_parsed.netloc
        port = SCHEME_DEFAULT_PORTS.get(url_parsed.scheme)
    
    # basic/auto headers
    headers['Host'] = url_parsed.netloc.lower()
    headers['Connection'] = 'close'
    if body:
        headers['Content-Length'] = len(body)

    # informational context for the response object
    request_info = Request(verb, url, headers)

    # format the raw request
    request_lines = [
        f'{verb.upper()} {url_parsed.path} HTTP/1.1',
    ]
    request_lines.extend(f'{header_name}: {header_value}' for header_name, header_value in headers.items())
    if body:
        request_lines.append('')
        request_lines.extend(body.splitlines())
    else:
        request_lines.extend(('', ''))
    request_raw = '\r\n'.join(request_lines).encode('utf-8')


    resp = None
    sent_request = False
    sock = await _sock()

    # connect
    while True:
        try:
            sock.connect((host, port))
        except OSError as e:
            if e.errno == 113:
                # ECONNABORTED - connection attempt aborted
                sock.close()
                sock = await _sock()
            elif e.errno == 116:
                # ETIMEDOUT - operation timed out, but, connection might be in progress
                await asyncio.sleep_ms(100)
            elif e.errno == 119:
                # EINPROGRESS - connection is currently in progress
                await asyncio.sleep_ms(100)
            elif e.errno == 120:
                # EALREADY - connection is already pending
                await asyncio.sleep_ms(100)
            elif e.errno == 127:
                # EISCONN - we may be connected
                await asyncio.sleep(0)
                # try sending the request. if that fails with BrokenPipeError,
                # we aren't connected. start over
                try:
                    # send request
                    sock.send(request_raw)
                except BrokenPipeError:
                    # jk - not connected! try again
                    sock.close()
                    sock = await _sock()
                else:
                    sent_request = True
                    break
            elif e.errno == 128:
                # ENOTCONN - not connected; start over
                sock.close()
                sock = await _sock()
            else:
                print(f'[{datetime.now()}]{req_id}_{host}:{port}', repr(e), errno.errorcode.get(e.errno))
        else:
            break

    if not sent_request:
        await asyncio.sleep(0)
        # if we didn't do this already:
        # send request
        sock.send(request_raw)


    # await the response
    read_buf = bytearray(4096)
    response_buf = bytearray()
    while True:
        try:
            read_nbytes, (host, port) = sock.recvfrom_into(read_buf)
            if read_nbytes == 0 and response_buf:
                # possibly finished reading response
                sock.close()
                break
        except OSError as e:
            await asyncio.sleep_ms(100)
        else:
            response_buf += read_buf[:read_nbytes]
            read_buf[:read_nbytes] = b'\x00' * read_nbytes

    return Response.from_response(request_info, response_buf)


async def get(url, headers, body=None, timeout=DEFAULT_TIMEOUT):
    return await asyncio.wait_for(request('GET', url, headers, body=body), timeout)


async def post(url, headers, body=None, timeout=DEFAULT_TIMEOUT):
    return await asyncio.wait_for(request('POST', url, headers, body=body), timeout)
