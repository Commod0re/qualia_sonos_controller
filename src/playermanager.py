import os
from adafruit_datetime import datetime, timedelta

import asonos
import ssdp
import timezone


def cache_player(player):
    ro = storage.getmount("/").readonly
    if ro:
        storage.remount("/", readonly=False)
    with open('/player.cache', 'w') as f:
        # dump approximation of ssdp_parsed
        json.dump({
            'ip': player.ip,
            'port': player.port,
            'base': player.base,
            'household_id': player.household_id,
        }, f)
    if ro:
        storage.remount("/", readonly=True)


def player_from_cache():
    try:
        mtime = timezone.fromlocaltime(os.stat('/player.cache')[8])
        cache_expires = mtime + timedelta(days=30)
        if now <= cache_expires:
            with open('/player.cache', 'r') as f:
                return asonos.Sonos(**json.load(f))
    except OSError:
        # no player cache; nothing to do
        pass

    # no cache or cache expired
    return None


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
