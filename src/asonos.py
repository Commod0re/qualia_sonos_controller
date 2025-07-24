import asyncio
import biplane
import wifi
from socketpool import SocketPool

import ahttp
import babyxml


server = biplane.Server()
serve_task = None
sonos_client_registry = {}
sonos_sid_registry = {}
sonos_client_sid_registry = {}


def htmldecode(text):
    return (text
        .replace('&nbsp;', ' ')
        .replace('&lt;', '<')
        .replace('&gt;', '>')
        .replace('&quot;', '"')
        .replace('&apos;', "'")
        .replace('&amp;', '&'))


@server.route('/', 'GET')
def root(params, headers, body):
    # return biplane.Response('\n'.join(f'{k}: {v}' for k, v in sonos_client_registry.items()))
    return biplane.Response(b'OK')


# def event_callback_handler(params, headers, body):
#     return biplane.Response(b'')
@server.route('/', 'NOTIFY')
def handle_notify(params, headers, body):
    sid = headers['sid']
    service = headers['x-sonos-servicetype']
    client = sonos_client_sid_registry[sid, service]

    print(f'handling {service} event from {client}')
    # print(params)
    # print(headers)
    body = babyxml.xmltodict(body.decode('utf-8'))
    # print(body)
    last_change_raw = body['e:propertyset', 0]['e:property', 0]['LastChange', 0]
    # print(last_change_raw)
    # print(htmldecode(last_change_raw))
    print(babyxml.xmltodict(htmldecode(last_change_raw)))
    return biplane.Response(b'OK')


async def run_server():
    with ahttp.pool.socket() as server_socket:
        server_socket.setsockopt(SocketPool.SOL_SOCKET, SocketPool.SO_REUSEADDR, 1)
        for _ in server.start(server_socket, ('0.0.0.0', 8000)):
            await asyncio.sleep(0)


class Sonos:
    @property
    def ip(self):
        return self._ip

    @property
    def base(self):
        return self._base

    @property
    def household_id(self):
        return self._household_id

    @property
    def device_info(self):
        return self._device_info

    @property
    def zone_attributes(self):
        return self._zone_attrs

    @property
    def room_name(self):
        return self.device_info['device', 0]['roomName', 0]

    def __init__(self, ip, **kwargs):
        self._ip = ip
        self._port = kwargs.get('port', 1400)
        # stuff we might have up front
        # if we got here from UPnP or cache
        self._base = kwargs.get('base') or f'http://{ip}:{self._port}'
        self._device_info = kwargs.get('device_info')
        self._zone_attrs = {}
        self._household_id = kwargs.get('household_id')
        self._service_urls = kwargs.get('service_urls', {})
        self._service_schemas = kwargs.get('service_schemas', {})
        self._service_event_urls = kwargs.get('service_event_urls', {})

    def __del__(self):
        if sonos_client_registry.get(self.ip) is self:
            del sonos_client_registry[self.ip]

    async def connect(self):
        # load device info if needed
        # this must come before anything that calls self._upnp_control
        if not self.device_info:
            self._device_info = await self.get_device_info()

        tasks = []
        # map service urls if needed
        if not self._service_urls:
            tasks.append(self._map_services())

        # get zone attrs if needed
        if not self._zone_attrs:
            tasks.append(self._get_zone_attrs())

        await asyncio.gather(*tasks)

    async def subscribe(self, service):
        # TODO: hook up an Event
        sonos_client_registry[self.ip, service] = self
        url = f'http://{self.ip}:1400{self._service_event_urls[service]}'
        headers = {
            'callback': f'<http://{wifi.radio.ipv4_address}:8000/>',
            'NT': 'upnp:event',
            'Timeout': 'Second-3600',
        }
        resp = await ahttp.request('SUBSCRIBE', url, headers)
        sonos_sid_registry[self.ip, service] = resp.headers['sid']
        sonos_client_sid_registry[resp.headers['sid'], service] = self
        print(f'subscribed to events with sid={resp.headers["sid"]}')

    async def unsubscribe(self, service):
        sid = sonos_sid_registry.pop((self.ip, service))
        del sonos_client_registry[self.ip, service]
        del sonos_client_sid_registry[sid, service]
        headers = {
            'SID': sid,
        }
        url = f'http://{self.ip}:1400{self._service_event_urls[service]}'
        resp = await ahttp.request('UNSUBSCRIBE', url, headers)
        print(resp.headers)
        print(resp.body)

    async def get_device_info(self):
        url = f'http://{self.ip}:1400/xml/device_description.xml'
        resp = await ahttp.get(url, {}, None)
        return resp.xml()['root', 0]

    async def _map_services(self):
        def map_service(service):
            name = service['serviceType', 0].split(':service:')[1].split(':')[0]
            self._service_urls[name] = service['controlURL', 0]
            self._service_schemas[name] = service['serviceType', 0]
            self._service_event_urls[name] = service['eventSubURL', 0]

        def service_list(device):
            for (k, idx), service in device['serviceList', 0].items():
                if k == 'service':
                    yield service

        def device_list(device):
            for (k, idx), device in device['deviceList', 0].items():
                if k == 'device':
                    yield device

        root_device = self.device_info['device', 0]
        for service in service_list(root_device):
            map_service(service)
        for device in device_list(root_device):
            for service in service_list(device):
                map_service(service)

    async def _get_zone_attrs(self):
        attrs = await self.get_zone_group_attributes()
        # guaranteed to exist
        if not self._household_id:
            self._household_id = attrs['CurrentMuseHouseholdId', 0]
        self._zone_attrs.update(attrs)

    async def _upnp_control(self, service, action, **arguments):
        soap_headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            "SOAPACTION": f'{self._service_schemas[service]}#{action}',
        }
        wrapped_arguments = babyxml.dicttoxml(arguments)
        soap_body = ''.join([
            '<?xml version="1.0"?>',
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"',
            ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">',
            '<s:Body>',
           f'<u:{action} xmlns:u="{self._service_schemas[service]}">',
           f'{wrapped_arguments}',
           f'</u:{action}>',
            '</s:Body>',
            '</s:Envelope>'
        ])
        resp = await ahttp.post(
            f'http://{self.ip}:1400{self._service_urls[service]}',
            headers=soap_headers,
            body=soap_body
        )
        envelope_body = resp.xml()['s:Envelope', 0]['s:Body', 0]
        if envelope_response := envelope_body.get((f'u:{action}Response', 0)):
            return envelope_response
        return envelope_body

    async def get_zone_group_attributes(self):
        res = await self._upnp_control('ZoneGroupTopology', 'GetZoneGroupAttributes')
        if res:
            return res
        return None

    async def state(self):
        res = await self._upnp_control('AVTransport', 'GetTransportInfo', InstanceID=0)
        if res:
            return res['CurrentTransportState', 0]

    async def volume(self, new_vol=None):
        if new_vol is None:
            res = await self._upnp_control('RenderingControl', 'GetVolume', Channel='Master', InstanceID=0)
            if res:
                return int(res['CurrentVolume', 0])
            return None
        else:
            new_vol = max(0, min(int(new_vol), 100))
            await self._upnp_control('RenderingControl', 'SetVolume', Channel='Master', DesiredVolume=new_vol, InstanceID=0)
            return new_vol

    async def play(self):
        await self._upnp_control('AVTransport', 'Play', Speed=1, InstanceID=0)

    async def pause(self):
        await self._upnp_control('AVTransport', 'Pause', Speed=1, InstanceID=0)

    async def next(self):
        await self._upnp_control('AVTransport', 'Next', Speed=1, InstanceID=0)

    async def prev(self):
        await self._upnp_control('AVTransport', 'Previous', Speed=1, InstanceID=0)

    async def current_track_info(self):
        res = await self._upnp_control('AVTransport', 'GetPositionInfo', Channel='Master', InstanceID=0)
        if not res or ('TrackMetaData', 0) not in res:
            return None
        trackmetaxml = htmldecode(res['TrackMetaData', 0])
        if trackmetaxml == 'NOT_IMPLEMENTED':
            return None
        trackmeta = babyxml.xmltodict(trackmetaxml)['DIDL-Lite', 0]['item', 0]
        album_art_uri = htmldecode(trackmeta.get(('upnp:albumArtURI', 0), ''))
        if album_art_uri and '://' not in album_art_uri:
            album_art_uri = ''.join([self.base, album_art_uri])

        return {
            'title': htmldecode(trackmeta.get(('dc:title', 0), '')),
            'artist': htmldecode(trackmeta.get(('dc:creator', 0), '')),
            'album': htmldecode(trackmeta.get(('upnp:album', 0), '')),
            'album_art': album_art_uri,
            'position': res['RelTime', 0],
            'duration': res['TrackDuration', 0],
            'queue_position': int(res['Track', 0]) - 1,
        }

    async def medium_info(self):
        res = await self._upnp_control('AVTransport', 'GetMediaInfo', InstanceID=0)
        urimetaxml = htmldecode(res.get(('CurrentURIMetaData', 0), ''))
        if urimetaxml:
            urimeta = babyxml.xmltodict(urimetaxml)['DIDL-Lite', 0]['item', 0]
        else:
            urimeta = {}

        return {
            'title': htmldecode(urimeta.get(('dc:title', 0), '')),
            'medium_art': htmldecode(urimeta.get(('upnp:albumArtURI', 0), '')),
            'medium': res.get(('PlayMedium', 0), ''),
        }

    async def queue_slice(self, count=5, offset=0):
        res = await self._upnp_control('Queue', 'Browse', QueueID=0, StartingIndex=offset, RequestedCount=count)
        if not res:
            return None

        resultxml = htmldecode(res['Result', 0])
        result = babyxml.xmltodict(resultxml)['DIDL-Lite', 0]
        item_gen = (
            ((key, idx), item)
            for (key, idx), item in result.items()
            if key == 'item'
        )

        queue = []
        for (key, idx), item in item_gen:
            album_art_uri =  htmldecode(item['upnp:albumArtURI', 0])
            if album_art_uri and '://' not in album_art_uri:
                album_art_uri = ''.join((self.base, album_art_uri))
            queue.append({
                'title': htmldecode(item.get(('dc:title', 0), '')),
                'artist': htmldecode(item.get(('dc:creator', 0), '')),
                'album': htmldecode(item.get(('upnp:album', 0), '')),
                'album_art': album_art_uri,
                'duration': item['res_attrs', 0]['duration'],
                'queue_position': offset + idx,
            })
        return queue




# testing
# loop = asyncio.new_event_loop()
# sonos = Sonos('10.0.3.0')
# loop.run_until_complete(sonos.connect())
# print(sonos._service_event_urls.keys())
# loop.run_until_complete(sonos.subscribe('AVTransport'))
# loop.create_task(run_server())
# loop.run_forever()


# def upnp(service, action, **arguments):
#     return loop.run_until_complete(sonos._upnp_control(service, action, **arguments))


# print(upnp('AVTransport', 'GetPositionInfo', InstanceID=0))
