import asyncio
import collections
import os
import wifi

import asonos
import controls
import display
import ssdp


def fmt_bssid(bssid):
    return ':'.join(f'{b:02x}' for b in bssid)


async def wifi_disconnected():
    while True:
        await asyncio.sleep(1)
        if not wifi.radio.connected:
            return


def task_restart(name):
    def wrapper(func):
        async def wrapped(*args, **kwargs):
            while True:
                try:
                    await func(*args, **kwargs)

                except asyncio.CancelledError:
                    break

                except Exception as e:
                    print(f'[{name}] caught unhandled exception {type(e).__name__}')
                    print(e)

                await asyncio.sleep_ms(10)

        return wrapped
    return wrapper


@task_restart('wifi_roaming')
async def wifi_roaming():
    ssid = os.getenv('CIRCUITPY_WIFI_SSID')
    psk = os.getenv('CIRCUITPY_WIFI_PASSWORD')
    no_network = collections.namedtuple('Network', ['bssid', 'rssi'])(b'\x00\x00\x00\x00', -100)
    while True:
        # roam-scan less frequently than (re)connect-scan
        try:
            await asyncio.wait_for(wifi_disconnected(), timeout=300)
        except asyncio.TimeoutError:
            pass

        if not wifi.radio.connected:
            print('wifi not connected; scanning for APs to connect to')

        cur_network = wifi.radio.ap_info or no_network

        # my kingdom for an asyncio version of this
        network = cur_network
        for net in wifi.radio.start_scanning_networks():
            if net.ssid == ssid and net.rssi > network.rssi:
                network = net
        wifi.radio.stop_scanning_networks()

        await asyncio.sleep(0)

        if network.bssid == cur_network.bssid:
            continue

        # this isn't fast roaming so only roam if it's really worth it
        if cur_network is no_network or (network.rssi - cur_network.rssi) >= 3:
            verb = 'roaming' if wifi.radio.connected else 'connecting'
            print(f'{verb} to {fmt_bssid(network.bssid)} ({network.rssi})')
            wifi.radio.stop_station()
            wifi.radio.connect(ssid, psk, channel=network.channel, bssid=network.bssid)

            if wifi.radio.connected:
                print('wifi connected')


@task_restart('play_pause')
async def play_pause(player, ev):
    while True:
        await ev.wait()
        ev.clear()

        cur_state = await player.state()
        if cur_state in {'STOPPED', 'PAUSED_PLAYBACK'}:
            print('PLAY')
            await player.play()
        else:
            print('PAUSE')
            await player.pause()


@task_restart('prev')
async def prev(player, ev):
    while True:
        await ev.wait()
        ev.clear()
        print('PREV')
        await player.prev()


@task_restart('next')
async def next(player, ev):
    while True:
        await ev.wait()
        ev.clear()
        print('NEXT')
        await player.next()


@task_restart('volume')
async def volume(player, cntrl, ev):
    # get initial position for delta tracking
    pos = cntrl.encoder.position

    while True:
        await ev.wait()
        # set volume
        cur_pos = cntrl.encoder.position
        delta = cur_pos - pos
        cur_vol = None
        while cur_vol is None:
            cur_vol = await player.volume()
            if cur_vol:
                break
            await asyncio.sleep(0.100)

        new_vol = max(0, min(100, cur_vol + delta))
        if cur_vol != new_vol:
            print(f'volume => {new_vol}')
            await player.volume(new_vol)
        pos = cur_pos
        ev.clear()


@task_restart('monitor_current_track')
async def monitor_current_track(player):
    state = None
    track = {}
    pos = None
    while True:
        idle = 1
        if wifi.radio.connected:
            idle = 1
            cur_state = await player.state()
            if cur_state:
                if cur_state != state:
                    print(f'now {cur_state}')
                    state = cur_state

                cur_track = await player.current_track_info()
                if cur_track:
                    cur_pos = cur_track.pop('position')
                    if cur_track != track:
                        print(f"NOW {cur_state} {cur_track['artist']} - {cur_track['album']} - {cur_track['title']}")
                        track = cur_track
                        pos = cur_pos
                else:
                    idle = 10

        await asyncio.sleep(idle)


async def discover_sonos(player_map):
    # player_map:
    #   players:
    #     mac: Sonos()
    #   rooms:
    #     room_name:
    #       players:
    #         mac:
    #           player: Sonos()
    #           model: name
    #           icon: path
    #       primary: Sonos()
    def mac(usn):
        return ':'.join(''.join(d) for d in zip(*[iter(usn[12:24])]*2))

    def icons(device_list):
        device_tags = sum(1 for n in device_list if n[0] == 'device')
        for n in range(device_tags):
            device = device_list['device', n]
            if ('iconList', 0) in device:
                return device['iconList', 0]

    new_batch = []

    if 'players' not in player_map:
        player_map['players'] = {}
    if 'rooms' not in player_map:
        player_map['rooms'] = {}

    # discover players
    async for ssdp_parsed in ssdp.discover():
        if ssdp_parsed.get('household_id', '').startswith('Sonos_'):
            player_id = mac(ssdp_parsed['headers']['USN'])
            verb = 'existing'
            if player_id not in player_map['players']:
                verb = 'found'
                new_batch.append(asonos.Sonos(**ssdp_parsed))
            print(f'{verb} player at {ssdp_parsed["ip"]}')

    # connect to the new batch
    await asyncio.gather(*(player.connect() for player in new_batch))

    # map the new batch
    for player in new_batch:
        room_name = player.room_name
        player_id = player.device_info['device', 0]['MACAddress', 0]
        model_name = player.device_info['device', 0]['deviceList', 0]['device', 0]['modelName', 0]
        icon_list = icons(player.device_info['device', 0]['deviceList', 0])

        print(f'player at {player.ip} ({model_name}) belongs to room {room_name}')

        player_map['players'][player_id] = player

        if room_name not in player_map['rooms']:
            player_map['rooms'][room_name] = {'players': {}, 'primary': None}

        player_map['rooms'][room_name]['players'][player_id] = {
            'player': player,
            'model': model_name,
            'icon': icon_list['icon', 0]['url', 0] if icon_list else '',
        }

        if ('CurrentZoneGroupID', 0) in player.zone_attributes:
            player_map['rooms'][room_name]['primary'] = player


async def main():
    loop = asyncio.get_event_loop()

    print('managing wifi')
    loop.create_task(wifi_roaming())

    print('setting up controls')
    ano = await controls.AnoRotary.new(display.qualia.graphics.i2c_bus)

    print('locating sonoses')
    # TODO: monitor players over time
    # TODO: make this selectable instead of hardcoded
    players = {'players': {}, 'rooms': {}}
    target_room = 'Mike’s Office'
    while not players['rooms'].get(target_room, {}).get('primary'):
        await discover_sonos(players)

    player = players['rooms'][target_room]['primary']

    print('connecting event handlers')
    loop.create_task(monitor_current_track(player))
    loop.create_task(play_pause(player, ano.events['select_press']))
    loop.create_task(prev(player, ano.events['left_press']))
    loop.create_task(next(player, ano.events['right_press']))
    loop.create_task(volume(player, ano, ano.events['encoder']))

    print('ready')

    while True:
        await asyncio.sleep(1)


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
