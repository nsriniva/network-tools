#!/usr/bin/python

from pdb import set_trace
from time import sleep
from pyroute2 import IPDB, IPRoute, NetNS
from socket import AF_INET, AF_INET6
from jinja2 import Environment, FileSystemLoader
from csv import DictReader
from optparse import OptionParser
from sys import argv, exit as sys_exit

def gen_nw_addrs(nw_start, nw_count):
    nw_addrs = []
    nw_start_l = nw_start.split(':')
    a = int(nw_start_l[0], base=16)
    b = int(nw_start_l[1], base=16)
    c = int(nw_start_l[2], base=16)
    d = nw_start_l[4]

    nw_addrs.append('{:x}:{:x}:{:x}::{}'.format(a, b, c, d))
    for i in range(nw_count-1):
        nw_addrs.append('{:x}:{:x}:{:x}:{:x}::{}'.format(a, b, c, i+1, d))

    return nw_addrs

class NameSpace(object):
    def __init__(self, gw, rt_intfs, rt_addrs,  nw_start, nw_count, ns_base='cloud', netns_num=0):
        self.rt_intfs = rt_intfs
        self.rt_addrs = rt_addrs
        self.gw = gw
        self.nw_addrs = gen_nw_addrs(nw_start, nw_count)
        print '{} : {}'.format(len(self.nw_addrs), self.nw_addrs)

        self.netns_name = '{}{}'.format(ns_base,netns_num+1)

        self.ping_targets = 'ping_targets.%d'%netns_num

        self.ns = NetNS(self.netns_name)
        self.ipdb = IPDB()
        self.ipdb_ns = IPDB(nl=self.ns)

        self.network_intfs = []
        def_spec = {'dst': 'default', 'family':AF_INET6,
                     'priority':1}
        oif = 0
        for idx,rt_intf in enumerate(self.rt_intfs):
            print self.netns_name, rt_intf, idx
            with self.ipdb.interfaces[rt_intf] as intf:
                intf.net_ns_fd = self.netns_name

            with self.ipdb_ns.interfaces[rt_intf] as intf:
                intf.add_ip('%s/64'%self.rt_addrs[idx])
                intf.up()
                if idx == 0:
                    oif = intf.index
                    print 'oif = %d'%oif

            #def_spec['oif'] = oif
        try:
            print 'Checking for defaultroute %s in %s'%\
                (def_spec, self.netns_name)
            with self.ipdb_ns.routes[def_spec] as rt:
                rt.gateway = self.gw
        except KeyError as error:
            print 'Adding default route'
            def_spec['gateway'] = self.gw
            self.ipdb_ns.routes.add(def_spec).commit()

        self.create_networks()
        self.create_ping_targets()
        
    def __del__(self):
        print 'In __del__ for NameSpace %s'%self.netns_name
        self.ipdb.release()
        if self.ns is not None:
            self.ipdb_ns.release()

    def cleanup(self):
        for rt_intf in self.rt_intfs:
            with self.ipdb_ns.interfaces[rt_intf] as intf:
                intf.net_ns_fd = None

        if self.ns is not None:
            self.ns.close()
            self.ns.remove()

    def create_ping_targets(self):
        ping_addrs = [nw_addr.split('/')[0] for nw_addr in self.nw_addrs]
        with open(self.ping_targets, 'w') as fd:
            fd.write('\n'.join(ping_addrs))
            fd.write('\n')

    def create_networks(self):
        print '{} : {}'.format(len(self.nw_addrs), self.nw_addrs)
        for idx in range(len(self.nw_addrs)):
            if_name = 'veth%d_%s'%(idx, self.netns_name)
            # max if name len is 15 - so the peer interface suffix is '_p' 
            ret = self.ipdb_ns.create(ifname=if_name, peer='_'.join([if_name, 'p']), kind='veth')
            print '{} {}'.format(if_name, ret)

        self.ipdb_ns.commit()

        for idx, addr in enumerate(self.nw_addrs):
            if_name = 'veth%d_%s'%(idx, self.netns_name)
            print if_name, addr
 
            with self.ipdb_ns.interfaces[if_name] as veth:
                veth.add_ip(addr)
            with self.ipdb_ns.interfaces[if_name] as veth:
                veth.up()
            self.network_intfs.append(if_name)
            if_name = '_'.join([if_name, 'p'])
            print 'Bringing up %s'%if_name
            with self.ipdb_ns.interfaces[if_name] as intf:
                intf.up()
        self.ipdb_ns.commit()


class XRConfigGen(object):
    def __init__(self):
        self.env = Environment(loader=FileSystemLoader('.'))
        self.intf_tmpl = self.env.get_template('intf_cfg.tmpl')
        self.no_intf_tmpl = self.env.get_template('no_intf_cfg.tmpl')
        self.rt_tmpl = self.env.get_template('rt_cfg.tmpl')
        self.no_rt_tmpl = self.env.get_template('no_rt_cfg.tmpl')
        self.intf_cfg = None
        self.no_intf_cfg = None
        self.rt_cfg = {}
        self.no_rt_cfg = {}

    def gen_intf(self):
        with open('intf.xr') as fd:
            intfs = [intf for intf in DictReader(fd, skipinitialspace=True, delimiter=' ')]
            self.intf_cfg = self.intf_tmpl.render(intfs=intfs)
            self.no_intf_cfg = self.no_intf_tmpl.render(intfs=intfs)
        with open('xr_intf.cfg','w') as fd:
            fd.write(self.intf_cfg)
        with open('no_xr_intf.cfg','w') as fd:
            fd.write(self.no_intf_cfg)

    def gen_rt(self, num_ns):
        with open('route.xr') as fd:
            routes = [route for route in DictReader(fd, skipinitialspace=True, delimiter=' ')]
            rt_cfg = ""
            no_rt_cfg = ""
            for route in routes:
                nw_start = route['networks']
                nw_count = int(route['count'])
                next_hop = route['next_hop']
                nw_routes = gen_nw_addrs(nw_start, nw_count)
                rt_cfg += self.rt_tmpl.render(nw_routes=nw_routes, next_hop=next_hop)
                no_rt_cfg += self.no_rt_tmpl.render(nw_routes=nw_routes, next_hop=next_hop)


        with open('xr_route.cfg','w') as fd:
            fd.write(rt_cfg)
        with open('no_xr_route.cfg','w') as fd:
            fd.write(no_rt_cfg)

                            
    

def main(prog, args):

    ns_base = 'cloud'
    if len(args):
        ns_base = args[0]
    name_spaces = {}
    num_ns = 2
    for ns in range(num_ns):
        rt_intfs = []
        rt_addrs = []
        with open('intf_%s.dpd'%ns) as fd:
            intfs = DictReader(fd, skipinitialspace=True, delimiter=' ')
            for intf in intfs:
		rt_intfs.append(intf['name'])
		rt_addrs.append(intf['ipaddr'])
        with open('network_%s.dpd'%ns) as fd:
            networks = fd.read().split()
        gw = networks[0]
        nw_start = networks[1]
        nw_count = int(networks[2])
        
        name_spaces[ns] = NameSpace(gw, rt_intfs, rt_addrs, nw_start, nw_count, ns_base, ns)

    xr_config_gen = XRConfigGen()
    xr_config_gen.gen_intf()
    xr_config_gen.gen_rt(num_ns)

if __name__ == "__main__":
    main(argv[0], argv[1:])
