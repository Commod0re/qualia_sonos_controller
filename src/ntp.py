import asyncio
import os
import rtc

import adafruit_ntp
from adafruit_datetime import datetime, timedelta

import ahttp


def get_dst_dates_for_year(year):
    # going by US DST rules:
    # DST begins at 2AM on the second Sunday in March and ends on the first Sunday in November
    # so first calculate the relevant date range for input dt
    march_1 = datetime(year, 3, 1)
    dst_start = datetime(year, 3, 14 - march_1.weekday(), 2)
    nov_1 = datetime(year, 11, 1)
    dst_end = datetime(year, 11, 7 - nov_1.weekday(), 2)
    return dst_start, dst_end


def is_dst(dt, dst_start=None, dst_end=None):
    if dst_start is None or dst_end is None:
        dst_start, dst_end = get_dst_dates_for_year(dt.year)
    # now return whether dt is within the range or not
    return dst_start <= dt <= dst_end


def ntp():
    ntp_server = os.getenv('NTP_SERVER')
    tz_offset = int(os.getenv('NTP_TZ_OFFSET', '0'))
    ntp_client = adafruit_ntp.NTP(ahttp.pool, server=ntp_server, tz_offset=tz_offset)
    clock = rtc.RTC()

    # sync the clock to standard time
    while True:
        try:
            clock.datetime = ntp_client.datetime
        except OSError as e:
            print(e)
            pass
        else:
            break

    # calculate our actual tz offset and re-instantiate ntp_client
    dst_start, dst_end = get_dst_dates_for_year(clock.datetime.tm_year)
    last_is_dst = new_is_dst = is_dst(datetime.now())
    ntp_client = adafruit_ntp.NTP(ahttp.pool, server=ntp_server, tz_offset=tz_offset + int(last_is_dst))

    # monitor task
    async def monitor_ntp():
        nonlocal dst_start, dst_end, last_is_dst, new_is_dst, ntp_client

        while True:
            # sync every hour
            await asyncio.sleep(60 * 60)

            # on certain dates, during certain time ranges, re-check last_is_dst and re-instantiate ntp_client
            today = (clock.datetime.tm_mon, clock.datetime.tm_mday)
            # - dst start date
            if today == (dst_start.month, dst_start.day) and (not last_is_dst):
                new_is_dst = is_dst(datetime.now(), dst_start, dst_end)
            # - dst end date
            elif today == (dst_end.month, dst_end.day) and last_is_dst:
                new_is_dst = is_dst(datetime.now(), dst_start, dst_end)
            # - january 1st
            elif today == (1, 1) and clock.datetime.tm_year != dst_start.year:
                dst_start, dst_end = get_dst_dates_for_year(tm.tm_year)

            # if our dst state changed we need to re-instantiate the ntp client
            if new_is_dst != last_is_dst:
                ntp_client = adafruit_ntp.NTP(ahttp.pool, server=ntp_server, tz_offset=tz_offset + int(last_is_dst))

            # naive solution: resync NTP every interval no matter how larger or small the diff
            # TODO: when the diff between our time and the NTP server's time is above zero but smaller than a certain amount
            #       we should try to make adjustments via RTC calibration instead of blindly setting the clock
            try:
                clock.datetime = ntp_client.datetime
            except OSError as e:
                print(e)


    return monitor_ntp()
