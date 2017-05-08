#!/usr/bin/env python3

"""Script to watch a folder for new magnet links being put in, uploading them to premiumize.me and adding the respective links to a MyJdownloader instance when finished"""
import sys
import os
import requests
import json
import re
import time
import threading
import myjdapi

env_vars_to_check = ['PREMIUMIZE_CUSTOMER_ID', 'PREMIUMIZE_PIN', 'MYJDOWNLOADER_PASSWORD', 'MYJDOWNLOADER_DEVICENAME', 'MAGNETFILE_DIR']

for env_var in env_vars_to_check:
    if os.environ.get(env_var) is None:
        print("{0} is not set, exiting".format(env_var))
        sys.exit(1)

# Premiumize.me API variables
authentification_params = {'customer_id': os.environ.get('PREMIUMIZE_CUSTOMER_ID'), 'pin': os.environ.get('PREMIUMIZE_PIN')}
torrent_upload_url = 'https://www.premiumize.me/api/transfer/create'
torrent_upload_params = {**{'type': 'torrent'}, **authentification_params}
link_list_url = 'https://www.premiumize.me/api/transfer/list'
link_list_params = authentification_params
link_details_url = 'https://www.premiumize.me/api/torrent/browse'
link_details_params = authentification_params
link_remove_url = 'https://www.premiumize.me/api/transfer/delete'
link_remove_params = {**{'type': 'torrent'}, **authentification_params}

def main():
    folder_thread = threading.Thread(target=watch_folder_for_magnet_files)
    premiumize_thread = threading.Thread(target=watch_premiumize_links)

    folder_thread.daemon = premiumize_thread.daemon = True
    folder_thread.start()
    premiumize_thread.start()

    while folder_thread.is_alive() and premiumize_thread.is_alive():
        time.sleep(10)


def watch_folder_for_magnet_files():
    while True:
        try:
            file_list = [files for files in os.listdir(os.environ.get('MAGNETFILE_DIR'))
                         if os.path.isfile(os.path.join(os.environ.get('MAGNETFILE_DIR'), files)) and os.path.splitext(files)[1] == '.magnet']

            for file in file_list:
                print("Found magnet file named {0}".format(file))
                with open(os.path.join(os.environ.get('MAGNETFILE_DIR'), file), 'r') as read_file:
                    file_contents = read_file.read()

                add_result = add_magnet_to_premiumize(file_contents)
                if add_result['status'] == 'error':
                    os.rename(os.path.join(os.environ.get('MAGNETFILE_DIR'), file), os.path.join(os.environ.get('MAGNETFILE_DIR'), os.path.splitext(file)[0] + '.fail'))
                    print("Could not add {0} to Premiumize.me".format(file))
                    print(add_result['message'])
                    continue

                os.rename(os.path.join(os.environ.get('MAGNETFILE_DIR'), file), os.path.join(os.environ.get('MAGNETFILE_DIR'), str(add_result.get('id')) + '.dl'))

        except Exception as e:
            print("Unknown error occurred while watching magnet folder")
            print(str(e))

        time.sleep(5)


def watch_premiumize_links():
    while True:
        try:
            link_list = json.loads(requests.get(torrent_list_url, params=torrent_list_params).text or 
                                   "{'status': 'error', 'message': 'Torrent status check returned empty response'}")
            
            if link_list['status'] == 'error':
                print('An error occurred while getting the current links')
                print(link_list['message'])
                continue

            for link in link_list['transfers']:
                if link['status'] == 'finished' and 
                   link['id'] in [os.path.splitext(files)[0] for files in os.listdir(os.environ.get('MAGNETFILE_DIR'))
                                  if os.path.isfile(os.path.join(os.environ.get('MAGNETFILE_DIR'), files)) and os.path.splitext(files)[1] == '.dl']:
                    link_details = get_link_details_from_premiumize(link['hash'])

                    if link_details['status'] == 'error':
                        print("An error occurred while getting the details for {0} (id: {1})".format(link['name'], link['id']))
                        print(link_details['message'])
                        continue

                    link_zip_download = link_details['zip']

                    add_result = add_links_to_jd(torrent_name, links)
                    if add_result['id'] is not None:
                        print("{0} has been successfully added to myJD (id: {1})".format(link['name'], add_result['id']))
                    else:
                        print("{0} could not be added to myJD".format(link['name']))

                    remove_result = remove_link_from_premiumize(link['id'])
                    os.remove(os.path.join(os.environ.get('MAGNETFILE_DIR'), link['id'] + '.dl'))
                    if remove_result['status'] == 'success':
                        print("{0} has been successfully removed from Premiumize.me".format(link['name']))
                    else:
                        print("{0} could not be removed from Premiumize.me".format(link['name']))
                        print(remove_result['message'])

        except Exception as e:
            print("Unknown error occurred while watching Premiumize.me links")
            print(str(e))

        time.sleep(30)
            

def get_myjd_device():    
    my_jdownloader_controller = myjdapi.Myjdapi()
    my_jdownloader_controller.connect(os.environ.get('MYJDOWNLOADER_EMAIL'), os.environ.get('MYJDOWNLOADER_PASSWORD'))
    return my_jdownloader_controller.get_device(os.environ.get('MYJDOWNLOADER_DEVICENAME'))


def add_magnet_to_premiumize(magnet_link):
    return json.loads(requests.post(torrent_upload_url, params={**{'src': magnet_link}, **torrent_upload_params}).text or
           "{'status': 'error', 'message': 'Torrent upload returned empty response'}")


def get_link_details_from_premiumize(link_hash):
    return json.loads(requests.post(link_details_url, params={**{'hash': link_hash}, **link_details_params}).text or
           "{'status': 'error', 'message': 'Link details returned empty response'}")


def remove_link_from_premiumize(link_id):
    return json.loads(requests.get(link_remove_url, params={**{'id': link_id}, **link_remove_params}).text or 
           "{'status': 'error', 'message': 'Link removal returned empty response'}")


def add_links_to_jd(package_name, links):
    return get_myjd_device().linkgrabber.add_links([{"autostart": True, "links": ','.join(links), "packageName": package_name}])
        
        
if __name__ == '__main__':
    sys.exit(main())
