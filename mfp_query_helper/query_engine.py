from mfp_query_helper.utils import DateUtils, MfpUtils, TypeUtils, QueryNotFoundError
from elasticsearch import Elasticsearch
from elasticsearch.helpers import scan
from datetime import datetime

class Queries:
    NEW_DEVICES = 'newDevices'
    MFP_APP_VERSTIONS = 'mfpAppVersions'
    DISTINCT_MFP_APP_VERSIONS = 'distinctMfpAppVersions'

    ALL_QUERIES = [NEW_DEVICES, MFP_APP_VERSTIONS, DISTINCT_MFP_APP_VERSIONS]

DEVICES_DOC_TYPE = 'Devices'


def create_es(config):
    return Elasticsearch(hosts=[
        {
            'host': config.host,
            'port': config.port
        }],
        timeout=config.timeout)


def get_new_devices(filter_parameters, config):
    '''
    returns list of objects:
    {
        'date': 0, // day stamp
        'count': 0 // number of devices on that day
    }
    representing devices first appearance
    '''
    es = create_es(config)

    unique_devices = {}

    print('ss: ' + str(config.scroll_size))

    if config.debug:
        print('Query to be executed: ' + str(filter_parameters.build_filtered_query()))

    for device in scan(es, query=filter_parameters.build_filtered_query(),
            index=config.index, doc_type=DEVICES_DOC_TYPE, size=config.scroll_size):
        device = device.get('_source')
        deviceID = device.get('deviceID')

        if deviceID in unique_devices:
            if device.get('firstAccessTimestamp') < unique_devices.get(deviceID).get('firstAccessTimestamp'):
                unique_devices[deviceID] = device
        else:
            unique_devices[deviceID] = device

    results = []
    for deviceID in unique_devices:
        device = unique_devices.get(deviceID)

        # get the date from the firstAccessTimestamp
        # this expects seconds not miliseconds so divide by 1000
        device_date = datetime.fromtimestamp(float(int(device.get('firstAccessTimestamp'))/1000))
        # get the timestamp of the beginning of the day in UTC
        day_timestamp = DateUtils.get_day_timestamp_gmt(device_date)
        # convert dictionary from unicode to string keys and values
        device_obj_str = TypeUtils.convert_dict_to_string(device)

        day_in_results = next((item for item in results if item['date'] == day_timestamp), None)
        if day_in_results:
            day_in_results['count'] += 1
            day_in_results['devices'].append(device_obj_str)
        else:
            results.append({'count': 1, 'date': day_timestamp, 'devices': [device_obj_str]})
    return results


def get_mfp_app_versions(filter_parameters, config):
    '''
    returns counts of all app versions
    {
        'App Name': {
            '1.0': 100,
            '2.0': 52.
            ...
        }
        ...
    }
    '''
    es = create_es(config)

    query = {}
    filter_obj = filter_parameters.build_filter()
    if filter_obj:
        query = {
            'query': {
                'filtered': {
                    'filter': filter_obj
                }
            }
        }

    query['aggs'] = {
        'app_agg': {
            'terms': {
                'field': 'mfpAppName'
            },
            'aggs': {
                'version_agg': {
                    'terms': {
                        'field': 'mfpAppVersion'
                    }
                }
            }
        }
    }

    search = es.search(index=config.index, doc_type=DEVICES_DOC_TYPE, body=query)
    app_buckets = search.get('aggregations').get('app_agg').get('buckets')

    results = {}
    for app in app_buckets:
        app_name = app.get('key')
        version_buckets = app.get('version_agg').get('buckets')

        for bucket in version_buckets:
            version = bucket.get('key')
            doc_count = bucket.get('doc_count')

            if app_name not in results:
                results[app_name] = {
                    version: doc_count
                }
            elif version not in results[app_name]:
                results[app_name][version] = doc_count
            else:
                results[app_name][version] += doc_count

    return results


def get_distinct_mfp_app_versions(filter_parameters, config):
    '''returns counts of distinct app names and versions'''
    es = create_es(config)

    unique_devices = {}
    for device in scan(es, query=filter_parameters.build_filtered_query(),
            index=config.index, doc_type=DEVICES_DOC_TYPE, size=SCROLL_SIZE):
        device = device.get('_source')
        device_key = device.get('deviceID') + device.get('mfpAppName')

        if device_key in unique_devices:
            app_version = device.get('mfpAppVersion')
            # only get latest version
            if not MfpUtils.version_less_than(app_version, unique_devices[device_key].get('mfpAppVersion')):
                unique_devices[device_key] = device
        else:
            unique_devices[device_key] = device

    results = {}
    for device_key in unique_devices:
        device = unique_devices.get(device_key)

        app_name = device.get('mfpAppName')
        app_version = device.get('mfpAppVersion')

        if app_name not in results:
            results[app_name] = {
                app_version: 1
            }
        elif app_version not in results[app_name]:
            results[app_name][app_version] = 1
        else:
            results[app_name][app_version] += 1

    return results


def run_query(query_name, filter_parameters, config):
    if query_name not in Queries.ALL_QUERIES:
        raise QueryNotFoundError('No query named {0}'.format(query_name))

    if query_name == Queries.NEW_DEVICES:
        print(get_new_devices(filter_parameters, config))
    elif query_name == Queries.MFP_APP_VERSTIONS:
        print(get_mfp_app_versions(filter_parameters, config))
    elif query_name == Queries.DISTINCT_MFP_APP_VERSIONS:
        print(get_distinct_mfp_app_versions(filter_parameters, config))
