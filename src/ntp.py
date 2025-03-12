import asyncio
import os
import rtc

import adafruit_ntp

import ahttp


def ntp():
    ntp_server = os.getenv('NTP_SERVER')
    ntp_client = adafruit_ntp.NTP(ahttp.pool, server=ntp_server)
    clock = rtc.RTC()

    # sync the clock
    clock.datetime = ntp_client.datetime

    # monitor task
    async def monitor_ntp():
        while True:
            # sync every hour
            await asyncio.sleep(60 * 60)
            # naive solution: resync NTP every interval no matter how larger or small the diff
            # TODO: when the diff between our time and the NTP server's time is larger than a certain amount
            #       we should make smaller adjustments every interval instead of blindly resyncing
            clock.datetime = ntp_client.datetime

    return monitor_ntp()
