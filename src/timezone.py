from adafruit_datetime import date, datetime, timedelta


PST = timedelta(hours=-8)
PDT = timedelta(hours=-7)


def get_pstpdt(dt):
    # in the US, dst beings on the second Sunday in March at 2am
    # and ends on the first Sunday in November at 2am
    march_1 = date(dt.year, 3, 1)
    dst_begins = datetime(dt.year, 3, (7 - march_1.weekday()) + 7, 2, 0, 0)
    nov_1 = date(dt.year, 11, 1)
    dst_ends = datetime(dt.year, 11, 7 - nov_1.weekday(), 2, 0, 0)

    if dst_begins <= dt <= dst_ends:
        return PDT
    else:
        return PST


def fromtimestamp(ts, tzoffset):
    return datetime.fromtimestamp(ts) + tzoffset


def fromlocaltime(ts):
    dt = datetime.fromtimestamp(ts)
    return dt + get_pstpdt(dt)
