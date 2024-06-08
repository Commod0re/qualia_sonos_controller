import asyncio
import board
import os
import supervisor
import wifi

import asonos
import controls
import display
import ssdp


async def connect_wifi():
    ssid = os.getenv('CIRCUITPY_WIFI_SSID')
    psk = os.getenv('CIRCUITPY_WIFI_PASSWORD')
    while not wifi.radio.connected:
        print('wifi not connected, attempting to reconnect')
        try:
            wifi.radio.connect(ssid, psk)
        except ConnectionError:
            # ssid not found. try a scan
            try:
                networks = wifi.radio.start_scanning_networks()
            except RuntimeError:
                wifi.radio.stop_scanning_networks()
                await asyncio.sleep(0.100)
                networks = wifi.radio.start_scanning_networks()
            print('scanning...')
            await asyncio.sleep(10)
            found = {network.ssid for network in networks}
            wifi.radio.stop_scanning_networks()
            if ssid in found:
                print(f'{ssid} found, retrying')
        if wifi.radio.connected:
            print('wifi connected')
        await asyncio.sleep(1)



async def keep_wifi_connected():
    while True:
        await connect_wifi()
        await asyncio.sleep(1)


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


async def prev(player, ev):
    while True:
        await ev.wait()
        ev.clear()
        print('PREV')
        await player.prev()


async def next(player, ev):
    while True:
        await ev.wait()
        ev.clear()
        print('NEXT')
        await player.next()


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


async def wrap_handler(name, func, *args, **kwargs):
    while True:
        try:
            await func(*args, **kwargs)
        except Exception as e:
            print(f'[{name}] caught {type(e).__name__}: {e}')



async def main():
    loop = asyncio.get_event_loop()

    print('monitoring wifi')
    await connect_wifi()
    loop.create_task(keep_wifi_connected())

    print('locating sonoses')
    # TODO: monitor players over time
    # TODO: make this selectable instead of hardcoded
    # TODO: each room can have multiple players and that might matter somehow
    player_found = False
    checked = set()
    while not player_found:
        async for ssdp_parsed in ssdp.discover():
            print(f'checking player at {ssdp_parsed["ip"]}')
            # print(ssdp_parsed)
            # player = babysonos.Sonos(ssdp_parsed)
            player = asonos.Sonos(**ssdp_parsed)
            await player.connect()
            player_room_name = player.room_name
            print(f'room name = "{player_room_name}"')
            if player_room_name == 'Mike’s Office':
                try:
                    await player.state()
                except KeyError:
                    pass
                else:
                    player_found = True
                    break

    print(f'player "{player_room_name}" located at {player.ip}')

    # TODO: why does it halt the entire process to do this above "locating sonoses"
    print('setting up controls')
    ano = controls.AnoRotary(display.qualia.graphics.i2c_bus)

    print('connecting event handlers')
    # loop.create_task(monitor_current_track(player))
    loop.create_task(wrap_handler('monitor_current_track', monitor_current_track, player))
    # loop.create_task(play_pause(player, ano.events['select_press']))
    loop.create_task(wrap_handler('play_pause', play_pause, player, ano.events['select_press']))
    # loop.create_task(prev(player, ano.events['left_press']))
    loop.create_task(wrap_handler('prev', prev, player, ano.events['left_press']))
    # loop.create_task(next(player, ano.events['right_press']))
    loop.create_task(wrap_handler('next', next, player, ano.events['right_press']))
    # loop.create_task(volume(player, ano, ano.events['encoder']))
    loop.create_task(wrap_handler('volume', volume, player, ano, ano.events['encoder']))

    print('ready')

    while True:
        await asyncio.sleep(1)


loop = asyncio.get_event_loop()
loop.run_until_complete(main())
