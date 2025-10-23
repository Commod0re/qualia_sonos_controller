import asyncio
import json
import os
import storage
import traceback
import wifi
from adafruit_datetime import datetime, timedelta

import asonos
import ssdp
import timezone


class PlayerManager:
    @property
    def is_connected(self):
        return wifi.radio.connected and self.connected.is_set()

    def __init__(self):
        self.player = None
        self.player_name = None
        self.connected = asyncio.Event()
        self.callback_events = {}

    @staticmethod
    def init_storage():
        ro = storage.getmount("/").readonly
        if ro:
            try:
                storage.remount("/", readonly=False, disable_concurrent_write_protection=True)
            except RuntimeError as e:
                print(f'[{datetime.now()}] failed to remount "/": RuntimeError({e})')

    @staticmethod
    def load_user_config():
        try:
            with open('/user.config', 'r') as f:
                return json.load(f)
        except OSError:
            # no saved user config
            return {}

    def save_user_config(self):
        with open('/user.config', 'w') as f:
            json.dump({
                'player_name': self.player.room_name
            }, f)

    async def load_player(self):
        # load from cache
        cached = player_cache()
        if cached:
            try:
                self.player = await asonos.Sonos.connect(**cached)
            except Exception as e:
                print(f'[{datetime.now()}] Exception: {type(e)}({e})')
                traceback.print_exception(e)

        if not self.player:
            # loading from cache did not occur so now load the user config
            print('locating sonoses')
            user_config = self.load_user_config()
            target_room = user_config['player_name']
            players = {'players': {}, 'rooms': {}}

            # TODO: if user_config did not load for any reason
            #       we need to show a picker UI during scan
            while not players['rooms'].get(target_room, {}).get('primary'):
                await discover_sonos(players)

            self.player = players['rooms'][target_room]['primary']
            try:
                cache_player(self.player)
            except Exception as e:
                print(f'[{datetime.now()}] cache_player failed Exception: {type(e)}({e})')

        self.callback_events['AVTransport'] = await self.player.subscribe('AVTransport')
        self.connected.set()
        return self.player


def cache_player(player):
    with open('/player.cache', 'w') as f:
        # dump approximation of ssdp_parsed
        json.dump({
            'ip': player.ip,
            'port': player.port,
            'household_id': player.household_id,
        }, f)


def player_cache():
    try:
        mtime = timezone.fromlocaltime(os.stat('/player.cache')[8])
        cache_expires = mtime + timedelta(days=30)
        if datetime.now() <= cache_expires:
            with open('/player.cache', 'r') as f:
                return json.load(f)
    except OSError:
        # no player cache; nothing to do
        pass

    # no cache or cache expired
    return None


def invalidate_cache():
    try:
        os.remove('/player.cache')
    except OSError:
        # failed to invalidate cache (probably USB mounted)
        pass


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

    async def _connect(kwargs):
        while True:
            try:
                player = await asonos.Sonos.connect(**kwargs)
            except asyncio.TimeoutError:
                print(f'TimeoutError connecting to {kwargs["ip"]}')
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
                connect_tasks[player_id] = asyncio.create_task(_connect(ssdp_parsed))
            print(f'{verb} player at {ssdp_parsed["ip"]}')
    discoverer.close()

    while connect_tasks:
        await asyncio.sleep(1)
