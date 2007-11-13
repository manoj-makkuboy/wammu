# -*- coding: UTF-8 -*-
# vim: expandtab sw=4 ts=4 sts=4:
'''
Wammu - Phone manager
Searching for phone
'''
__author__ = 'Michal Čihař'
__email__ = 'michal@cihar.com'
__license__ = '''
Copyright (c) 2003 - 2007 Michal Čihař

This program is free software; you can redistribute it and/or modify it
under the terms of the GNU General Public License version 2 as published by
the Free Software Foundation.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
more details.

You should have received a copy of the GNU General Public License along with
this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
'''

import wx
import threading
import os
import os.path
import sys
try:
    import grp
    HAVE_GRP = True
except ImportError:
    HAVE_GRP = False
import Wammu
if Wammu.gammu_error == None:
    import gammu
import Wammu.Data
import Wammu.Events
import wx.lib.layoutf
from Wammu.Locales import StrConv

try:
    import bluetooth
    import Wammu.BluezDiscovery
    BLUETOOTH = 'bluez'
except ImportError:
    try:
        import btctl
        BLUETOOTH = 'btctl'
    except ImportError:
        BLUETOOTH = None

class AllSearchThread(threading.Thread):
    '''
    Root thread for phone searching. It spawns other threads for testing each
    device.
    '''
    def __init__(self,
            lock = 'no',
            level = 'nothing',
            msgcallback = None,
            callback = None,
            win = None,
            noticecallback = None,
            limit = None):
        threading.Thread.__init__(self)
        self.lock = lock
        self.list = []
        self.win = win
        self.listlock = threading.Lock()
        self.level = level
        self.threads = []
        self.callback = callback
        self.msgcallback = msgcallback
        self.noticecallback = noticecallback
        self.limit = limit

    def create_search_thread(self, device, connections, name):
        '''
        Creates single thread for searching phone on device using listed
        connections. Name is just text which will be shown to user.
        '''
        newthread = SearchThread(
                device,
                connections,
                self.list,
                self.listlock,
                self.lock,
                self.level)
        newthread.setName(name)
        if self.msgcallback != None:
            self.msgcallback(
                    _('Checking %s') %
                    StrConv(name)
                    )
        self.threads.append(newthread)
        newthread.start()

    def search_bt_device(self, address, name):
        '''
        Searches single bluetooth device.
        '''
        connections = Wammu.Data.Conn_Bluetooth_All
        vendorguess = _('Could not guess vendor')
        # Use better connection list for some known manufacturers
        for vendor in Wammu.Data.MAC_Prefixes.keys():
            if address[:8].upper() in Wammu.Data.MAC_Prefixes[vendor]:
                connections = Wammu.Data.Conn_Bluetooth[vendor]
                vendorguess = _('Guessed as %s') % vendor

        self.create_search_thread(
                address,
                connections,
                '%s (%s) - %s - %s' % (
                    address,
                    name,
                    vendorguess,
                    str(connections)))

    def check_device(self, curdev):
        '''
        Checks whether it makes sense to perform searching on this device and
        possibly warns user about misconfigurations.
        '''
        if not os.path.exists(curdev):
            return False
        if not os.access(curdev, os.R_OK) or not os.access(curdev, os.W_OK):
            gid =  os.stat(curdev).st_gid
            if HAVE_GRP:
                group = grp.getgrgid(gid)[0]
            else:
                group = str(gid)
            if self.msgcallback != None:
                self.msgcallback(
                        _('You don\'t have permissions for %s device!') %
                        curdev)
            if self.noticecallback != None:
                self.noticecallback(
                        _('Error opening device'),
                        (_('You don\'t have permissions for %s device!') %
                            curdev) +
                        ' ' +
                        (_('Maybe you need to be member of %s group.') %
                            group))
        return True

    def search_device(self, curdev, dev):
        '''
        Performs search on one real device.
        '''
        if len(curdev) > 0 and curdev[0] == '/':
            if not self.check_device(curdev):
                return

        self.create_search_thread(
                curdev,
                dev[0],
                '%s - %s' % (curdev, str(dev[0])))

    def listed_device_search(self):
        '''
        Initiates searching of devices defined in Wammu.Data.AllDevices.
        '''
        for dev in Wammu.Data.AllDevices:
            if not (self.limit == 'all' or self.limit in dev[3]):
                continue
            if dev[1].find('%d') >= 0:
                for i in range(*dev[2]):
                    curdev = dev[1] % i
                    self.search_device(curdev, dev)
            else:
                self.search_device(dev[1], dev)

    def bluetooth_device_search_bluez(self):
        '''
        Initiates searching for Bluetooth devices using PyBluez stack.
        '''
        # read devices list
        if self.msgcallback != None:
            self.msgcallback(_('Scanning for bluetooth devices using %s') %
                    'PyBluez')

        try:
            discovery = Wammu.BluezDiscovery.Discovery(self)
            discovery.find_devices()
            discovery.process_inquiry()
            if len(discovery.names_found) == 0 and self.msgcallback != None:
                self.msgcallback(_('No bluetooth device found'))
            if self.msgcallback != None:
                self.msgcallback(_('Bluetooth device scan completed'))
        except bluetooth.BluetoothError, txt:
            if self.msgcallback != None:
                self.msgcallback(
                        _('Could not access Bluetooth subsystem (%s)') %
                        StrConv(txt))

    def bluetooth_device_search_btctl(self):
        '''
        Initiates searching for Bluetooth devices using btctl stack.
        '''
        # read devices list
        if self.msgcallback != None:
            self.msgcallback(_('Scanning for bluetooth devices using %s') %
                    'GNOME Bluetooth (btctl)')

        # create controller object
        try:
            ctl = btctl.Controller('')
        except TypeError:
            ctl = btctl.Controller()

        devs = ctl.discover_devices()

        if devs == None or len(devs) == 0:
            if self.msgcallback != None:
                self.msgcallback(_('No bluetooth device found'))
        else:
            for dev in devs:
                self.search_bt_device(
                        dev['bdaddr'],
                        ctl.get_device_preferred_name(dev['bdaddr']))
        if self.msgcallback != None:
            self.msgcallback(_('Bluetooth device scan completed'))

    def bluetooth_device_search(self):
        '''
        Initiates searching for Bluetooth devices.
        '''
        if not self.limit in ['all', 'bluetooth']:
            return
        if BLUETOOTH == 'bluez':
            self.bluetooth_device_search_bluez()
        elif BLUETOOTH == 'btctl':
            self.bluetooth_device_search_btctl()
        else:
            if self.msgcallback != None:
                self.msgcallback(_('Neither GNOME Bluetooth (btctl) nor PyBluez found, not possible to scan for bluetooth devices'))
            if self.noticecallback != None:
                self.noticecallback(
                        _('No bluetooth searching'),
                        _('Neither GNOME Bluetooth (btctl) nor PyBluez found, not possible to scan for bluetooth devices'))

    def run(self):
        try:
            self.listed_device_search()
            self.bluetooth_device_search()

            i = 0
            while len(self.threads) > 0:
                if self.threads[i].isAlive():
                    i += 1
                else:
                    if self.msgcallback != None:
                        self.msgcallback(_('Finished %s') %
                                StrConv(self.threads[i].getName()))
                    del self.threads[i]
                if i >= len(self.threads):
                    i = 0
            if self.msgcallback != None:
                self.msgcallback(_('All finished, found %d phones') %
                        len(self.list))
            if self.callback != None:
                self.callback(self.list)
        except:
            evt = Wammu.Events.ExceptionEvent(data = sys.exc_info())
            wx.PostEvent(self.win, evt)

class SearchThread(threading.Thread):
    def __init__(self,
            device,
            connections,
            lst,
            listlock,
            lock = 'no',
            level = 'nothing',
            win = None):
        threading.Thread.__init__(self)
        self.device = device
        self.connections = connections
        self.lock = lock
        self.win = win
        self.level = level
        self.list = lst
        self.listlock = listlock

    def try_connection(self, connection):
        '''
        Performs test on single connection.
        '''
        gsm = gammu.StateMachine()
        gsm.SetConfig(0,
                {'StartInfo': 'no',
                 'UseGlobalDebugFile': 1,
                 'DebugFile': '',
                 'SyncTime': 'no',
                 'Connection': connection,
                 'LockDevice': self.lock,
                 'DebugLevel': self.level,
                 'Device': self.device,
                 'Localize': None,
                 'Model': ''})
        try:
            if self.level == 'textall':
                print 'Trying at %s using %s' % (self.device, connection)
            gsm.Init()
            self.listlock.acquire()
            self.list.append((
                self.device,
                connection,
                gsm.GetModel(),
                gsm.GetManufacturer()
                ))
            self.listlock.release()
            if self.level != 'nothing':
                print '!!Found model %s at %s using %s' % (
                        gsm.GetModel(),
                        self.device,
                        connection)
            return
        except gammu.GSMError:
            if self.level == 'textall':
                print 'Failed at %s using %s' % (self.device, connection)

    def run(self):
        '''
        Tests all listed connections.
        '''
        try:
            for conn in self.connections:
                self.try_connection(conn)
        except:
            evt = Wammu.Events.ExceptionEvent(data = sys.exc_info())
            wx.PostEvent(self.win, evt)

class PhoneInfoThread(threading.Thread):
    def __init__(self, win, device, connection):
        threading.Thread.__init__(self)
        self.device = device
        self.connection = connection
        self.result = None
        self.win = win

    def run(self):
        try:
            sm = gammu.StateMachine()
            sm.SetConfig(0,
                    {'StartInfo': 'no',
                     'UseGlobalDebugFile': 1,
                     'DebugFile': '',
                     'SyncTime': 'no',
                     'Connection': self.connection,
                     'LockDevice': 'no',
                     'DebugLevel': 'nothing',
                     'Device': self.device,
                     'Localize': None,
                     'Model': '',
                     })
            sm.Init()
            self.result = {
                    'Model': sm.GetModel(),
                    'Manufacturer': sm.GetManufacturer(),
                    }
            evt = Wammu.Events.DataEvent(data = self.result)
            wx.PostEvent(self.win, evt)
        except gammu.GSMError:
            evt = Wammu.Events.DataEvent(data = None)
            wx.PostEvent(self.win, evt)
