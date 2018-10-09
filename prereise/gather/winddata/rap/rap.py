import datetime
import math
import os
import time
from collections import OrderedDict

import numpy as np
import pandas as pd
import requests
import westernintnet
from netCDF4 import Dataset
from tqdm import tqdm

PowerCurves = pd.read_csv(os.path.dirname(__file__) +
                          '/../IECPowerCurves.csv')


def ll2uv(lon, lat):
    """Convert (longitude, latitude) to unit vector.

    :param lon: longitude of the site (in deg.) measured eastward from
    Greenwich, UK.
    :param lat: latitude of the site (in deg.). Equator is the zero point.
    :return: 3-components (x,y,z) unit vector.
    """
    cos_lat = math.cos(math.radians(lat))
    sin_lat = math.sin(math.radians(lat))
    cos_lon = math.cos(math.radians(lon))
    sin_lon = math.sin(math.radians(lon))

    uv = []
    uv.append(cos_lat * cos_lon)
    uv.append(cos_lat * sin_lon)
    uv.append(sin_lat)

    return uv


def angular_distance(uv1, uv2):
    """Calculate the angular distance between two vectors.

    :param uv1: 3-components vector.
    :param uv2: 3-components vector.
    :return: angle in degrees.
    """
    cos_angle = uv1[0]*uv2[0] + uv1[1]*uv2[1] + uv1[2]*uv2[2]
    if cos_angle >= 1:
        cos_angle = 1
    if cos_angle <= -1:
        cos_angle = -1
    angle = math.degrees(math.acos(cos_angle))

    return angle


def get_power(wspd, turbine):
    """Convert wind speed to power using NREL turbine power curves.

    :param wspd: wind speed (in m/s).
    :param turbine: class of turbine.
    :return: normalized power.
    """
    match = (PowerCurves['Speed bin (m/s)'] <= np.ceil(wspd)) & \
            (PowerCurves['Speed bin (m/s)'] >= np.floor(wspd))
    if not match.any():
        return 0
    values = PowerCurves[turbine][match]
    return np.interp(wspd,
                     PowerCurves[turbine][match].index.values,
                     PowerCurves[turbine][match].values)


def retrieve_data(wind_farm, start_date='2016-01-01', end_date='2017-12-31'):
    """Retrive wind speed data from NOAA's server.

    :param wind_farm: pandas DataFrame of wind farms.
    :param start_date: start date.
    :param end_date: end date (inclusive).
    :return: pandas DataFrame with the columns: plant ID, U-component of the
    wind speed (m/s) 80-m above ground, V-component of wind speed (m/s) 80-m
    above ground, power output (MW), UTC timestamp and timestamp ID. Also
    returns a list of missing files.
    """

    # Information on wind farms
    n_target = len(wind_farm)

    lon_target = wind_farm.lon.values
    lat_target = wind_farm.lat.values
    id_target = wind_farm.index.values
    capacity_target = wind_farm.GenMWMax.values

    # Build query
    link = 'https://www.ncei.noaa.gov/thredds/ncss/rap130anl/'

    start = datetime.datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.datetime.strptime(end_date, '%Y-%m-%d')
    step = datetime.timedelta(days=1)

    files = []
    while start <= end:
        ts = start.strftime('%Y%m%d')
        url = link + ts[:6] + '/' + ts + '/rap_130_' + ts
        for h in range(10000, 12400, 100):
            files.append(url + '_' + str(h)[1:] + '_000.grb2?')
        start += step

    var_u = 'u-component_of_wind_height_above_ground'
    var_v = 'v-component_of_wind_height_above_ground'
    var = 'var=' + var_u + '&' + 'var=' + var_v

    box = 'north=49&west=-122&east=-102&south=32' + '&' + \
          'disableProjSubset=on&horizStride=1&addLatLon=true'

    extension = 'accept=netCDF'

    # Download files and fill out dataframe
    missing = []
    target2grid = OrderedDict()
    data = pd.DataFrame({'plantID': [],
                         'U': [],
                         'V': [],
                         'Pout': [],
                         'ts': [],
                         'tsID': []})
    dt = datetime.datetime.strptime(start_date, '%Y-%m-%d')
    step = datetime.timedelta(hours=1)

    for i, file in tqdm(enumerate(files), total=len(files)):
        if i != 0 and i % 1000 == 0:
            time.sleep(300)
        query = file + var + '&' + box + '&' + extension
        request = requests.get(query)

        data_tmp = pd.DataFrame({'plantID': id_target,
                                 'ts': [dt]*n_target,
                                 'tsID': [i+1]*n_target})

        if request.status_code == 200:
            with open('tmp.nc', 'wb') as f:
                f.write(request.content)
            tmp = Dataset('tmp.nc', 'r')
            lon_grid = tmp.variables['lon'][:].flatten()
            lat_grid = tmp.variables['lat'][:].flatten()
            u_wsp = tmp.variables[var_u][0, 1, :, :].flatten()
            v_wsp = tmp.variables[var_v][0, 1, :, :].flatten()

            n_grid = len(lon_grid)
            if data.empty:
                # The angular distance is calculated once. The target to grid
                # correspondence is stored in a dictionary.
                for j in range(n_target):
                    uv_target = ll2uv(lon_target[j], lat_target[j])
                    angle = [angular_distance(uv_target,
                                              ll2uv(lon_grid[k], lat_grid[k]))
                             for k in range(n_grid)]
                    target2grid[id_target[j]] = np.argmin(angle)

            data_tmp['U'] = [u_wsp[target2grid[id_target[j]]]
                             for j in range(n_target)]
            data_tmp['V'] = [v_wsp[target2grid[id_target[j]]]
                             for j in range(n_target)]
            wspd = np.sqrt(pow(data_tmp['U'], 2) + pow(data_tmp['V'], 2))
            data_tmp['Pout'] = [get_power(val,
                                          'IEC class 2') * capacity_target[j]
                                for j, val in enumerate(wspd)]

            tmp.close()
            os.remove('tmp.nc')
        else:
            missing.append(file)

            # missing data are set to NaN.
            data_tmp['U'] = [np.nan] * n_target
            data_tmp['V'] = [np.nan] * n_target
            data_tmp['Pout'] = [np.nan] * n_target

        data = data.append(data_tmp, ignore_index=True, sort=False)
        dt += step

    # Format dataframe
    data['plantID'] = data['plantID'].astype(np.int32)
    data['tsID'] = data['tsID'].astype(np.int32)

    data.sort_values(by=['tsID', 'plantID'], inplace=True)
    data.reset_index(inplace=True, drop=True)

    return data, missing
