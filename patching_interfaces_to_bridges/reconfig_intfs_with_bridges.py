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
        self.ipdb = ()
        self.vmnets:Dict[int, Tuple[str, str, Optional[Interface]]] = {}

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

        for intf in self.ndb.addresses.summary():
            intf = tuple(intf)
            iname = intf[2]
            iaddr = intf[3]

            vmnet = self.find_vmnet(iaddr)
            if vmnet != -1:
                self.vmnets[vmnet] = (iname, iaddr, f'vmnet{vmnet}br', None)

            
    def activate_bridges(self):

        def create_bridge(bname:str) ->Interface:
            vmbr =  self.ndb\
                        .interfaces\
                        .create(ifname=bname,
                                kind='bridge')
            vmbr.commit()
            return vmbr

        for k,v in self.vmnets.items():
            self.vmnets[k] = (v[0],v[1],v[2],create_bridge(v[2]))
            
            
