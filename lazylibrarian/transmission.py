#  This file is part of LazyLibrarian.
#
#  LazyLibrarian is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  LazyLibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with LazyLibrarian.  If not, see <http://www.gnu.org/licenses/>.

import json
import time
import urlparse

import lazylibrarian
from lazylibrarian import logger, request


# This is just a simple script to send torrents to transmission. The
# intention is to turn this into a class where we can check the state
# of the download, set the download dir, etc.
# TODO: Store the session id so we don't need to make 2 calls
#       Store torrent id so we can check up on it


def addTorrent(link, directory=None):
    method = 'torrent-add'
    # print type(link), link
    # if link.endswith('.torrent'):
    #    with open(link, 'rb') as f:
    #        metainfo = str(base64.b64encode(f.read()))
    #    arguments = {'metainfo': metainfo }
    # else:
    if directory is None:
        directory = lazylibrarian.DIRECTORY('Download')
    arguments = {'filename': link, 'download-dir': directory}

    response = torrentAction(method, arguments)

    if not response:
        return False

    if response['result'] == 'success':
        if 'torrent-added' in response['arguments']:
            retid = response['arguments']['torrent-added']['id']
        elif 'torrent-duplicate' in response['arguments']:
            retid = response['arguments']['torrent-duplicate']['id']
        else:
            retid = False

        logger.debug(u"Torrent sent to Transmission successfully")
        return retid

    else:
        logger.debug('Transmission returned status %s' % response['result'])
        return False


def getTorrentFolder(torrentid):  # uses hashid
    method = 'torrent-get'
    arguments = {'ids': [torrentid], 'fields': ['name', 'percentDone']}
    retries = 3
    while retries:
        response = torrentAction(method, arguments)
        if response and len(response['arguments']['torrents']):
            percentdone = response['arguments']['torrents'][0]['percentDone']
            if percentdone:
                return response['arguments']['torrents'][0]['name']
        else:
            logger.debug('getTorrentFolder: No response from transmission')
            return ''

        retries -= 1
        if retries:
            time.sleep(5)

    return ''


def getTorrentFolderbyID(torrentid):  # uses transmission id
    method = 'torrent-get'
    arguments = {'fields': ['name', 'percentDone', 'id']}
    retries = 3
    while retries:
        response = torrentAction(method, arguments)
        if response and len(response['arguments']['torrents']):
            tor = 0
            while tor < len(response['arguments']['torrents']):
                percentdone = response['arguments']['torrents'][tor]['percentDone']
                if percentdone:
                    torid = response['arguments']['torrents'][tor]['id']
                    if str(torid) == str(torrentid):
                        return response['arguments']['torrents'][tor]['name']
                tor += 1
        else:
            logger.debug('getTorrentFolder: No response from transmission')
            return ''

        retries -= 1
        if retries:
            time.sleep(5)

    return ''


def setSeedRatio(torrentid, ratio):
    method = 'torrent-set'
    if ratio != 0:
        arguments = {'seedRatioLimit': ratio, 'seedRatioMode': 1, 'ids': [torrentid]}
    else:
        arguments = {'seedRatioMode': 2, 'ids': [torrentid]}

    response = torrentAction(method, arguments)
    if not response:
        return False


def removeTorrent(torrentid, remove_data=False):

    method = 'torrent-get'
    arguments = {'ids': [torrentid], 'fields': ['isFinished', 'name']}

    response = torrentAction(method, arguments)
    if not response:
        return False

    try:
        finished = response['arguments']['torrents'][0]['isFinished']
        name = response['arguments']['torrents'][0]['name']

        if finished:
            logger.debug('%s has finished seeding, removing torrent and data' % name)
            method = 'torrent-remove'
            if remove_data:
                arguments = {'delete-local-data': True, 'ids': [torrentid]}
            else:
                arguments = {'ids': [torrentid]}
            response = torrentAction(method, arguments)
            return True
        else:
            logger.debug('%s has not finished seeding yet, torrent will not be removed, \
                        will try again on next run' % name)
    except Exception as e:
        logger.debug('Unable to remove torrent %s, %s' % (torrentid, str(e)))
        return False

    return False


def checkLink():

    method = 'session-stats'
    arguments = {}

    response = torrentAction(method, arguments)
    if response:
        if response['result'] == 'success':
            # does transmission handle labels?
            return "Transmission login successful"
    return "Transmission login FAILED\nCheck debug log"


def torrentAction(method, arguments):

    host = lazylibrarian.TRANSMISSION_HOST
    port = lazylibrarian.TRANSMISSION_PORT
    username = lazylibrarian.TRANSMISSION_USER
    password = lazylibrarian.TRANSMISSION_PASS

    if not host.startswith('http'):
        host = 'http://' + host

    if host.endswith('/'):
        host = host[:-1]

    # Fix the URL. We assume that the user does not point to the RPC endpoint,
    # so add it if it is missing.
    parts = list(urlparse.urlparse(host))

    if parts[0] not in ("http", "https"):
        parts[0] = "http"

    if ':' not in parts[1]:
        parts[1] += ":%s" % port

    if not parts[2].endswith("/rpc"):
        parts[2] += "/transmission/rpc"

    host = urlparse.urlunparse(parts)

    # Retrieve session id
    auth = (username, password) if username and password else None
    response = request.request_response(host, auth=auth,
                                        whitelist_status_code=[401, 409])

    if response is None:
        logger.error("Error getting Transmission session ID")
        return

    # Parse response
    session_id = ''
    if response.status_code == 401:
        if auth:
            logger.error("Username and/or password not accepted by "
                         "Transmission")
        else:
            logger.error("Transmission authorization required")
        return
    elif response.status_code == 409:
        session_id = response.headers['x-transmission-session-id']

    if not session_id:
        logger.error("Expected a Session ID from Transmission")
        return

    # Prepare next request
    headers = {'x-transmission-session-id': session_id}
    data = {'method': method, 'arguments': arguments}

    try:
        response = request.request_json(host, method="POST", data=json.dumps(data),
                                        headers=headers, auth=auth)
    except Exception as e:
        logger.debug('Transmission error %s' % str(e))
        response = ''

    if not response:
        logger.error("Error sending torrent to Transmission")
        return

    return response
