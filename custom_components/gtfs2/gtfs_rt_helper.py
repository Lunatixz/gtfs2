import logging
from datetime import datetime, timedelta
import json
import os

import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util
import requests
import voluptuous as vol
from google.transit import gtfs_realtime_pb2
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE, CONF_NAME
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

from .const import (

    ATTR_STOP_ID,
    ATTR_ROUTE,
    ATTR_TRIP,
    ATTR_DIRECTION_ID,
    ATTR_DUE_IN,
    ATTR_DUE_AT,
    ATTR_NEXT_UP,
    ATTR_ICON,
    ATTR_UNIT_OF_MEASUREMENT,
    ATTR_DEVICE_CLASS,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,

    CONF_API_KEY,
    CONF_X_API_KEY,
    CONF_STOP_ID,
    CONF_ROUTE,
    CONF_DIRECTION_ID,
    CONF_DEPARTURES,
    CONF_TRIP_UPDATE_URL,
    CONF_VEHICLE_POSITION_URL,
    CONF_ROUTE_DELIMITER,
    CONF_ICON,
    CONF_SERVICE_TYPE,
    CONF_RELATIVE_TIME,

    DEFAULT_SERVICE,
    DEFAULT_ICON,
    DEFAULT_DIRECTION,
    DEFAULT_PATH,
    DEFAULT_PATH_GEOJSON,

    TIME_STR_FORMAT
)

def due_in_minutes(timestamp):
    """Get the remaining minutes from now until a given datetime object."""
    diff = timestamp - dt_util.now().replace(tzinfo=None)
    return int(diff.total_seconds() / 60)


def log_info(data: list, indent_level: int) -> None:
    indents = "   " * indent_level
    info_str = f"{indents}{': '.join(str(x) for x in data)}"
    _LOGGER.info(info_str)


def log_error(data: list, indent_level: int) -> None:
    indents = "   " * indent_level
    info_str = f"{indents}{': '.join(str(x) for x in data)}"
    _LOGGER.error(info_str)


def log_debug(data: list, indent_level: int) -> None:
    indents = "   " * indent_level
    info_str = f"{indents}{' '.join(str(x) for x in data)}"
    _LOGGER.debug(info_str)



def get_gtfs_feed_entities(url: str, headers, label: str):
    _LOGGER.debug(f"GTFS RT get_feed_entities for url: {url} , headers: {headers}, label: {label}")
    feed = gtfs_realtime_pb2.FeedMessage()  # type: ignore

    # TODO add timeout to requests call
    response = requests.get(url, headers=headers, timeout=20)
    if response.status_code == 200:
        log_info([f"Successfully updated {label}", response.status_code], 0)
    else:
        log_error(
            [
                f"Updating {label} got",
                response.status_code,
                response.content,
            ],
            0,
        )
    if label == "alerts":
        _LOGGER.debug("Feed : %s", feed)
        _LOGGER.debug("Feed parse: %s", feed.ParseFromString(response.content))
    feed.ParseFromString(response.content) 
    return feed.entity

def get_next_services(self):
    self.data = self._get_rt_route_statuses
    self._stop = self._stop_id
    self._destination = self._destination_id
    self._route = self._route_id
    self._trip = self._trip_id
    self._direction = self._direction
    _LOGGER.debug("RT route: %s", self._route)
    _LOGGER.debug("RT trip: %s", self._trip)
    _LOGGER.debug("RT stop: %s", self._stop)
    _LOGGER.debug("RT direction: %s", self._direction)
    next_services = self.data.get(self._route, {}).get(self._direction, {}).get(self._stop, [])
    if not next_services:
        # GTFS RT feed may differ, try via trip
        self._direction = '0'
        self.data2 = get_rt_trip_statuses(self)
        next_services = self.data2.get(self._trip, {}).get(self._direction, {}).get(self._stop, [])
        _LOGGER.debug("Next Services, using trip_id instead of route_id: %s", next_services)
        if next_services:
            _LOGGER.debug("Next services trip_id[0]: %s", next_services[0])
        
    if self.hass.config.time_zone is None:
        _LOGGER.error("Timezone is not set in Home Assistant configuration")
        timezone = "UTC"
    else:
        timezone=dt_util.get_time_zone(self.hass.config.time_zone)
    
    if self._relative :
        due_in = (
            due_in_minutes(next_services[0].arrival_time)
            if len(next_services) > 0
            else "-"
        )
    else:
        due_in = (
            dt_util.as_utc(next_services[0].arrival_time)
            if len(next_services) > 0
            else "-"
        )

    attrs = {
        ATTR_DUE_IN: due_in,
        ATTR_STOP_ID: self._stop,
        ATTR_ROUTE: self._route,
        ATTR_TRIP: self._trip,
        ATTR_DIRECTION_ID: self._direction,
        ATTR_LATITUDE: "",
        ATTR_LONGITUDE: ""
    }
    if len(next_services) > 0:
        attrs[ATTR_DUE_AT] = (
            next_services[0].arrival_time.strftime(TIME_STR_FORMAT)
            if len(next_services) > 0
            else "-"
        )
        if next_services[0].position:
            if next_services[0].position[0]:
                attrs[ATTR_LATITUDE] = next_services[0].position[0][1]
                attrs[ATTR_LONGITUDE] = next_services[0].position[0][0]
    if len(next_services) > 1:
        attrs[ATTR_NEXT_UP] = (
            next_services[1].arrival_time.strftime(TIME_STR_FORMAT)
            if len(next_services) > 1
            else "-"
        )
    if self._relative :
        attrs[ATTR_UNIT_OF_MEASUREMENT] = "min"
    else :
        attrs[ATTR_DEVICE_CLASS] = (
            "timestamp" 
            if len(next_services) > 0
            else ""
        )

    _LOGGER.debug("GTFS RT next services attributes: %s", attrs)
    return attrs
    
def get_rt_route_statuses(self):
    vehicle_positions = {}
    
    if self._vehicle_position_url != "" :   
        vehicle_positions = get_rt_vehicle_positions(self)
              
    class StopDetails:
        def __init__(self, arrival_time, position):
            self.arrival_time = arrival_time
            self.position = position

    departure_times = {}

    feed_entities = get_gtfs_feed_entities(
        url=self._trip_update_url, headers=self._headers, label="trip data"
    )
    self._feed_entities = feed_entities

    for entity in feed_entities:
        if entity.HasField("trip_update"):
            # If delimiter specified split the route ID in the gtfs rt feed
            if self._route_delimiter is not None:
                route_id_split = entity.trip_update.trip.route_id.split(
                    self._route_delimiter
                )
                if route_id_split[0] == self._route_delimiter:
                    route_id = entity.trip_update.trip.route_id
                else:
                    route_id = route_id_split[0]
                log_debug(
                    [
                        "Feed Route ID",
                        entity.trip_update.trip.route_id,
                        "changed to",
                        route_id,
                    ],
                    1,
                )
            else:
                route_id = entity.trip_update.trip.route_id
            
            if route_id == self._route_id:

                
                if route_id not in departure_times:
                    departure_times[route_id] = {}
                
                if entity.trip_update.trip.direction_id is not None:
                    direction_id = str(entity.trip_update.trip.direction_id)
                else:
                    direction_id = DEFAULT_DIRECTION
                if direction_id not in departure_times[route_id]:
                    departure_times[route_id][direction_id] = {}

                for stop in entity.trip_update.stop_time_update:
                    stop_id = stop.stop_id
                    if not departure_times[route_id][direction_id].get(
                        stop_id
                    ):
                        departure_times[route_id][direction_id][stop_id] = []
                    # Use stop arrival time;
                    # fall back on departure time if not available
                    if stop.arrival.time == 0:
                        stop_time = stop.departure.time
                    else:
                        stop_time = stop.arrival.time
                    #)
                    # Ignore arrival times in the past
                    if due_in_minutes(datetime.fromtimestamp(stop_time)) >= 0:
                        details = StopDetails(
                            datetime.fromtimestamp(stop_time),
                            [d["properties"].get(entity.trip_update.trip.trip_id) for d in vehicle_positions],
                        )
                        departure_times[route_id][direction_id][
                            stop_id
                        ].append(details)

    # Sort by arrival time
    for route in departure_times:
        for direction in departure_times[route]:
            for stop in departure_times[route][direction]:
                departure_times[route][direction][stop].sort(
                    key=lambda t: t.arrival_time
                )

    self.info = departure_times
    #_LOGGER.debug("Departure times Route: %s", departure_times)
    return departure_times
    
def get_rt_trip_statuses(self):

    vehicle_positions = {}
    
    if self._vehicle_position_url != "" :   
        vehicle_positions = get_rt_vehicle_positions(self)
              
    class StopDetails:
        def __init__(self, arrival_time, position):
            self.arrival_time = arrival_time
            self.position = position

    departure_times = {}

    feed_entities = self._feed_entities

    for entity in feed_entities:

        if entity.HasField("trip_update"):
            trip_id = entity.trip_update.trip.trip_id        
            if trip_id == self._trip_id:
                _LOGGER.debug("RT Trip, found trip: %s", trip_id)

                if trip_id not in departure_times:
                    departure_times[trip_id] = {}
                
                if entity.trip_update.trip.direction_id is not None:
                    direction_id = str(entity.trip_update.trip.direction_id)
                else:
                    direction_id = DEFAULT_DIRECTION
                if direction_id not in departure_times[trip_id]:
                    departure_times[trip_id][direction_id] = {}

                for stop in entity.trip_update.stop_time_update:
                    stop_id = stop.stop_id
                    if not departure_times[trip_id][direction_id].get(
                        stop_id
                    ):
                        departure_times[trip_id][direction_id][stop_id] = []
                    # Use stop arrival time;
                    # fall back on departure time if not available
                    if stop.arrival.time == 0:
                        stop_time = stop.departure.time
                    else:
                        stop_time = stop.arrival.time
                    # Ignore arrival times in the past
                    if due_in_minutes(datetime.fromtimestamp(stop_time)) >= 0:
                        details = StopDetails(
                            datetime.fromtimestamp(stop_time),
                            [d["properties"].get(entity.trip_update.trip.trip_id) for d in vehicle_positions],
                        )
                        departure_times[trip_id][direction_id][
                            stop_id
                        ].append(details)

    # Sort by arrival time
    for trip in departure_times:
        for direction in departure_times[trip]:
            for stop in departure_times[trip][direction]:
                departure_times[trip][direction][stop].sort(
                    key=lambda t: t.arrival_time
                )

    self.info = departure_times
    #_LOGGER.debug("Departure times Trip: %s", departure_times)
    return departure_times    

def get_rt_vehicle_positions(self):
    feed_entities = get_gtfs_feed_entities(
        url=self._vehicle_position_url,
        headers=self._headers,
        label="vehicle positions",
    )
    geojson_body = []
    geojson_element = {"geometry": {"coordinates":[],"type": "Point"}, "properties": {"id": "", "title": "", "trip_id": "", "route_id": "", "direction_id": "", "vehicle_id": "", "vehicle_label": ""}, "type": "Feature"}
    for entity in feed_entities:
        vehicle = entity.vehicle
        
        if not vehicle.trip.trip_id:
            # Vehicle is not in service
            continue
        if vehicle.trip.trip_id == self._trip_id:    
            log_debug(
                [
                    "Adding position for trip ID",
                    vehicle.trip.trip_id,
                    "route ID",
                    vehicle.trip.route_id,
                    "direction ID",
                    vehicle.trip.direction_id,
                    "position latitude",
                    vehicle.position.latitude,
                    "longitude",
                    vehicle.position.longitude,
                ],
                2,
            )    
            
        #construct geojson only for configured rout/direction
        if str(self._route_id) == str(vehicle.trip.route_id) and str(self._direction) == str(vehicle.trip.direction_id):
            geojson_element = {"geometry": {"coordinates":[],"type": "Point"}, "properties": {"id": "", "title": "", "trip_id": "", "route_id": "", "direction_id": "", "vehicle_id": "", "vehicle_label": ""}, "type": "Feature"}
            geojson_element["geometry"]["coordinates"] = []
            geojson_element["geometry"]["coordinates"].append(vehicle.position.longitude)
            geojson_element["geometry"]["coordinates"].append(vehicle.position.latitude)
            geojson_element["properties"]["id"] = str(vehicle.trip.route_id) + "(" + str(vehicle.trip.direction_id) + ")"
            geojson_element["properties"]["title"] = str(vehicle.trip.route_id) + "(" + str(vehicle.trip.direction_id) + ")"
            geojson_element["properties"]["trip_id"] = vehicle.trip.trip_id
            geojson_element["properties"]["route_id"] = vehicle.trip.route_id
            geojson_element["properties"]["direction_id"] = vehicle.trip.direction_id
            geojson_element["properties"]["vehicle_id"] = "tbd"
            geojson_element["properties"]["vehicle_label"] = "tbd"
            geojson_element["properties"][vehicle.trip.trip_id] = geojson_element["geometry"]["coordinates"]
            geojson_body.append(geojson_element)
    
    self.geojson = {"features": geojson_body, "type": "FeatureCollection"}
        
    _LOGGER.debug("GTFS RT geojson: %s", json.dumps(self.geojson))
    self._route_dir = self._route_id + "_" + self._direction
    update_geojson(self)
    return geojson_body
    
def get_rt_alerts(self):
    rt_alerts = {}
    if self._alerts_url:
        feed_entities = get_gtfs_feed_entities(
            url=self._alerts_url,
            headers=self._headers,
            label="alerts",
        )
        for entity in feed_entities:
            if entity.HasField("alert"):
                for x in entity.alert.informed_entity:
                    if x.HasField("stop_id"):
                        stop_id = x.stop_id 
                    else:
                        stop_id = "unknown"
                    if x.HasField("stop_id"):
                        route_id = x.route_id  
                    else:
                        route_id = "unknown"
                if stop_id == self._stop_id and (route_id == "unknown" or route_id == self._route_id): 
                    _LOGGER.debug("RT Alert for route: %s, stop: %s, alert: %s", route_id, stop_id, entity.alert.header_text)
                    rt_alerts["origin_stop_alert"] = (str(entity.alert.header_text).split('text: "')[1]).split('"',1)[0].replace(':','').replace('\n','')
                if stop_id == self._destination_id and (route_id == "unknown" or route_id == self._route_id): 
                    _LOGGER.debug("RT Alert for route: %s, stop: %s, alert: %s", route_id, stop_id, entity.alert.header_text)
                    rt_alerts["destination_stop_alert"] = (str(entity.alert.header_text).split('text: "')[1]).split('"',1)[0].replace(':','').replace('\n','')
                if stop_id == "unknown" and route_id == self._route_id: 
                    _LOGGER.debug("RT Alert for route: %s, stop: %s, alert: %s", route_id, stop_id, entity.alert.header_text)
                    rt_alerts["origin_stop_alert"] = (str(entity.alert.header_text).split('text: "')[1]).split('"',1)[0].replace(':','').replace('\n','')
                    rt_alerts["destination_stop_alert"] = (str(entity.alert.header_text).split('text: "')[1]).split('"',1)[0].replace(':','').replace('\n','')    
                        
    return rt_alerts
    
    
def update_geojson(self):    
    geojson_dir = self.hass.config.path(DEFAULT_PATH_GEOJSON)
    os.makedirs(geojson_dir, exist_ok=True)
    file = os.path.join(geojson_dir, self._route_dir + ".json")
    _LOGGER.debug("GTFS RT geojson file: %s", file)
    with open(file, "w") as outfile:
        json.dump(self.geojson, outfile)
        
def get_gtfs_rt_trip(hass, path, data):
    """Get gtfs rt trip data"""
    _LOGGER.debug("Getting gtfs rt trip with data: %s", data)
    gtfs_dir = hass.config.path(path)
    os.makedirs(gtfs_dir, exist_ok=True)
    url = data["url"]
    file = data["entity_id"][0].split('.')[1] + "_rt.trip"
    try:
        r = requests.get(url, allow_redirects=True)
        open(os.path.join(gtfs_dir, file), "wb").write(r.content)
    except Exception as ex:  # pylint: disable=broad-except
        _LOGGER.error("The given URL or GTFS data file/folder was not found")
        return "no_data_file"
    return None        
    
    
        
