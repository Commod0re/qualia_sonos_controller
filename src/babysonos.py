import adafruit_requests
import asyncio
import struct
import time
import wifi
from socketpool import SocketPool

import babyxml

pool = SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool)
# MCAST_GRP = '239.255.255.250'
# MCAST_PORT = 1900
# PLAYER_SEARCH = f'''M-SEARCH * HTTP/1.1
# HOST: {MCAST_GRP}:{MCAST_PORT}
# MAN: "ssdp:discover"
# MX: 3
# ST: urn:schemas-upnp-org:device:ZonePlayer:1
# '''.encode('utf-8')
PROTO_PORTS = {
    'http': 80,
    'https': 443,
}


# def _sock():
#     s = pool.socket(SocketPool.AF_INET, SocketPool.SOCK_DGRAM, SocketPool.IPPROTO_UDP)
#     s.setsockopt(SocketPool.IPPROTO_IP, SocketPool.IP_MULTICAST_TTL, 2)
#     return s


# def parse_ssdp_response(resp):
#     headers = dict(l.split(': ') for l in resp.splitlines() if ': ' in l)
#     proto, url = headers['LOCATION'].split('://')
#     hostport = url.split('/')[0]
#     if ':' in hostport:
#         host, port = hostport.split(':')
#     else:
#         host = hostport
#         port = PROTO_PORTS[proto]

#     return {
#         'ip': host,
#         'base': headers['LOCATION'][:headers['LOCATION'].index('/', 8)],
#         'household_id': headers.pop('X-RINCON-HOUSEHOLD', None),
#         'headers': headers,
#     }


def parse_description(xmldesc):
    return xmltodict(xmldesc)


# def discover_sync():
#     # send out the multicast search beacon
#     sock = _sock()
#     sock.sendto(PLAYER_SEARCH, (MCAST_GRP, MCAST_PORT))

#     # prepare read buffer
#     buf = bytearray(1024)
#     sock.settimeout(2)
#     # read responses
#     total = 0
#     sonos = 0
#     hosts = {}
#     while True:
#         try:
#             b = sock.recv_into(buf)
#         except OSError:
#             # timed out; done reading responses
#             break

#         resp = str(buf[:b].decode('utf-8'))
#         total += 1
#         if 'Sonos' in resp:
#             sonos += 1
#         parsed = parse_ssdp_response(resp)
#         hosts[parsed['ip']] = parsed

#     players = {}
#     for host, ssdp in sorted(hosts.items()):
#         if ssdp['household_id']:
#             players[host] = Sonos(ssdp)
#     return players



class Sonos:
    @property
    def ip(self):
        return self._ip

    @property
    def base(self):
        return self._base

    @property
    def household_id(self):
        return self.household_id

    @property
    def headers(self):
        return self._headers

    @property
    def device_info(self):
        if not self._device_info:
            self._get_device_info()
        return self._device_info

    @property
    def service_urls(self):
        if not self._service_urls:
            self._map_services()
        return self._service_urls

    @property
    def room_name(self):
        return self.device_info['device', 0]['roomName', 0]

    @property
    def volume(self):
        res = self._upnp_control('RenderingControl', 'GetVolume', Channel='Master')
        if res:
            return int(res['CurrentVolume', 0])

    @property
    def state(self):
        res = self._upnp_control('AVTransport', 'GetTransportInfo')
        if res:
            return res['CurrentTransportState', 0]

    @volume.setter
    def volume(self, volume):
        volume = max(0, min(int(volume), 100))
        self._upnp_control('RenderingControl', 'SetVolume', Channel='Master', DesiredVolume=volume)

    def __init__(self, ssdp_parsed):
        self._ip = ssdp_parsed['ip']
        self._base = ssdp_parsed['base']
        self._household_id = ssdp_parsed['household_id']
        self._headers = ssdp_parsed['headers']
        self._device_info = {}
        self._service_urls = {}

    def _get_device_info(self):
        resp = requests.get(self._headers['LOCATION'])
        xmldesc = resp.content.decode('utf-8')
        self._device_info = babyxml.xmltodict(xmldesc)['root', 0]

    def _map_services(self):
        def map_service(service):
            name = service['serviceType', 0].split(':service:')[1].split(':')[0]
            self._service_urls[name] = service['controlURL', 0]

        def service_list(device):
            for (k, idx), service in device['serviceList', 0].items():
                if k == 'service':
                    yield service

        def device_list(device):
            for (k, idx), device in device['deviceList', 0].items():
                if k == 'device':
                    yield device

        for service in service_list(self.device_info['device', 0]):
            map_service(service)
        for device in device_list(self.device_info['device', 0]):
            for service in service_list(device):
                map_service(service)

    # UPnP control abstraction
    def _upnp_control(self, service, action, service_version=1, **arguments):
        soap_headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            "SOAPACTION": f'urn:schemas-upnp-org:service:{service}:{service_version}#{action}',
        }
        if 'InstanceID' not in arguments:
            arguments['InstanceID'] = 0
        wrapped_arguments = babyxml.dicttoxml(arguments)
        soap_body = ''.join([
             '<?xml version="1.0"?>' 
             '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"',
             ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">',
             '<s:Body>',
            f'<u:{action} xmlns:u="urn:schemas-upnp-org:service:{service}:{service_version}">',
            f'{wrapped_arguments}',
            f'</u:{action}>',
             '</s:Body>',
             '</s:Envelope>',
        ])
        try:
            resp = requests.post(
                f'{self.base}{self.service_urls[service]}',
                headers=soap_headers,
                data=soap_body.encode('utf-8'),
                timeout=1
            )
        except adafruit_requests.OutOfRetries:
            return {}
        else:
            envelope_body = babyxml.xmltodict(resp.content.decode('utf-8'))['s:Envelope', 0]['s:Body', 0]
            if (f'u:{action}Response', 0) in envelope_body:
                return envelope_body[f'u:{action}Response', 0]
            return envelope_body


    # basic operations
    def play(self):
        self._upnp_control('AVTransport', 'Play', Speed=1)

    def pause(self):
        self._upnp_control('AVTransport', 'Pause', Speed=1)

    def next(self):
        self._upnp_control('AVTransport', 'Next', Speed=1)

    def prev(self):
        self._upnp_control('AVTransport', 'Previous', Speed=1)

    def seek(self, position=None, track=None):
        if track is not None:
            self._upnp_control('AVTransport', 'Seek', Unit='TRACK_NR', Target=track + 1)

        if position is not None:
            self._upnp_control('AVTransport', 'Seek', Unit='REL_TIME', Target=position)

    def current_track_info(self):
        res = self._upnp_control('AVTransport', 'GetPositionInfo', Channel='Master')
        if not res:
            return None
        trackmetaxml = res['TrackMetaData', 0].replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&amp;', '&')
        trackmeta = babyxml.xmltodict(trackmetaxml)['DIDL-Lite', 0]

        return {
            'title': trackmeta['item', 0]['dc:title', 0].replace('&apos;', "'").replace('&amp;', '&'),
            'artist': trackmeta['item', 0]['dc:creator', 0],
            'album': trackmeta['item', 0]['upnp:album', 0],
            'album_art': ''.join([self.base, trackmeta['item', 0]['upnp:albumArtURI', 0].replace('&amp;', '&')]),
            'position': res['RelTime', 0],
            'duration': res['TrackDuration', 0],
        }
