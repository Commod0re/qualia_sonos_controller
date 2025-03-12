import asyncio
import collections
import os
import time
import wifi
from adafruit_datetime import datetime

import asonos
import controls
import ntp
import ssdp
import ui


def fmt_bssid(bssid):
    return ':'.join(f'{b:02x}' for b in bssid)


async def ip_changed(last_ip):
    while True:
        cur_ip = str(wifi.radio.ipv4_address) if wifi.radio.connected else 'disconnected'
        if last_ip != cur_ip:
            return cur_ip
        await asyncio.sleep(1)


async def wifi_disconnected():
    while True:
        if not wifi.radio.connected:
            return
        await asyncio.sleep(1)


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


@task_restart('volume')
async def volume(player, cntrl, ev):
    # get initial position for delta tracking
    pos = cntrl.encoder.position
    vol = ui.volume.volume = await player.volume()

    while True:
        await ev.wait()
        # get new encoder position and calculate delta from last time
        new_pos = cntrl.encoder.position
        delta = new_pos - pos

        # if position changed, update the UI and speaker
        if delta:
            new_vol = max(0, min(100, vol + delta))
            vol = ui.volume.volume = new_vol
            await player.volume(new_vol)
            pos = new_pos
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
    connect_tasks = {}

    def mac(usn):
        return ':'.join(''.join(d) for d in zip(*[iter(usn[12:24])]*2))

    def icons(device_list):
        device_tags = sum(1 for n in device_list if n[0] == 'device')
        for n in range(device_tags):
            device = device_list['device', n]
            if ('iconList', 0) in device:
                return device['iconList', 0]

    async def _connect(player):
        while True:
            try:
                await player.connect()
            except asyncio.TimeoutError:
                print(f'TimeoutError connecting to {player.ip}')
            else:
                break
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

        # we are done
        connect_tasks.pop(player_id)

    # discover players
    discoverer = await ssdp.discover()
    async for ssdp_parsed in discoverer:
        if ssdp_parsed.get('household_id', '').startswith('Sonos_'):
            player_id = mac(ssdp_parsed['headers']['USN'])
            verb = 'existing'
            if player_id not in player_map['players'] and player_id not in connect_tasks:
                verb = 'found'
                connect_tasks[player_id] = asyncio.create_task(_connect(asonos.Sonos(**ssdp_parsed)))
            print(f'{verb} player at {ssdp_parsed["ip"]}')
    discoverer.close()

    while connect_tasks:
        await asyncio.sleep(1)


async def main():
    loop = asyncio.get_event_loop()

    # print('managing wifi')
    # loop.create_task(wifi_roaming())

    print('syncing NTP')
    loop.create_task(ntp.ntp())

    print('setting up controls')
    ano = await controls.AnoRotary.new(ui.i2c)
    qbtns = await controls.QualiaButtons.new(ui.i2c)
    player = None

    async def _refresh():
        while True:
            await asyncio.sleep_ms(1000 // 60)
            ui.refresh()

    async def _status_ip():
        ip = None
        while True:
            try:
                new_ip = await asyncio.wait_for(ip_changed(ip), timeout=300)
            except asyncio.TimeoutError:
                # timed out; ip never changed
                continue
            # update display
            ui.status_bar.ip = new_ip

    async def _track_info():
        # TODO: replace polling with events
        track = {}
        while True:
            loop_start = time.monotonic()
            if wifi.radio.connected and player:
                try:
                    cur_track = await player.current_track_info()
                except asyncio.TimeoutError:
                    print(f'[{datetime.now()}] TIMEOUT - retry')
                    continue
                if cur_track and cur_track != track:
                    # update artist, album, title
                    if cur_track.get('artist') != track.get('artist'):
                        ui.track_info.artist_name = cur_track.get('artist') or 'No Artist'
                    if cur_track.get('album') != track.get('album'):
                        ui.track_info.album_name = cur_track.get('album') or ''
                    if cur_track.get('title') != track.get('title'):
                        new_title = cur_track.get('title') or 'No Title'
                        if new_title.startswith(cur_track.get('artist')):
                            new_title = new_title.split(' - ')[-1]
                        ui.track_info.track_name = new_title
                    # update duration
                    if cur_track.get('duration') != track.get('duration'):
                        ui.play_progress.track_duration = cur_track.get('duration')
                    # update position
                    if cur_track.get('position') is not None:
                        ui.play_progress.play_position = cur_track.get('position')
                    track = cur_track

            await asyncio.sleep(1 - (time.monotonic() - loop_start))

    async def _prev():
        press = ano.events['left_press']
        while True:
            await press.wait()
            press.clear()
            if wifi.radio.connected and player:
                # show back indicator
                ui.track_info.show_icon('prev')
                # make the call
                await player.prev()
                # hide back indicator
                ui.track_info.hide_icon('prev')

    async def _next():
        press = ano.events['right_press']
        while True:
            await press.wait()
            press.clear()
            if wifi.radio.connected and player:
                # show next indicator
                ui.track_info.show_icon('next')
                await player.next()
                # hide next indicator
                ui.track_info.hide_icon('next')

    # ui tasks
    loop.create_task(_refresh())
    loop.create_task(_status_ip())
    loop.create_task(_track_info())
    # controls tasks with ui implications
    loop.create_task(_prev())
    loop.create_task(_next())

    print('locating sonoses')
    # TODO: monitor players over time
    # TODO: make this selectable instead of hardcoded
    players = {'players': {}, 'rooms': {}}
    ui.status_bar.sonos = 'connecting...'
    target_room = 'Mike’s Office'
    while not players['rooms'].get(target_room, {}).get('primary'):
        await discover_sonos(players)

    player = players['rooms'][target_room]['primary']
    ui.status_bar.sonos = player.room_name.replace('’', "'")

    print('connecting event handlers')
    loop.create_task(play_pause(player, ano.events['select_press']))
    loop.create_task(volume(player, ano, ano.events['encoder']))

    print('ready')
    while True:
        await asyncio.sleep(60)


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
