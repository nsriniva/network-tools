#!/usr/bin/env python
from pyroute2 import NDB
from pyroute2 import IPRoute

            
ndb = NDB()
ipr = IPRoute()

bris = ['vmnet2br','vmnet3br']
ifaces = ['ens37', 'ens38']
addrs = [('172.16.143.128',24,'172.16.143.255'), ('172.16.205.128',24,'172.16.205.255')]

bri_intf = [ ndb.interfaces[b] for b in bris if ndb.interfaces.get(b) is not None]
intf = [ ndb.interfaces[b] for b in ifaces if ndb.interfaces.get(b) is not None]

for i in bri_intf:
    i.remove().commit()
    
    
for idx,i in enumerate(intf):
    i.set('state','down').commit()
    addr = addrs[idx]
    ipr.addr('add', index=i['index'], address = addr[0], mask = addr[1], broadcast=addr[2])
         
    ipr.link('set', index=i['index'], state='up')
         
