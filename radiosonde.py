import json
import gpxpy.gpx as mod_gpx
from datetime import datetime, timedelta, timezone
import logging as log
import sys
import argparse as mod_argparse
from itertools import count
from czml3 import Document, Packet, Preamble
from czml3.types import (
    IntervalValue,
    Sequence,
    TimeInterval,
    format_datetime_like,
    Cartesian3Value,
    CartographicDegreesListValue,
    CartographicRadiansListValue
)
from czml3.properties import (
    Billboard,
    Clock,
    Color,
    Label,
    Material,
    Model,
    ViewFrom,
    Path,
    Position,
    PositionList,
    Polyline,
    SolidColorMaterial,
    PolylineOutlineMaterial,
    PolylineDashMaterial,
    PolylineMaterial
)


class BoundingBox(object):
    def __init__(self,
                 coord_list=[0, 360, -90, 90],  # minlon maxlon minlat maxlat
                 height_range=[0, 100000]):

        self.min_lon = coord_list[0]
        self.max_lon = coord_list[1]
        self.min_lat = coord_list[2]
        self.max_lat = coord_list[3]
        self.min_ele = height_range[0]
        self.max_ele = height_range[1]

    def __str__(self) -> str:
        return f'bbox lon: {self.min_lon}..{self.max_lon}, lat: {self.min_lat}..{self.max_lat}, ele: {self.min_ele}..{self.max_ele}'

    def habhub_pos_in_bbox(self, p):
        """
        match a hubhub position sample
        return True if within bbox

        example:
              {
                "position_id": "69163055",
                "mission_id": "0",
                "vehicle": "RS_S1130582",
                "server_time": "2020-12-23 12:41:35.448741",
                "gps_time": "2020-12-23 12:41:45",
                "gps_lat": "-34.9376",
                "gps_lon": "138.86803",
                "gps_alt": "26363",
                "gps_heading": "",
                "gps_speed": "19.7",
                "picture": "",
                "temp_inside": "",
                "data": {
                  "comment": "RS41-SG S1130582 401.501 MHz 2.6V",
                  "temperature_external": "-52.9",
                  "humidity": "0.7"
                },
                "callsign": "VK5HS_AUTO_RX",
                "sequence": "7673"
              },
        """
        lat = p["gps_lat"]
        lon = p["gps_lon"]
        ele = p["gps_alt"]
        return (ele >= self.min_ele and ele <= self.max_ele and lat >= self.min_lat and lat <= self.max_lat and lon >= self.min_lon and lon <= self.max_lon)



class SondeObservation(object):
    _serial = count(0)

    def __init__(self,
                 habhub_tracks=[],
                 habhub_receivers=[],
                 bbox=None,
                 start_time=None,
                 end_time=None):
        pass

    def gen_czml(self):
        pass


# python -d habhub.py --habhub-data positions.json foo.json
#  curl --max-time 600 --output positions.json 'https://spacenear.us/tracker/datanew.php?mode=6hours&type=positions&format=json&max_positions=0'

def get_bounds(points):
    """
    return bounding box of a list of gpxpy points
    """
    min_lat = None
    max_lat = None
    min_lon = None
    max_lon = None
    min_ele = None
    max_ele = None

    for point in points:
        if min_lat is None or point.latitude < min_lat:
            min_lat = point.latitude
        if max_lat is None or point.latitude > max_lat:
            max_lat = point.latitude
        if min_lon is None or point.longitude < min_lon:
            min_lon = point.longitude
        if max_lon is None or point.longitude > max_lon:
            max_lon = point.longitude
        if min_ele is None or point.elevation < min_ele:
            min_ele = point.elevation
        if max_ele is None or point.elevation > max_ele:
            max_ele = point.elevation

    if min_lat and max_lat and min_lon and max_lon:
        return {'min_latitude': min_lat, 'max_latitude': max_lat,
                'min_longitude': min_lon, 'max_longitude': max_lon,
                'min_elevation': min_ele, 'max_elevation': max_ele,
                }
    return None


def read_positions(files, bbox=None):
    log.debug(f"{files}")

    p = []
    for filename in files:
        with open(filename, 'rb') as fp:
            try:
                log.debug(f"doing {filename}")
                js = json.loads(fp.read().decode('utf8'))
                p.append(js)
            except Exception as e:
                log.error(f"file: {filename} {e}")


def main():
    parser = mod_argparse.ArgumentParser(usage='%(prog)s [-s] [-m] [-d] [json file ...]',
                                         description='convert  radisonde data to CZML. ')

    parser.add_argument('--habhub-data',
                        dest='hh_files',
                        nargs='+',
                        metavar='positions.json',
                        type=str,
                        default=[],
                        help='one or more json files containing habhub positions in JSON format. '
                        'example: '
                        "curl --max-time 600 --output positions.json"
                        " 'https://spacenear.us/tracker/datanew.php?mode=6hours&type=positions&format=json&max_positions=0'")

    parser.add_argument('--habhub-receivers', dest='hh_reivers',
                        metavar='receivers.json',
                        nargs='+',
                        type=str,
                        default=[],
                        help='one or more json files containing lists of habhub stations. '
                        "example: curl --output receivers.json 'http://spacenear.us/tracker/receivers.php'")

    parser.add_argument('-d', '--debug',
                        action='store_true',
                        help='show detailed logging')

    parser.add_argument('-b', '--bbox',
                        nargs=4,
                        default=[0, 360, -90, 90],
                        help='coordinates of bounding box to convert, example: 14.5 16.8 46 47.5 '
                        'values: minlon maxlon minlat maxlat')

    parser.add_argument('--height-range',
                        nargs=2,
                        default=[0, 100000],
                        help='lower and upper boundary. example: --height-range 0 6000 '
                        'values: minheight maxheight')
    args, files = parser.parse_known_args()

    global debug
    debug = args.debug

    logformat = "[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s"
    if debug:
        log.basicConfig(format=logformat, level=log.DEBUG)  # verbose
    else:
        log.basicConfig(format=logformat, level=log.ERROR)  # default
    log.error(f"{args}")
    log.debug(f"{args.bbox}")

    bbox = BoundingBox(coord_list=args.bbox, height_range=args.height_range)
    log.debug(f"bbox={bbox}")

    positions = read_positions(args.hh_files, bbox=None)
    sys.exit(0)

    with open("foo.json", "r") as jsonfile:
        j = json.load(jsonfile)

    poslist = j['positions']['position']

    vehicles = dict()

    # collect vehicles
    for p in poslist:
        vehicles[p['vehicle']] = []

    # collate positions
    # do a bbox here
    for p in poslist:
        vehicles[p['vehicle']].append(p)

    for v, poslist in vehicles.items():
        print(len(poslist), v)

    # tv = vehicles['RS_R3341161']
    #
    # print(len(tv))
    #  python habhub.py|sort -rn|less


if __name__ == "__main__":
    main()
