#!/usr/bin/python

from pdb import set_trace
from typing import Dict, Tuple, Optional
from time import sleep
from pyroute2 import IPDB, IPRoute, NetNS, NDB
from pyroute2.ndb.objects.interface import Interface 
from socket import AF_INET, AF_INET6
#from jinja2 import Environment, FileSystemLoader
from csv import DictReader
from optparse import OptionParser
from ipaddress import ip_network
from sys import argv, exit as sys_exit


class VMNet(dict):

    def __init__(self, fname:str = 'vmnet.dat'):
        dict.__init__(self)
        self.fname : str = fname
        self.load_vmnet_info(self.fname)
        self.ndb = NDB()
        self.vmnets:Dict[int, Tuple[str, Interface, str, Optional[Interface]]] = {}

    def load_vmnet_info(self, fname:str='vmnet.dat'):

        with open(fname) as fd:
            vmnets = DictReader(fd, fieldnames=['vmnet','subnet'],delimiter=' ')
            vm_sub = []
            for vm in vmnets:
                for _,v in vm.items():
                    vm_sub.append(v)
                self[int(vm_sub[0])] = ip_network(vm_sub[1])
                del vm_sub[:]

    
    def find_vmnet(self, ip_addr:str) -> int:

        try:
            ip_net = ip_network(ip_addr)
            for vmnet, subnet in self.items():
                if subnet.supernet_of(ip_net):
                    return vmnet
        except Exception as e:
            print(e)

        return -1

    def find_vmnets(self):

        def create_bridge(bname:str) ->Interface:
            if self.ndb.interfaces.get(bname) is not None:
                self.ndb.interfaces[bname].remove().commit()

            vmbr =  self.ndb\
                        .interfaces\
                        .create(ifname=bname,
                                kind='bridge')
            vmbr.commit()
            return vmbr

        for iface in self.ndb.addresses.summary():
            iface = tuple(iface)
            iname = iface[2]
            iaddr = iface[3]
            intf  = self.ndb.interfaces[iname]
            
            vmnet = self.find_vmnet(iaddr)
            if vmnet != -1:
                self.vmnets[vmnet] = (iname, intf, iaddr, create_bridge( f'vmnet{vmnet}br'))


    def attach_bridges(self):

        for _, vmnet in self.vmnets:
            # shutdown intf
            vmnet[1].set('state','down')\
                    .del_ip(vmnet[2])\
                    .set('state','up')\
                    .set('master', vmnet[3]['index'])\
                    .commit()

            vmnet[3].add_ip(vmnet[2])\
                    .set('state','up')\
                    .commit()
            
            
