import asyncio
import errno
import io
import json
import os
import random
import ssl
import time
import wifi
from adafruit_datetime import datetime
from collections import namedtuple
from socketpool import SocketPool

import babyxml


DEBUG = os.getenv('DEBUG_AHTTP') in {'1', '2'}
DEBUG2 = os.getenv('DEBUG_AHTTP') == '2'
DEFAULT_TIMEOUT = 60

pool = SocketPool(wifi.radio)
ssl_context = ssl.create_default_context()


async def _sock():
    s = None
    while s is None:
        try:
            s = pool.socket(SocketPool.AF_INET, SocketPool.SOCK_STREAM, SocketPool.IPPROTO_TCP)
        except RuntimeError:
            await asyncio.sleep_ms(100)
    s.setsockopt(SocketPool.SOL_SOCKET, SocketPool.SO_REUSEADDR, 1)
    # CircuitPython >= 9.1.0: setting a TCP socket to non-blocking
    # before connecting does not work right
    # it will immediately fail with either EAGAIN or ETIMEDOUT and never actually seems to succeed
    # instead, set a timeout when connecting and switch to non-blocking after the connection is established
    s.settimeout(3)
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
TEXT_MIMES = {
    'application/json',
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
    def from_response(cls, request, status, headers, body):
        httpver, status_code, reason = status.split(' ', 2)
        content_mime, *params = headers.get('content-type', 'application/octet-stream').split(';')
        charset = None
        if content_mime.startswith('text/') or content_mime in TEXT_MIMES:
            charset = 'latin-1'
        for param in params:
            name, val = param.split('=')
            if name == 'charset':
                charset = val
        if charset:
            body = body.decode(charset)
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


def dns_lookup(url_parsed):
    # TODO: async DNS
    hostname = url_parsed.netloc
    port = SCHEME_DEFAULT_PORTS.get(url_parsed.scheme)
    if ':' in hostname:
        hostname, port = hostname.split(':')
        port = int(port)

    *_, (host, port) = pool.getaddrinfo(hostname, port)[0]
    return host, port


reqs_in_flight = set()

async def request(verb, url, headers, body=None):
    if DEBUG:
        tag = f'{random.randint(0x1000, 0xffff):04x}'
        reqs_in_flight.add(tag)

    # parse URL
    url_parsed = urlparse(url)
    # DNS lookup
    host, port = dns_lookup(url_parsed)
    
    # basic/auto headers
    headers['Connection'] = 'close'
    headers['Host'] = url_parsed.netloc.lower()
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
    sock = await _sock()
    if url_parsed.scheme == 'https':
        sock = ssl_context.wrap_socket(sock)
    await asyncio.sleep(0)

    if DEBUG2:
        print(f'[{datetime.now()}]{tag}_{host}:{port} Connecting...')
        st = time.monotonic()
    while True:
        try:
            sock.connect((host, port))
        except OSError as e:
            # print(f'[{datetime.now()}]{tag}_{host}:{port} {e}')
            if e.errno in {errno.ECONNABORTED, errno.ECONNRESET, errno.ENOTCONN, errno.EBADF}:
                # ECONNABORTED - connection attempt aborted
                # ECONNRESET - connection reset
                # ENOTCONN - connection closed
                # EBADF - bad file descriptor (use after close)
                if DEBUG:
                    print(f'[{datetime.now()}]{tag}_{host}:{port} connection error {e}; retry ({len(reqs_in_flight) - 1} other connections live)')
                await asyncio.sleep(0)
                sock.close()
                sock = await _sock()
                continue
            elif e.errno in {errno.EINPROGRESS, errno.EALREADY, errno.ETIMEDOUT, errno.EAGAIN}:
                if DEBUG:
                    print(f'[{datetime.now()}]{tag}_{host}:{port} connection error {e}; sleep 250ms ({len(reqs_in_flight) - 1} other connections live)')
                # EINPROGRESS - connection is currently in progress
                # EALREADY - already connecting
                # ETIMEDOUT - operation timed out
                # EAGAIN - try again
                await asyncio.sleep_ms(250)
                continue
            elif e.errno == 127:
                # EISCONN - already connected
                pass
            else:
                # all other OSErrors
                continue

        # sock.connect call succeeded or subsequent call returned EISCONN
        # now that we're connected, set non-blocking`
        sock.setblocking(False)
        # try sending the request. if that fails with BrokenPipeError,
        # we aren't connected. start over
        try:
            # send request
            if DEBUG2:
                print(f'[{datetime.now()}]{tag}_{host}:{port} try send after EISCONN ({time.monotonic() - st}s)')
            sock.send(request_raw)
        except (BrokenPipeError, OSError) as e:
            # jk - not connected! try again
            if DEBUG:
                print(f'[{datetime.now()}]{tag}_{host}:{port} connection error {type(e)}({e}); retry')
            await asyncio.sleep(0)
            sock.close()
            sock = await _sock()
        else:
            if DEBUG2:
                print(f'[{datetime.now()}]{tag}_{host}:{port} send success ({time.monotonic() - st}s)')
            await asyncio.sleep(0)
            # post-send await point for concurrency
            break

    # await the response
    # read status line and headers
    # this often also starts to read the body
    status, headers, body_buf = await _read_headers(sock)
    # read the rest of the body
    body_buf = await _read_body(sock, body_buf, headers)

    if DEBUG:
        reqs_in_flight.remove(tag)

    return Response.from_response(request_info, status, headers, body_buf)


async def _aread(read_buf, buf, sock):
    while True:
        try:
            read_nbytes = sock.recv_into(read_buf, len(read_buf))
        except OSError as e:
            if e.errno == 128:
                # ENOTCONN - other side closed the connection
                sock.close()
            elif e.errno != 11:
                # not EAGAIN
                print(READ, repr(e), errno.errorcode.get(e.errno))
            await asyncio.sleep_ms(100)
        else:
            buf += read_buf[:read_nbytes]
            read_buf[:read_nbytes] = b'\x00' * read_nbytes
            return read_nbytes


async def _read_headers(sock):
    read_buf = bytearray(64)
    headers_buf = bytearray()

    # try to read all headers
    while b'\r\n\r\n' not in headers_buf:
        await _aread(read_buf, headers_buf, sock)
        # concurrency point
        await asyncio.sleep(0)

    header, body = headers_buf.split(b'\r\n\r\n', 1)
    # parse status and header lines
    status, *header_lines = header.decode('latin-1').split('\r\n')
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

    return status, headers, body


async def _read_body(sock, body_buf, headers):
    # read body
    if 'chunked' in headers.get('transfer-encoding', ''):
        # raise NotImplementedError('transfer-encoding: chunked')
        # reset body_buf and sync up with whatever we've read so far
        already_read, body_buf = body_buf, bytearray()
        while True:
            # try to read the next chunk size
            while b'\r\n' not in already_read:
                next_read_buf = bytearray(16)
                await _aread(next_read_buf, already_read, sock)
                await asyncio.sleep(0)

            # pop chunk length off already_read and parse it
            chunk_len_raw, already_read = already_read.split(b'\r\n', 1)
            chunk_len = int(chunk_len_raw.decode('latin-1'), 16)
            if chunk_len == 0:
                break

            # if the next chunk is partial, read it
            while len(already_read) < chunk_len + 2:
                rest_buf = bytearray(chunk_len + 2 - len(already_read))
                await _aread(rest_buf, already_read, sock)
                await asyncio.sleep(0)

            # pop data chunk off already_read and onto body_buf
            # make sure to consume the CRLF trailer too
            body_buf += already_read[:chunk_len]
            already_read = already_read[chunk_len + 2:]

    else:
        # if content-encoding is not chunked then we can use content-length
        # to figure out when we're done reading
        content_length = int(headers['content-length'])
        read_buf = bytearray(1024)
        while len(body_buf) < content_length:
            await _aread(read_buf, body_buf, sock)
            # concurrency point
            await asyncio.sleep(0)

    # done reading body; close the socket
    sock.close()

    return body_buf


async def get(url, headers, body=None, timeout=DEFAULT_TIMEOUT):
    return await asyncio.wait_for(request('GET', url, headers, body=body), timeout)


async def post(url, headers, body=None, timeout=DEFAULT_TIMEOUT):
    return await asyncio.wait_for(request('POST', url, headers, body=body), timeout)
