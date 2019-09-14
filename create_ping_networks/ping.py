#!/usr/bin/python
from sh import ip, fping, fping6, wc
from sys import stdout, argv
from psycopg2 import connect
from sys import stdout
from threading import Thread


class PostgresInterface(object):
    def __init__(self, host='mb15-004.cisco.com', database='bhavani',
                 user='bhavani', password='bhavani'):
        self.conn_params = 'host={} dbname={} user={} password={}'.\
                           format(host, database, user, password)
        self.db_conn = connect(self.conn_params)
        self.cursor = self.db_conn.cursor()
        #print 'Connected to db'
        #stdout.flush()
        self.table = 'telemetry.ping'

    
    def apply_sql_oper(self, hosts, sql, netns_name, peer_netns_name):
        result_dict = {True:'success', False:'faiure'}

        xmt = 0
        rcv = 0
        loss = 0.0
        avg_time = 0
        num_hosts = 0
        for to_host,host in hosts.iteritems():
            if host[3] != -100:
                xmt += host[0]
                rcv += host[1]
                loss += host[2]
                avg_time += host[3]
                num_hosts += 1

        if num_hosts != 0:
            loss /= num_hosts
        #print '{}/{}/{}'.format(xmt, rcv, avg_time)
        #stdout.flush()
        if rcv == 0:
            result = 'failure'
        elif xmt == rcv:
            result = 'success'
        else:
            result = 'partial({})'.format(float(rcv)*100.0/xmt)
        
        if num_hosts != 0:
            avg_time = avg_time/num_hosts
        self.cursor.execute(sql, (result_dict[num_hosts > 0], avg_time, netns_name, peer_netns_name))
        self.db_conn.commit()

    def update_ping_data(self, hosts, netns_name, peer_netns_name):
        sql = """ UPDATE telemetry.ping
                     SET result = %s,
                         time_ms = %s
                  WHERE from_host = %s AND to_host = %s """

        self.apply_sql_oper(hosts, sql, netns_name, peer_netns_name)
    
    def delete_ping_data(self):
        sql = " DELETE from telemetry.ping "
        self.cursor.execute(sql)
        self.db_conn.commit()

    def insert_ping_data(self, hosts, netns_name, peer_netns_name):
        sql = """ INSERT into telemetry.ping
                  (result, time_ms, from_host, to_host)
                  VALUES
                  (%s, %s, %s, %s)
                  """

        self.apply_sql_oper(hosts, sql, netns_name, peer_netns_name)
              
class Ping(Thread):
    def __init__(self, clear=False, ns_base='cloud', netns_num=0):
        Thread.__init__(self)

        self.pgi = PostgresInterface()
        if clear:
            self.pgi.delete_ping_data()

        self.hosts = {}
        self.ping_count = 0
        self.netns_num = netns_num
        self.peer_netns_num = 1 - netns_num
        self.netns_name = '{}{}'.format(ns_base, self.netns_num+1)
        self.peer_netns_name = '{}{}'.format(ns_base, self.peer_netns_num+1)

        self.ping_targets = 'ping_targets.%d'%self.peer_netns_num

        self.netns_exec_fping = \
                                ip.bake('netns', 'exec', self.netns_name, 
                                        'fping6', '-l', '-Q1',
                                        '-p250',
                                        '-f', self.ping_targets, 
                                        _err=self.process_output, _bg=True)

        self.start()

    def run(self):
        #print 'Executing {}/{}/{}'.format(self.netns_exec_fping, self.netns_name, self.peer_netns_name)
        fp = self.netns_exec_fping()
        fp.wait()

    def process_output(self,line, stdin, process):

        print line
        vals = ''.join(line.split()).split(':x')
    
        #print '[%d] : %s'%(self.ping_count, vals)
        #print 'vals[0] : {}/{}'.format(vals[0], vals[0][0])
        if vals[0][0] == '[':
            xmit = 0
            rcvd = 0
            time = 0
            num_hosts = len(self.hosts)
            if self.ping_count == 1:
                #print 'inserting {}/{}'.format(self.netns_name, self.peer_netns_name)
                #stdout.flush()
                self.pgi.insert_ping_data(self.hosts, self.netns_name, self.peer_netns_name)
            elif self.ping_count > 1:
                #print 'updating'
                self.pgi.update_ping_data(self.hosts, self.netns_name, self.peer_netns_name)
            for host in self.hosts.itervalues():
                xmit += host[0]
                rcvd += host[1]
                time += host[2]
            if num_hosts:
                #print 'xmit = {} rcvd = {} time = {} ping_count = {} num_hosts = {}'.format(xmit, rcvd, time, self.ping_count, num_hosts)
                lost_pkts = float(xmit-rcvd)/num_hosts
                time = float(time)/(num_hosts*self.ping_count)
                #print 'lost_pkts = {} time {}'.format(lost_pkts, time)
                stdout.flush()
            self.ping_count += 1
        else:
            host = vals[0]
            #print 'host={}'.format(host)
            stats = vals[1].split(',')
        
            #print 'stats={}'.format(stats)
            pkts = stats[0].split('=')[1].split('/')
            #print pkts
            pkts_xmt = int(pkts[0])
            pkts_rcv = int(pkts[1])
            pkts_loss = float(pkts[2].split('%')[0])
            avg_time = -100
            if pkts_xmt == pkts_rcv:
                time = stats[1].split('=')[1].split('/')
                #print time
                avg_time = float(time[1])
            self.hosts[host] = [pkts_xmt, pkts_rcv, pkts_loss, avg_time]
        
            #print '[{}:{}] : {}'.format(self.ping_count, host, self.hosts[host])
        
def main(argc, argv):

    ns_base = 'cloud'
    if argc > 1:
        ns_base = argv[1]

    th0 = Ping(clear=True, ns_base=ns_base)
    th1 = Ping(ns_base=ns_base, netns_num=1)
    

    th1.join()
    th0.join()

if __name__ == '__main__':
    main(len(argv), argv)
