import asyncio
import collections
import ipaddress
import time
import wifi
from socketpool import SocketPool


pool = SocketPool(wifi.radio)
MCAST_GRP = '239.255.255.250'
MCAST_PORT = 1900
PLAYER_SEARCH = f'''M-SEARCH * HTTP/1.1
HOST: {MCAST_GRP}:{MCAST_PORT}
MAN: "ssdp:discover"
MX: 3
ST: urn:schemas-upnp-org:device:ZonePlayer:1
'''.encode('utf-8')


def _sock():
    s = pool.socket(SocketPool.AF_INET, SocketPool.SOCK_DGRAM, SocketPool.IPPROTO_UDP)
    s.setsockopt(SocketPool.SOL_SOCKET, SocketPool.SO_REUSEADDR, 1)
    s.setsockopt(SocketPool.IPPROTO_IP, SocketPool.IP_MULTICAST_TTL, 2)
    s.setblocking(False)
    return s


def parse_ssdp_response(resp):
    headers = dict(l.split(': ') for l in resp.splitlines() if ': ' in l)
    proto, url = headers['LOCATION'].split('://')
    hostport = url.split('/')[0]
    if ':' in hostport:
        host, port = hostport.split(':')
    else:
        host = hostport
        port = PROTO_PORTS[proto]

    return {
        'ip': host,
        'base': headers['LOCATION'][:headers['LOCATION'].index('/', 8)],
        'household_id': headers.pop('X-RINCON-HOUSEHOLD', None),
        'headers': headers,
    }


class ResponseReader:
    def __init__(self, sock):
        self.sock = sock
        self.last_read = 0
        self._ignore_hosts = set()
        self._buf = bytearray(1024)
        self._clear = b'\x00' * 1024

    def __aiter__(self):
        return self

    def reset_buffer(self):
        self._buf[:] = self._clear

    async def __anext__(self):
        read_nbytes = 0

        while True:
            try:
                read_nbytes, (host, port) = self.sock.recvfrom_into(self._buf)
            except OSError:
                await asyncio.sleep_ms(100)
            else:
                self.last_read = time.time()
                if host not in self._ignore_hosts:
                    resp_raw = self._buf[:read_nbytes].decode()
                    self.reset_buffer()

                    parsed = parse_ssdp_response(resp_raw)
                    if parsed['household_id']:
                        return parsed
                    else:
                        self._ignore_hosts.add(host)
                else:
                    self.reset_buffer()


            if self.last_read > 0 and (time.time() - self.last_read) > 10:
                self.last_read = 0
                self.sock.close()
                raise StopAsyncIteration


class Discoverer:
    def __init__(self):
        self.sock = _sock()
        self._last_send = 0
        self._response_reader = ResponseReader(self.sock)
        self._riter = None

    def __aiter__(self):
        return self


    async def __anext__(self):
        resp = None
        while resp is None:
            if (time.time() - self._last_send) > 300:
                self.sock.sendto(PLAYER_SEARCH, (MCAST_GRP, MCAST_PORT))
                self._last_send = time.time()

            if self._response_reader.last_read == 0 or (time.time() - self._response_reader.last_read) <= 15:
                resp = await self._response_reader.__anext__()
                if resp:
                    return resp

            else:
                until = self._last_send + 300
                remaining = until - time.time()
                print(f'sleeping until {until} ({remaining}s)')
                await asyncio.sleep(remaining)


# async def discover(found):
#     # non-blocking socket
#     sock = _sock()
#     ignore_hosts = set()

#     while True:
#         print('send multicast')
#         # send out a multicast search beacon
#         sock.sendto(PLAYER_SEARCH, (MCAST_GRP, MCAST_PORT))

#         # try to read responses asynchronously
#         async for resp in ResponseReader(sock, ignore_hosts):
#             if resp['ip'] not in found:
#                 found[resp['ip']] = resp

#         # TODO: try again sooner if we didn't catch the player we're hoping to see
#         # TODO: try again much later if we caught all known players
#         # wait 5 minutes before trying again
#         await asyncio.sleep(300)


def discover():
    return Discoverer()