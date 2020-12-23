#!/usr/bin/env python

# python habhub.py --bbox  14.5 16.8 46 47.5  -d --habhub-data positions.json foo.json


import json
import gpxpy
import datetime
# from datetime import datetime, timedelta, timezone, date.fromisoformat
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

DEFAULT_MODEL = "https://static.mah.priv.at/cors/OE-SOX.glb"


class BoundingBox(object):
    def __init__(self,
                 coord_list=[0, 360, -90, 90],  # minlon maxlon minlat maxlat
                 height_range=[0, 100000],
                 gpxpy_track=None):
        self.track = gpxpy_track
        if self.track:
            self._set_from_gpxpy_track(self.track)
        else:
            self.min_lon = coord_list[0]
            self.max_lon = coord_list[1]
            self.min_lat = coord_list[2]
            self.max_lat = coord_list[3]
            self.min_ele = height_range[0]
            self.max_ele = height_range[1]

    def __str__(self) -> str:
        return f'bbox(lon: {self.min_lon}..{self.max_lon}, lat: {self.min_lat}..{self.max_lat}, ele: {self.min_ele}..{self.max_ele})'

    def within_box(self, lat, lon, ele):
        return (ele >= self.min_ele and ele <= self.max_ele and lat >= self.min_lat and lat <= self.max_lat and lon >= self.min_lon and lon <= self.max_lon)

    def habhub_receiver_in_bbox(self, p):
        """
        match a habhub receiver
        return True if within bbox
        example:
        {
            "name": "SQ5SKB",
            "tdiff_hours": 0,
            "lon": 20.849021,
            "lat": 51.979377,
            "alt": 137,
            "description": "\n<font size=\"-2\"><BR>\n<B>Radio: </B>Yaesu FT-991A<BR>\n<B>Antenna: </B>Diamond V2000<BR>\n<B>Last Contact: </B>0 hours ago<BR>\n</font>\n"
        }
        """
        return self.within_box(float(p["lat"]), float(p["lon"]), float(p["alt"]))

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
              }
        """
        return self.within_box(float(p["gps_lat"]), float(p["gps_lon"]), float(p["gps_alt"]))

    def _set_from_gpxpy_track(self, track):
        """
        return bounding box of a list of gpxpy points
        """
        min_lat = None
        max_lat = None
        min_lon = None
        max_lon = None
        min_ele = 100000
        max_ele = -100000

        for (point, segment, point_no) in self.track.walk():
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
            self.min_lat = min_lat
            self.max_lat = max_lat
            self.min_lon = min_lon
            self.max_lon = max_lon
        self.min_ele = min_ele
        self.max_ele = max_ele


class SondeObservations(object):
    _serial = count(0)

    def __init__(self,
                 habhub_tracks=[],
                 habhub_receivers=[],
                 bbox=None,
                 after=None,
                 before=None):
        self.habhub_positions = self._read_json(habhub_tracks)
        self.habhub_receivers = self._read_json(habhub_receivers)
        self.bbox = bbox
        self.after = after
        self.before = before
        self.first_seen = datetime.datetime.max
        self.last_seen = datetime.datetime.min

    def _read_json(self, files):
        p = dict()
        for filename in files:
            with open(filename, 'rb') as fp:
                try:
                    log.debug(f"doing {filename}")
                    js = json.loads(fp.read().decode('utf8'))
                    # p.append(js)
                    p = {**p, **js}
                except Exception as e:
                    log.error(f"file: {filename} {e}")
        return p

    def select_vehicles(self):
        """
        by time and bounding box
        returns a dict {vehicle_name, position_list}

        """
        poslist = self.habhub_positions['positions']['position']
        vehicles = dict()

        # collect vehicles
        for p in poslist:
            vehicles[p['vehicle']] = []

        # collate positions
        for p in poslist:
            if self.bbox.habhub_pos_in_bbox(p):
                if 'gps_time' in p:
                    gps_time = datetime.datetime.strptime(
                        p['gps_time'], '%Y-%m-%d %H:%M:%S')
                    p['parsed_time'] = gps_time

                    # collect timespan(min,max) of all samples
                    if self.last_seen < gps_time:
                        self.last_seen = gps_time
                    if self.first_seen > gps_time:
                        self.first_seen = gps_time

                    if gps_time < self.after or gps_time > self.before:
                        continue
                vehicles[p['vehicle']].append(p)

        for v, poslist in vehicles.items():
            l = len(poslist)
            if l > 0:
                log.debug(f"vehicle {v} positions {l}")
        return vehicles

    def gen_position_list(self, plist):
        """ """
        results = []
        for p in plist:
            results.append(format_datetime_like(p['parsed_time']))
            results.extend([float(p["gps_lon"]),
                            float(p["gps_lat"]),
                            float(p["gps_alt"])])
        return results

    def gen_habhub_vehicle_track(self, v, poslist, model):

        results = []
        start = datetime.datetime.max
        stop = datetime.datetime.min
        for p in poslist:
            t = p['parsed_time']
            if stop < t:
                stop = t
            if start > t:
                start = t
            results.append(format_datetime_like(t))
            results.extend([float(p["gps_lon"]),
                            float(p["gps_lat"]),
                            float(p["gps_alt"])])
        availability = TimeInterval(start=start, end=stop)

        pl = self.gen_position_list(poslist)
        #log.debug(f"vehicle={v} pl={pl}") #" poslist={poslist}")
        # log.debug(f"vehicle={v}")
        # lb = Label(text=packetname,
        #            show=True,
        #            scale=0.5,
        #            pixelOffset={'cartesian2': [50, -30]})
        position = Position(#interpolationDegree=3,
                            cartographicDegrees=pl)
        # interpolationAlgorithm="LAGRANGE",
        # interpolationAlgorithm="LINEAR",
        # epoch=self.starttime(),

        red = Color(rgba=[255, 0, 0, 255])
        grn = Color(rgba=[0, 255, 0, 255])
        po = PolylineOutlineMaterial(color=red,
                                     outlineColor=grn,
                                     outlineWidth=4)
        path = Path(material=Material(polylineOutline=po),
                    width=6,
                    leadTime=0,
                    trailTime=100000,
                    resolution=5)

        p = Packet(id=v,
                   # description="der flug",
                   # name=packetname,
                   position=position,
                   # label=lb,
                   path=path,
                   # reference does not work here 
                   model=model, #"balloon_model#model",
                   viewFrom=ViewFrom(cartesian=Cartesian3Value(
                       values=[-1000, 0, 300])),
                   availability=availability)

        return p

    def gen_czml(self):
        gltf = DEFAULT_MODEL
        model = Model(gltf=gltf,
                      scale=1.0,
                      minimumPixelSize=64)

        #p =  Packet(id="balloon_model",  model=model)
        #packets = [p]
        packets = []
        vehicles = self.select_vehicles()
        for v, poslist in vehicles.items():
            if len(poslist) > 0:
                packets.append(self.gen_habhub_vehicle_track(v, poslist, model))
        return packets

def prolog(name, mintime, maxtime):

    clock = None
    if maxtime > mintime:
        multiplier = 7200
        range = 'CLAMPED'
        step = 'SYSTEM_CLOCK_MULTIPLIER'
        start = mintime
        clock = IntervalValue(start=mintime,
                              end=maxtime,
                              value=Clock(currentTime=start, multiplier=multiplier))

    preamble = Preamble(name='document',
                        description='document description from prolog',
                        clock=clock)
    return preamble

#  ./radiosonde.py --bbox  10 20 42 48  -d --after 2020-12-23 --before 2020-12-24 --habhub-data positions.json foo.json
#  curl --max-time 600 --output positions.json 'https://spacenear.us/tracker/datanew.php?mode=6hours&type=positions&format=json&max_positions=0'

def main():
    parser = mod_argparse.ArgumentParser(usage='%(prog)s arguments',
                                         description='convert radisonde data to CZML. ')

    parser.add_argument('--habhub-data',
                        dest='hh_files',
                        nargs='+',
                        metavar='JSON_FILE',
                        type=str,
                        default=[],
                        help='one or more json files containing habhub positions in JSON format. '
                        'obtain for example with:\n\t'
                        "curl --max-time 600 --output positions.json"
                        " 'https://spacenear.us/tracker/datanew.php?mode=6hours&type=positions&format=json&max_positions=0'")

    parser.add_argument('--habhub-receivers', dest='hh_reivers',
                        metavar='JSON_FILE',
                        nargs='+',
                        type=str,
                        default=[],
                        help='one or more json files containing lists of habhub stations. '
                        "obtain for example with: curl --output receivers.json 'http://spacenear.us/tracker/receivers.php'")

    parser.add_argument('-d', '--debug',
                        action='store_true',
                        help='show detailed logging')

    parser.add_argument('--bbox',
                        dest='bbox',
                        nargs=4,
                        metavar=('MINLON', 'MAXLON', 'MINLAT', 'MAXLAT'),
                        default=[0, 360, -90, 90],
                        type=float,
                        help='coordinates of bounding box to convert, example: --bbox 14.5 16.8 46 47.5')

    parser.add_argument('--height-range',
                        nargs=2,
                        default=[0, 100000],
                        type=float,
                        metavar=('LOWER_BOUNDARY', 'UPPER_BOUNDARY'),
                        help='lower and upper boundary. example: --height-range 0 6000')

    parser.add_argument('--after',
                        type=datetime.datetime.fromisoformat,
                        metavar='DATE',
                        default=datetime.datetime.min,
                        help='export positions sampled after DATE (must be in ISO format)')

    parser.add_argument('--before',
                        type=datetime.datetime.fromisoformat,
                        metavar='DATE',
                        default=datetime.datetime.max,
                        help='export positions sampled before DATE (must be in ISO format)')

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

    so = SondeObservations(habhub_tracks=args.hh_files,
                           habhub_receivers=args.hh_reivers,
                           bbox=bbox,
                           after=args.after,
                           before=args.before)

    packets = so.gen_czml()
    preamble = prolog("habhub", so.first_seen, so.last_seen)
    packets.insert(0, preamble)
    document = Document(packets)
    print(document.dumps(indent=4))

    sys.exit(0)

    # tv = vehicles['RS_R3341161']
    #
    # print(len(tv))
    #  python habhub.py|sort -rn|less
    # if False:
    #     fn = "Stiwoll-Muggauberg.gpx"
    #     with open(fn, 'r') as gpx_file:
    #         gpx = gpxpy.parse(gpx_file)
    #         for t in gpx.tracks:
    #             bbox = BoundingBox(gpxpy_track=t)
    #             log.debug(f"fn={fn} bbox={bbox}")


if __name__ == "__main__":
    main()
