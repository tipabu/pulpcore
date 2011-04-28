#!/usr/bin/python
#
# Copyright (c) 2010 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public License,
# version 2 (GPLv2). There is NO WARRANTY for this software, express or
# implied, including the implied warranties of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. You should have received a copy of GPLv2
# along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
#
# Red Hat trademarks are not licensed under GPLv2. No permission is
# granted to use or replicate Red Hat trademarks that are incorporated
# in this software or its documentation.

'''
Utilities for parsing and formatting of JSON values.
'''

import time
from datetime import datetime

ISOFORMAT = '%Y-%m-%dT%H:%M:%S'

def parse_date(date_string):
    '''
    Parses a unix timestamp string. Valid dates generated on the server should
    be created with:

    datetime.now().strftime("%s")

    @param date_string: unix timestamp string
    @type  date_string: str

    @return: python object representing the date
    @rtype:  L{datetime.datetime} instance
    '''
    return datetime.utcfromtimestamp(float(date_string))


def parse_iso_date(iso_str):
    """
    Parse an ISO-8601 formatted date string.
    @param iso_str: An ISO-8601 date string.
    @type iso_str: str
    @return: python object representing the date
    @rtype:  L{datetime.datetime} instance 
    """
    return datetime(*(time.strptime(iso_str[:19], ISOFORMAT)[0:6]))
