#!/usr/bin/python

from pdb import set_trace
from json import dump, load
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

VMNET_INTF_FILE = 'vmnet_intf.json'

class VMNet(dict):

    def __init__(self, fname:str = 'vmnet.dat'):
        dict.__init__(self)
        self.fname : str = fname
        self.load_vmnet_info(self.fname)
        self.ndb = NDB()
        self.ipr = IPRoute()
        self.vmnets:Optional[Dict[int, Tuple[str, str, int, str, str]]] = None

    def load_vmnet_info(self, fname:str='vmnet.dat'):

        with open(fname) as fd:
            vmnets = DictReader(fd, fieldnames=['vmnet','subnet'],delimiter=' ')
            vm_sub = []
            for vm in vmnets:
                for _,v in vm.items():
                    vm_sub.append(v)
                self[int(vm_sub[0])] = ip_network(vm_sub[1])
                del vm_sub[:]

    
    def find_vmnet(self, ip_addr:str) -> Tuple[int, int, str]:

        try:
            ip_net = ip_network(ip_addr)
            for vmnet, subnet in self.items():
                if subnet.supernet_of(ip_net):
                    return vmnet, subnet.prefixlen, str(subnet.broadcast_address)
        except Exception as e:
            print(e)

        return -1,-1,''

    def find_vmnets(self):
        
        if self.vmnets is None:
            self.vmnets = {}
            
        for iface in self.ndb.addresses.summary():
            iface = tuple(iface)
            iname = iface[2]
            iaddr = iface[3]
            intf  = self.ndb.interfaces[iname]
            
            vmnet,prefixlen, bcast_addr = self.find_vmnet(iaddr)
            print(vmnet, prefixlen, bcast_addr)
            if vmnet != -1:
                
                self.vmnets[vmnet] = (iname, iaddr, prefixlen, bcast_addr,f'bridge{vmnet}')


    def attach_bridges(self):
        def create_bridge(bname:str) ->Interface:
            if self.ndb.interfaces.get(bname) is not None:
                self.ndb.interfaces[bname].remove().commit()

            vmbr =  self.ndb\
                        .interfaces\
                        .create(ifname=bname,
                                kind='bridge')\
                        .commit()

            return vmbr

        for _, vmnet in self.vmnets.items():
            # shutdown intf
            self.ndb.interfaces[vmnet[0]].set('state','down')\
                                         .del_ip(f'{vmnet[1]}/{vmnet[2]}')\
                                         .set('state','up')\
                                         .commit()

            br = create_bridge(vmnet[4])
            br.add_port(vmnet[0])\
                    .commit()

            self.ipr.addr('add', index=br['index'],
                          address=vmnet[1], mask=vmnet[2], broadcast=vmnet[3])


            self.ipr.link('set', index=br['index'], state='up')

        with open(VMNET_INTF_FILE, 'w') as fd:
            dump(self.vmnets, fd)
            
    def detach_bridges(self):

        if self.vmnets is None:
            with open(VMNET_INTF_FILE) as fd:
                self.vmnets = load(fd)
                
        for _, vmnet in self.vmnets.items():
            self.ndb.interfaces[vmnet[4]].remove().commit()

            intf = self.ndb.interfaces[vmnet[0]]
            # shutdown intf
            intf.set('state','down')\
                    .commit()


            self.ipr.addr('add', index=intf['index'],
                          address=vmnet[1], mask=vmnet[2], broadcast=vmnet[3])


            self.ipr.link('set', index=intf['index'], state='up')
