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
        self.ipr = IPRoute()
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
                    return vmnet, subnet.prefixlen, str(subnet.broadcast_address)
        except Exception as e:
            print(e)

        return -1,-1,''

    def find_vmnets(self):

        def create_bridge(bname:str) ->Interface:
            if self.ndb.interfaces.get(bname) is not None:
                self.ndb.interfaces[bname].remove().commit()

            vmbr =  self.ndb\
                        .interfaces\
                        .create(ifname=bname,
                                kind='bridge')\
                        .commit()

            return vmbr

        for iface in self.ndb.addresses.summary():
            iface = tuple(iface)
            iname = iface[2]
            iaddr = iface[3]
            intf  = self.ndb.interfaces[iname]
            
            vmnet,prefixlen, bcast_addr = self.find_vmnet(iaddr)
            print(vmnet, prefixlen, bcast_addr)
            if vmnet != -1:
                self.vmnets[vmnet] = (iname, intf, iaddr, prefixlen, bcast_addr,create_bridge( f'vmnet{vmnet}br'))


    def attach_bridges(self):

        for _, vmnet in self.vmnets.items():
            # shutdown intf
            vmnet[1].set('state','down')\
                    .del_ip(f'{vmnet[2]}/{vmnet[3]}')\
                    .set('state','up')\
                    .commit()

            vmnet[5].add_port(vmnet[0])\
                    .commit()

            self.ipr.addr('add', index=vmnet[5]['index'],
                          address=vmnet[2], mask=vmnet[3], broadcast=vmnet[4])


            self.ipr.link('set', index=vmnet[5]['index'], state='up')

    def detach_bridges(self):

        for _, vmnet in self.vmnets.items():
            vmnet[5].remove().commit()
            
            # shutdown intf
            vmnet[1].set('state','down')\
                    .commit()


            self.ipr.addr('add', index=vmnet[1]['index'],
                          address=vmnet[2], mask=vmnet[3], broadcast=vmnet[4])


            self.ipr.link('set', index=vmnet[1]['index'], state='up')
