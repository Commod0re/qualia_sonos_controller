import asyncio
import collections
import io
import json
import os
import traceback
import time
import wifi
from adafruit_datetime import datetime, timedelta
from microcontroller import watchdog
from watchdog import WatchDogMode

import ahttp
import controls
import ntp
import ui
from playermanager import PlayerManager


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
                    traceback.print_exception(e)

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


async def main():
    loop = asyncio.get_event_loop()

    # print('managing wifi')
    # loop.create_task(wifi_roaming())

    print('syncing NTP')
    loop.create_task(ntp.ntp())

    print('setting up controls')
    ano = await controls.AnoRotary.new(ui.i2c)
    qbtns = await controls.QualiaButtons.new(ui.i2c)
    album_art_changed = asyncio.Event()
    album_art_uri = None
    cur_state = None
    player_manager = PlayerManager()
    player_manager.init_storage()

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

    async def _state_changed(last_state):
        while True:
            if last_state != cur_state:
                return cur_state
            await asyncio.sleep(0.25)

    async def _state_based_sleep(delta):
        interval = 30 if cur_state == 'STOPPED' else 1
        if delta >= (interval - 0.2):
            return
        try:
            await asyncio.wait_for(_state_changed(cur_state), timeout=interval - delta)
        except asyncio.TimeoutError:
            # waited the full duration
            pass

    @task_restart('track_info')
    async def _track_info():
        nonlocal album_art_uri
        # TODO: replace polling with events
        track = {
            'title': ui.track_info.track_name,
            'artist': ui.track_info.artist_name,
            'album': ui.track_info.album_name,
            'album_art': '',
            'position': ui.play_progress.play_position,
            'duration': ui.play_progress.track_duration,
            'queue_position': 0,
        }
        medium = {
            'title': ui.track_info.media_title,
            'medium_art': ''
        }
        await player_manager.connected.wait()
        while True:
            loop_start = time.monotonic()
            # NOTE: once I get UPnP event subscriptions working this won't be needed
            #       but as a stopgap, poll current track info less frequently when stopped
            if player_manager.is_connected:
                try:
                    cur_track = await player_manager.player.current_track_info()
                except asyncio.TimeoutError:
                    print(f'[{datetime.now()}] TIMEOUT - retry')
                    continue
                if cur_track and cur_track != track:
                    # update artist, album, title
                    track_changed = False
                    if cur_track['artist'] != track['artist']:
                        ui.track_info.artist_name = cur_track['artist'] or 'No Artist'
                        track_changed = True
                    if cur_track['album'] != track['album']:
                        ui.track_info.album_name = cur_track['album']
                        track_changed = True
                    if cur_track['title'] != track['title']:
                        new_title = cur_track['title'] or 'No Title'
                        if new_title.startswith(cur_track['artist']):
                            new_title = new_title.split(' - ')[-1]
                        ui.track_info.track_name = new_title
                        track_changed = True
                    # update duration
                    if cur_track['duration'] != track['duration']:
                        ui.play_progress.track_duration = cur_track['duration']
                    # update position
                    if cur_track['position'] is not None:
                        ui.play_progress.play_position = cur_track['position']
                    # update album_art
                    if cur_track['album_art'] != track['album_art']:
                        track['album_art'] = album_art_uri = cur_track['album_art']
                        # fixups
                        if 'imgix.net' in album_art_uri:
                            album_art_uri = (
                                album_art_uri
                                    # modify some arguments
                                    .replace('?w=200&auto=format,compress?w=200', '?w=400&fm=jpg&jpeg-progressive=false')
                                    .replace('&auto=format,compress', ''))
                        album_art_changed.set()
                    # TODO: this could be a background task or a separate handler triggered via event
                    # update media title
                    if track_changed:
                        print(f'[{datetime.now()}] track is now {cur_track["artist"]} - {cur_track["album"]} - {cur_track["title"]}')
                        try:
                            cur_medium = await player_manager.player.medium_info()
                        except asyncio.TimeoutError:
                            print(f'[{datetime.now()}] TIMEOUT')
                        if cur_medium and cur_medium != medium:
                            if cur_medium['title'] != medium['title']:
                                ui.track_info.media_title = cur_medium['title']
                            medium = cur_medium
                    track = cur_track

            await _state_based_sleep(time.monotonic() - loop_start)

    @task_restart('album_art')
    async def _album_art():
        while True:
            await album_art_changed.wait()
            album_art_changed.clear()
            if album_art_uri:
                print(f'loading album_art from {album_art_uri}')
                resp = None
                while not resp:
                    try:
                        resp = await ahttp.get(album_art_uri, {})
                    except asyncio.TimeoutError:
                        print(f'[{datetime.now()}] TIMEOUT - retry')
                        await asyncio.sleep_ms(200)
                    except OSError as e:
                        print(f'[{datetime.now()}] {type(e)}({e}) - retry')
                        await asyncio.sleep_ms(200)
                    else:
                        break

                print('buffering album_art...')
                buf = io.BytesIO(resp.body)
                print('show album_art')
                ui.album_art.show(buf)
            else:
                print('clearing album_art')
                ui.album_art.clear()

    @task_restart('prev')
    async def _prev():
        press = ano.events['left_press']
        while True:
            await press.wait()
            press.clear()
            if player_manager.is_connected:
                # show back indicator
                ui.track_info.show_icon('prev')
                # make the call
                await player_manager.player.prev()
                # hide back indicator
                ui.track_info.hide_icon('prev')

    @task_restart('next')
    async def _next():
        press = ano.events['right_press']
        while True:
            await press.wait()
            press.clear()
            if player_manager.is_connected:
                # show next indicator
                ui.track_info.show_icon('next')
                await player_manager.player.next()
                # hide next indicator
                ui.track_info.hide_icon('next')

    @task_restart('play_pause')
    async def _play_pause():
        nonlocal cur_state
        on_select_press = ano.events['select_press']
        while True:
            await on_select_press.wait()
            on_select_press.clear()

            if player_manager.is_connected:
                cur_state = await player_manager.player.state()
                if cur_state in {'STOPPED', 'PAUSED_PLAYBACK'}:
                    ui.track_info.show_icon('play')
                    await player_manager.player.play()
                    ui.track_info.hide_icon('play')
                    cur_state = 'PLAYING'
                else:
                    ui.track_info.show_icon('pause')
                    await player_manager.player.pause()
                    ui.track_info.hide_icon('pause')
                    cur_state = 'PAUSED_PLAYBACK'

    @task_restart('volume')
    async def _volume():
        ev = ano.events['encoder']
        await player_manager.connected.wait()
        # get initial encoder position for delta tracking
        pos = ano.encoder.position
        vol = ui.volume.volume = await player_manager.player.volume()

        while True:
            await ev.wait()
            # get new encoder position and calculate delta from last time
            new_pos = ano.encoder.position
            delta, pos = new_pos - pos, new_pos

            # if position changed, update the UI and speaker
            if player_manager.is_connected and delta:
                vol = ui.volume.volume = await player_manager.player.volume(vol + delta)
            ev.clear()

    @task_restart('tickle_watchdog')
    async def _tickle_watchdog():
        watchdog.timeout = 60
        watchdog.mode = WatchDogMode.RESET
        while True:
            await asyncio.sleep(30)
            watchdog.feed()

    print('connecting event handlers')
    # ui tasks
    loop.create_task(_refresh())
    loop.create_task(_status_ip())
    loop.create_task(_track_info())
    loop.create_task(_album_art())
    # controls tasks with ui implications
    loop.create_task(_prev())
    loop.create_task(_next())
    loop.create_task(_play_pause())
    loop.create_task(_volume())
    # watchdog timer
    loop.create_task(_tickle_watchdog())

    print('connecting to sonos')
    player = await player_manager.load_player()

    ui.status_bar.sonos = player.room_name.replace('’', "'")

    print('ready')
    while True:
        await asyncio.sleep(60)


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
