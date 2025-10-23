import asyncio
import babyxml
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
import event
import ntp
import ui
from asonos import htmldecode
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
    album_art_changed = event.EventWithData()
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

    @task_restart('avtransport_event_handler')
    async def _avtransport():
        nonlocal cur_state
        await player_manager.connected.wait()
        ev = player_manager.callback_events['AVTransport']

        last_album_art_uri = None
        track = {
            'title': ui.track_info.track_name,
            'artist': ui.track_info.artist_name,
            'album': ui.track_info.album_name,
        }
        # position, duration = ui.play_progress.play_position, ui.play_progress.track_duration
        while True:
            last_change = await ev.wait()
            ev.clear()

            # update player state
            cur_state = last_change['TransportState_attrs', 0]['val']
            # TODO: update current play position
            # update current track duration
            ui.play_progress.track_duration = last_change['CurrentTrackDuration_attrs', 0]['val']
            trackmeta = (babyxml.xmltodict(htmldecode(last_change['CurrentTrackMetaData_attrs', 0]['val']))
                            .get(('DIDL-Lite', 0), {})
                            .get(('item', 0), {}))
            # update current track info
            cur_track = {
                'title': htmldecode(trackmeta.get(('dc:title', 0), '')),
                'artist': htmldecode(trackmeta.get(('dc:creator', 0), '')),
                'album': htmldecode(trackmeta.get(('upnp:album', 0), '')),
            }
            if track != cur_track:
                ui.track_info.artist_name = cur_track['artist']
                ui.track_info.album_name = cur_track['album']
                ui.track_info.track_name = cur_track['title']
                track = cur_track
                print(f'[{datetime.now()}] track is now {cur_track["artist"]} - {cur_track["album"]} - {cur_track["title"]}')

            # update album art uri
            album_art_uri = (
                htmldecode(trackmeta.get(('upnp:albumArtURI', 0), ''))
                    # modify some arguments
                    .replace('?w=200&auto=format,compress?w=200', '?w=400&fm=jpg&jpeg-progressive=false')
                    .replace('&auto=format,compress', ''))
            if album_art_uri and '://' not in album_art_uri:
                album_art_uri = f'{player_manager.player.base}{album_art_uri}'
            if album_art_uri != last_album_art_uri:
                album_art_changed.set(album_art_uri)
                last_album_art_uri = album_art_uri

            # update current medium info
            urimeta = babyxml.xmltodict(htmldecode(last_change['AVTransportURIMetaData_attrs', 0]['val']))['DIDL-Lite', 0]['item', 0]
            ui.track_info.media_title = htmldecode(urimeta.get(('dc:title', 0), ''))

    @task_restart('album_art')
    async def _album_art():
        while True:
            album_art_uri = await album_art_changed.wait()
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
                # I wish it didn't have to be this way
                # but upnp events are not always timely
                # so we can't rely on being perfectly synced that way
                cur_state = await player_manager.player.state()
                if cur_state in {'STOPPED', 'PAUSED_PLAYBACK'}:
                    ui.track_info.show_icon('play')
                    await player_manager.player.play()
                    ui.track_info.hide_icon('play')
                else:
                    ui.track_info.show_icon('pause')
                    await player_manager.player.pause()
                    ui.track_info.hide_icon('pause')

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
    loop.create_task(_avtransport())
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
