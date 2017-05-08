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
        exit(1)

# Premiumize.me API variables
authentification_params = {'customer_id': os.environ.get('PREMIUMIZE_CUSTOMER_ID'), 'pin': os.environ.get('PREMIUMIZE_PIN')}
torrent_upload_url = 'https://www.premiumize.me/api/transfer/create'
torrent_upload_params = {**{'type': 'torrent'}, **authentification_params}
account_info_url = 'https://www.premiumize.me/api/account/info'
account_info_params = authentification_params
link_list_url = 'https://www.premiumize.me/api/transfer/list'
link_list_params = authentification_params
link_details_url = 'https://www.premiumize.me/api/torrent/browse'
link_details_params = authentification_params
link_remove_url = 'https://www.premiumize.me/api/transfer/delete'
link_remove_params = {**{'type': 'torrent'}, **authentification_params}

def main():
    account_thread = threading.Thread(target=watch_account_info)
    folder_thread = threading.Thread(target=watch_folder_for_magnet_files)
    premiumize_thread = threading.Thread(target=watch_premiumize_links)

    account_thread.daemon = folder_thread.daemon = premiumize_thread.daemon = True
    account_thread.start()
    folder_thread.start()
    premiumize_thread.start()

    while account_thread.is_alive() and folder_thread.is_alive() and premiumize_thread.is_alive():
        time.sleep(5)


def watch_account_info():
    while True:
        try:
            account_info = premiumize_get_account_info()

            if account_info['status'] == 'error':
                print('An error occurred while getting account info')
                print(account_info['message'])
                exit(2)

            if account_info['premium_until'] < time.time():
                print('Your premium status has expired')
                exit(3)

            if account_info['limit_used'] > 1.0:
                print('You are over the fair use limit')
                exit(4)

        except Exception as e:
            print("Unknown error occurred while watching account info")
            print(str(e))
            exit(5)

        time.sleep(30)

def watch_folder_for_magnet_files():
    while True:
        try:
            file_list = [files for files in os.listdir(os.environ.get('MAGNETFILE_DIR'))
                         if os.path.isfile(os.path.join(os.environ.get('MAGNETFILE_DIR'), files)) and os.path.splitext(files)[1] == '.magnet']

            for file in file_list:
                print("Found magnet file named {0}".format(file))
                with open(os.path.join(os.environ.get('MAGNETFILE_DIR'), file), 'r') as read_file:
                    file_contents = read_file.read()

                add_result = premiumize_add_magnet(file_contents)
                if add_result['status'] == 'error':
                    os.rename(os.path.join(os.environ.get('MAGNETFILE_DIR'), file), os.path.join(os.environ.get('MAGNETFILE_DIR'), os.path.splitext(file)[0] + '.fail'))
                    print("Could not add {0} to Premiumize.me".format(file))
                    print(add_result['message'])
                    continue

                print("Successfully added {0} to Premiumize.me".format(add_result['name']))
                os.rename(os.path.join(os.environ.get('MAGNETFILE_DIR'), file), os.path.join(os.environ.get('MAGNETFILE_DIR'), add_result['id'] + '.dl'))

        except Exception as e:
            print("Unknown error occurred while watching magnet folder")
            print(str(e))

        time.sleep(5)


def watch_premiumize_links():
    while True:
        try:
            link_list = json.loads(requests.get(link_list_url, params=link_list_params).text or 
                                   "{'status': 'error', 'message': 'Torrent status check returned empty response'}")
            
            if link_list['status'] == 'error':
                print('An error occurred while getting the current links')
                print(link_list['message'])
                continue

            for link in link_list['transfers']:
                if link['status'] == 'finished' and \
                   link['id'] in [os.path.splitext(files)[0] for files in os.listdir(os.environ.get('MAGNETFILE_DIR'))
                                  if os.path.isfile(os.path.join(os.environ.get('MAGNETFILE_DIR'), files)) and os.path.splitext(files)[1] == '.dl']:
                    link_details = premiumize_get_link_details(link['hash'])

                    if link_details['status'] == 'error':
                        print("An error occurred while getting the details for {0} (id: {1})".format(link['name'], link['id']))
                        print(link_details['message'])
                        continue

                    link_zip_download = link_details['zip']

                    add_result = jd_add_links(link['name'], [link_zip_download])
                    if add_result['id'] is not None:
                        print("{0} has been successfully added to myJD (id: {1})".format(link['name'], add_result['id']))
                    else:
                        print("{0} could not be added to myJD".format(link['name']))

                    remove_result = premiumize_remove_link(link['id'])
                    if remove_result['status'] == 'success':
                        print("{0} has been successfully removed from Premiumize.me".format(link['name']))
                        os.remove(os.path.join(os.environ.get('MAGNETFILE_DIR'), link['id'] + '.dl'))
                    else:
                        print("{0} could not be removed from Premiumize.me".format(link['name']))
                        print(remove_result['message'])
                        os.rename(os.path.join(os.environ.get('MAGNETFILE_DIR'), link['id'] + '.dl'), os.path.join(os.environ.get('MAGNETFILE_DIR'), link['id'] + '.noremove'))

        except Exception as e:
            print("Unknown error occurred while watching Premiumize.me links")
            print(str(e))

        time.sleep(15)
            

def get_myjd_device():    
    my_jdownloader_controller = myjdapi.Myjdapi()
    my_jdownloader_controller.connect(os.environ.get('MYJDOWNLOADER_EMAIL'), os.environ.get('MYJDOWNLOADER_PASSWORD'))
    return my_jdownloader_controller.get_device(os.environ.get('MYJDOWNLOADER_DEVICENAME'))


def premiumize_add_magnet(magnet_link):
    return json.loads(requests.post(torrent_upload_url, params={**{'src': magnet_link}, **torrent_upload_params}).text or
           "{'status': 'error', 'message': 'Torrent upload returned empty response'}")


def premiumize_get_link_details(link_hash):
    return json.loads(requests.post(link_details_url, params={**{'hash': link_hash}, **link_details_params}).text or
           "{'status': 'error', 'message': 'Link details returned empty response'}")


def premiumize_remove_link(link_id):
    return json.loads(requests.get(link_remove_url, params={**{'id': link_id}, **link_remove_params}).text or 
           "{'status': 'error', 'message': 'Link removal returned empty response'}")


def premiumize_get_account_info():
    return json.loads(requests.get(account_info_url, params=account_info_params).text or 
           "{'status': 'error', 'message': 'Account info returned empty response'}")


def jd_add_links(package_name, links):
    return get_myjd_device().linkgrabber.add_links([{"autostart": True, "links": ','.join(links), "packageName": package_name}])


if __name__ == '__main__':
    sys.exit(main())
