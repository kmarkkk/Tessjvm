#!/usr/bin/env python

import argparse
import datetime
import json
import os
import shutil
import subprocess
import atexit
import run_cassandra_cluster
import re
import time
from subprocess import Popen, PIPE


HEAP_SIZE = 900
YOUNG_SIZE = 700
OSV_IMAGE_DIR = "osv_images"
#ipPrefix = "169.229.48.%d"
ipPrefix = "172.16.2.%d"
ipStart = 101
macAddr = "00:16:3e:16:02:%d"
macStart = 69
cassandraXenCmdline = "--ip=eth0,172.16.2.%d,255.255.255.0  --defaultgw=169.229.48.1 --nameserver=169.229.48.155 /java.so -javaagent:/usr/cassandra/lib/jamm-0.2.6.jar -XX:+CMSClassUnloadingEnabled -XX:+UseThreadPriorities -XX:ThreadPriorityPolicy=42 -Xms%dM -Xmx%dM -Xmn%dM -XX:+HeapDumpOnOutOfMemoryError -Xss256k -XX:StringTableSize=1000003 -XX:+UseParNewGC -XX:+UseConcMarkSweepGC -XX:+CMSParallelRemarkEnabled -XX:SurvivorRatio=8 -XX:MaxTenuringThreshold=1 -XX:CMSInitiatingOccupancyFraction=75 -XX:+UseCMSInitiatingOccupancyOnly -XX:+UseTLAB -XX:+UseCondCardMark -Djava.net.preferIPv4Stack=true -Dcom.sun.management.jmxremote.port=7199 -Dcom.sun.management.jmxremote.rmi.port=7199 -Dcom.sun.management.jmxremote.ssl=false -Dcom.sun.management.jmxremote.authenticate=false -Dlogback.configurationFile=logback.xml -Dcassandra.logdir=/usr/cassandra/logs -Dcassandra.storagedir=/usr/cassandra/data -Dcassandra-foreground=yes -classpath /usr/cassandra/conf/:/usr/cassandra/lib/* org.apache.cassandra.service.CassandraDaemon"
#cassandraXenCmdline = "--ip=eth0,169.229.48.%d,255.255.255.0  --defaultgw=169.229.48.1 --nameserver=169.229.48.155 /java.so -javaagent:/usr/cassandra/lib/jamm-0.2.6.jar -XX:+CMSClassUnloadingEnabled -XX:+UseThreadPriorities -XX:ThreadPriorityPolicy=42 -Xms%dM -Xmx%dM -Xmn%dM -XX:+HeapDumpOnOutOfMemoryError -Xss256k -XX:StringTableSize=1000003 -XX:+UseParNewGC -XX:+UseConcMarkSweepGC -XX:+CMSParallelRemarkEnabled -XX:SurvivorRatio=8 -XX:MaxTenuringThreshold=1 -XX:CMSInitiatingOccupancyFraction=75 -XX:+UseCMSInitiatingOccupancyOnly -XX:+UseTLAB -XX:+UseCondCardMark -Djava.net.preferIPv4Stack=true -Dcom.sun.management.jmxremote.port=7199 -Dcom.sun.management.jmxremote.rmi.port=7199 -Dcom.sun.management.jmxremote.ssl=false -Dcom.sun.management.jmxremote.authenticate=false -Dlogback.configurationFile=logback.xml -Dcassandra.logdir=/usr/cassandra/logs -Dcassandra.storagedir=/usr/cassandra/data -Dcassandra-foreground=yes -classpath /usr/cassandra/conf/:/usr/cassandra/lib/* org.apache.cassandra.service.CassandraDaemon"
YCSB_IP = "169.229.48.100"
YCSB_MAC = "00:16:30:10:02:68"
ycsbXenCmdline = '--execute=--ip=eth0,%s,255.255.255.0  --defaultgw=169.229.48.1 --nameserver=169.229.48.155 /java.so -cp /usr/YCSB/jdbc/src/main/conf:/usr/YCSB/cassandra/target/cassandra-binding-0.1.4.jar:/usr/YCSB/cassandra/target/archive-tmp/cassandra-binding-0.1.4.jar:/usr/YCSB/gemfire/src/main/conf:/usr/YCSB/core/target/core-0.1.4.jar:/usr/YCSB/nosqldb/src/main/conf:/usr/YCSB/hbase/src/main/conf:/usr/YCSB/dynamodb/conf:/usr/YCSB/infinispan/src/main/conf:/usr/YCSB/voldemort/src/main/conf com.yahoo.ycsb.Client -db com.yahoo.ycsb.db.CassandraCQLClient -P /usr/YCSB/workloads/workloada -%s -p "host=%s" -p port=9042 -p threadcount=2'


def clearCassandraInstances():
    proc = Popen(['sudo', 'xl', 'list'], stdout=PIPE)
    (out, err) = proc.communicate()
    proc.wait()
    instances = out.split('\n')
    space = re.compile(" +")
    for instance in instances[1:]:
        name = space.split(instance)[0]
        if name and 'cassandra' in name:
            subprocess.check_call(['sudo', 'xl', 'destroy', name])

def printVerbose(options, statement):
    if options.verbose:
        print statement

def mkdir(directory, clean=False):
    if not os.path.exists(directory):
        os.makedirs(directory)
    elif clean:
        shutil.rmtree(directory)
        os.makedirs(directory)

def cleanUp(options, procsAndFiles):
    #Cleanup Scratch Directories
    for i in range(options.numjvms):
        subprocess.Popen(['rm', '-rf', 'scratch%d' % i])

    #Kill Ongoing processes and close the currently open stdout/stderr files
    while procsAndFiles:
        proc, stdout, stderr = procsAndFiles.pop()
        proc.kill()
        stdout.close()
        stderr.close()

    #Remove OSV Image Directory
    if options.xen:
        shutil.rmtree(OSV_IMAGE_DIR)

def makeOSvImageCopies(options, numCopies):
    mkdir(OSV_IMAGE_DIR)
    for i in xrange(numCopies):
        imageName = "cassandra.qemu_%d" % (i + 1)
        image_path = os.path.join(OSV_IMAGE_DIR, imageName)
        basename = os.path.join(options.cassandra_image, imageName)
        subprocess.call(['cp', basename, image_path])

def parseCpuModel():
    #Adapted from http://amitsaha.github.io/site/notes/articles/python_linux/article.html
    try:
        with open('/proc/cpuinfo') as f:
            for line in f:
                if line.strip() and line.rstrip('\n').startswith('model name'):
                    model_name = line.rstrip('\n').split(':')[1]
                    return model_name
    except IOError:
        return "Unknown"

def parseMemory():
    #Adapted from http://amitsaha.github.io/site/notes/articles/python_linux/article.html
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                key, value = line.split(':')
                if key == 'MemTotal':
                    return value 
    except IOError:
        return "Unknown"
    return "Unknown"

def cassandraXenRunCommand(options, i):
    image_path = os.path.join(OSV_IMAGE_DIR, "cassandra.qemu_%d" % (i + 1))
    cmd = ["./scripts/run.py", "-i", image_path, "-c", options.vcpus, "-p", "xen", "-a", options.cpus, "-m", options.memsize, "--cpupool", options.cpupool, "-n",
    "--bridge", "xenbr0", "--mac", macAddr % (macStart + i)]
    if options.losetup:
        cmd += ["-l"]
    print cmd
    return cmd

def ycsbXenRunCommand(options, hosts, phrase):
    ycsbCmd = ycsbXenCmdline % (YCSB_IP, phrase, hosts)
    ycsbCmd += ' ' + options.ycsb_cmd
    cmd = ["./scripts/run.py", "-t", "ycsb", "-i", options.ycsb_image, "-c", options.vcpus, "-p", "xen", "-m", options.memsize, "-a", options.cpus, "--cpupool", options.cpupool, "-n", "--bridge", "xenbr0", "--mac", YCSB_MAC, ycsbCmd]
    if options.losetup:
        cmd += ["-l"]
    return cmd

def parseMemsize(memory):
    if memory[-1:].upper() == "M":
        memory = int(memory[:-1])
    elif memory[-2:].upper() == "MB":
        memory = int(memory[:-2])
    elif memory[-1:].upper() == "G":
        memory = 1024 * int(memory[:-1])
    elif memory[-2:].upper() == "GB":
        memory = 1024 * int(memory[:-2])
    else:
        raise SyntaxError
    return memory

cassandra_instances = {}

def shutdown_cassandra_instances():
    print '> Shutting down Casssandra instancesssss'
    print cassandra_instances
    for c in cassandra_instances.values():
        print c['process']  
        c['process'].terminate()

    print '> Waiting for processes to terminate...'
    all_done = True
    while not all_done:
        all_done = True
        for c in cassandra_instances.values():
            print c['process']
            print c['process'].poll()
            if (c['process'].poll() == None):
                all_done = False
        time.sleep(0.01)
    print '> DONE'  

cassandraXenInstances = {}

def initCql(options, ip='127.0.0.1'):
    print '>Init cql for cassandra...'
    initCmd = [os.path.join(options.cassandra_home, 'bin/cqlsh'), ip, '-f', options.init_cql]
    initProc = subprocess.Popen(initCmd)
    initProc.wait()
    print '>Done init cql'

def runCassandra(options):
    # Check for ycsb and cassandra home.
    if not options.xen:
        if not options.ycsb_home or not os.path.exists(options.ycsb_home):
            raise Exception("Invalid ycsb home %s" % options.ycsb_home)
        if not options.cassandra_home or not os.path.exists(options.cassandra_home):
            raise Exception("Invalid cassandra home %s" % options.cassandra_home)
        if not options.workload or not os.path.exists(options.workload):
            raise Exception("Invalid workload file %s" % options.workload)

    if options.xen:
        makeOSvImageCopies(options, options.numjvms)
        print '>Done makign image copies...'
        if options.gangscheduled:
            platform = "xen_gangscheduled"
        else:
            platform = "xen"
    else:
        platform = "linux"

    # Build the Directory Structure
    resultsdir = options.resultsdir
    experimentdir = os.path.join(resultsdir, 'cassandra_ycsb')
    platformdir = os.path.join(experimentdir, platform)

    mkdir(resultsdir)
    mkdir(experimentdir)
    mkdir(platformdir)

    # Save experiement system state (revision #, env vars, timestamp, benchmark(s) run)
    sys_state = dict()
    sys_state['git_revision'] = subprocess.Popen(['git', 'rev-parse', 'HEAD'], stdout=subprocess.PIPE).communicate()[0]
    sys_state['env_vars'] = dict(os.environ)
    #sys_state['benchmarks'] = benchmarks
    sys_state['CPU'] = parseCpuModel()
    sys_state['Memory'] = parseMemory()
    sys_state_file = open(os.path.join(platformdir, 'sys_state_%s.json' % datetime.datetime.now().isoformat()), 'w')
    json.dump(sys_state, sys_state_file, sort_keys=True, indent=4, separators=(',', ': '))
    sys_state_file.close()

    # Run Benchmarks under various numbers of JVMS and Heap Sizes
    numjvms = 1
    procsAndFiles = []
    while numjvms <= options.numjvms:
        printVerbose(options, "Num JVMs: %d" % numjvms)
        try:
            outputdir = os.path.join(platformdir, "%djvms" % (numjvms))
            mkdir(outputdir, clean=True)
            if options.xen:
                # Run a xen.
                nodes = []
                for t in xrange(numjvms):
                    cassandraCmdline = cassandraXenCmdline % (ipStart + t, HEAP_SIZE, HEAP_SIZE, YOUNG_SIZE)
                    cmd = cassandraXenRunCommand(options, t)
                    cmd += ['--execute=' + cassandraCmdline]
                    cmd += ['--set-image-only']
                    subprocess.check_call(cmd)
                print '>Done set image command arg'
                for t in xrange(numjvms):
                    nodes.append(ipPrefix % (ipStart + t))
                    cmd = cassandraXenRunCommand(options, t)
                    printVerbose(options, " ".join(cmd))
                    stdoutFile = os.path.join(outputdir, 'stdout%02d' % (t + 1))
                    stderrFile = os.path.join(outputdir, 'stderr%02d' % (t + 1))
                    fstdout = open(stdoutFile, 'a')
                    fstderr = open(stderrFile, 'a')
                    p = subprocess.Popen(cmd, stdout=fstdout, stderr=fstderr)
                    cassandraXenInstances[t] = {'proc':p, 'out':stdoutFile}
                unfinished_nodes= cassandraXenInstances.keys()
                print '>Now waiting for all cassandra instances set up'
                while unfinished_nodes:
                      done_nodes = []
                      for node in unfinished_nodes:
                          with open(cassandraXenInstances[node]['out'], 'r') as fout:
                              outdata = fout.read()   
                          if re.search("Listening for thrift clients...", outdata) != None:
                              done_nodes.append(node)
                      for node in done_nodes:
                          unfinished_nodes.remove(node)
                      time.sleep(0.01)
                print '>All canssadra domains are ready! Start ycsb...'
                time.sleep(3000)
                initCql(options, nodes[0])
                loadCmd = ycsbXenRunCommand(options, ' '.join(nodes), 'load')
                print nodes
                ycsbLoadOut = open(os.path.join(outputdir, 'ycsbloadstdout'), 'a')
                ycsbLoadErr = open(os.path.join(outputdir, 'ycsbloadstderr'), 'a')
                print loadCmd
                subprocess.check_call(loadCmd, stdout=ycsbLoadOut, stderr=ycsbLoadErr)

                runCmd = ycsbXenRunCommand(options, ' '.join(nodes), 'run')
                ycsbRunOut = open(os.path.join(outputdir, 'ycsbrunstdout'), 'a')
                ycsbRunErr = open(os.path.join(outputdir, 'ycsbrunstderr'), 'a')
                subprocess.check_call(loadCmd, stdout=ycsbRunOut, stderr=ycsbRunErr)
                print '>Done ycsb'
            else:
                options.num_nodes = options.numjvms
                options.nosleep = True
                options.basedir = outputdir
                instances = run_cassandra_cluster.do_start(options)
                print 'Returned instances'
                print instances
                cassandra_instances. update(instances)
                #atexit.register(shutdown_cassandra_instances)
                if options.init_cql:
                    initCql(options)
                # Now run ycsb.
                ycsbCmd = [os.path.join(options.ycsb_home, 'bin/ycsb'), 'load', 'cassandra-cql', '-P', options.workload]
                #cmd = ['java', '-Xmx%dM' % heapsize, '-jar', options.dacapo, '--scratch-directory', 'scratch%d' % i, benchmark]

                #if options.xen:
                    #dacapo_cmd = " ".join(['/java.so', '-Xmx%dM' % heapsize, '-jar', "/dacapo.jar", benchmark])
                    #cmd = ["./scripts/run.py", "-i", options.image, "-m", options.memsize, "-c", options.vcpus, 
                     #       '-e', dacapo_cmd, '-p', 'xen']

                # Open stdout and stderr files to pipe output to
                stdout = open(os.path.join(outputdir, 'ycsb_stdout'), 'a')
                stderr = open(os.path.join(outputdir, 'ycsb_stderr'), 'a')
                printVerbose(options, " ".join(ycsbCmd))
                if options.stdout:
                    proc = subprocess.Popen(ycsbCmd)
                else:
                    proc = subprocess.Popen(ycsbCmd, stdout=stdout, stderr=stderr)
                proc.wait()
                # stdout.close()
                # stderr.close()
                print 'Done loading ycsb cassandra...'
                ycsbCmd[1] = 'run'
            while procsAndFiles:
                proc, stdout, stderr = procsAndFiles.pop()
                proc.wait()
                stdout.close()
                stderr.close()
        except KeyboardInterrupt as e:
            print "Detecting KeyboardInterrupt: Cleaning up Experiements"
            cleanUp(options, procsAndFiles)
            clearCassandraInstances()
            raise e
        clearCassandraInstances()
        clearCassandraInstances()
        if numjvms == 1:
          numjvms = 2
        else:
          numjvms += 2
    cleanUp(options, procsAndFiles)



if __name__ == "__main__":
    # Parse arguments
    parser = argparse.ArgumentParser(prog='run')
    parser.add_argument("--startjvms", action="store", default=1, type=int, help="starting amount of JVM's to test on")
    parser.add_argument("-n", "--numjvms", action="store", default=64, type=int, help="max amount of JVM's to test on")
    parser.add_argument("-r", "--resultsdir", action="store", help="where to store results")
    parser.add_argument("--startheap", action="store", default=128, type=int, help="starting heap size")
    parser.add_argument("-p", "--maxheap", action="store", type=int, default=4096, help="max heap size")
    parser.add_argument("-v", "--verbose", action="store_true", default=False, help="be more verbose")
    parser.add_argument("-s", "--stdout", action="store_true", default=False, help="Output to stdout rather than to results dir")
    parser.add_argument("-x", "--xen", action="store_true", default=False, help="whether or not to run on xen")
    parser.add_argument("-g", "--gangscheduled", action="store_true", default=False, help="whether or not the version of xen has gang scheduling")
    parser.add_argument("-ci", "--cassandra-image", action="store", default=None, help="location of the osv image with cassandra on it")
    parser.add_argument("-yi", "--ycsb-image", action="store", default=None, help="location of the osv image with ycsb on it")
    parser.add_argument("-m", "--memsize", action="store", default="2G", help="specify memory: ex. 1G, 2G, ...")
    parser.add_argument("-c", "--vcpus", action="store", default="4", help="specify number of vcpus")
    parser.add_argument("-l", "--losetup", action="store_true", default=False, help="Whether or not use loop devices as disk image.")
    parser.add_argument("--ycsb-home", action="store", default="", help="path to the ycsb home")
    parser.add_argument("--cassandra-home", action="store", default="", help="path to the cassandra home")
    parser.add_argument("--workload", action="store", default="", help="the workload file to run by ycsb")
    parser.add_argument("-a", "--cpus", action="store", default="0-11", help="Which CPU's to pin to for Xen")
    parser.add_argument("--cpupool", action="store", default="Pool-0", help="Which Xen cpupool to use")
    parser.add_argument('-nc', "--num-clusters", action="store", default=1, type=int, help="the number of clusters to run")
    parser.add_argument('--init-cql', action="store", help="the cql file to init cassandra for testing")
    parser.add_argument('--ycsb-cmd', action="store", default="",  help="extra ycsb arguments")
    parser.add_argument('--clean', action="store", help="clean all cassandra domains")

    cmdargs = parser.parse_args()
    if cmdargs.clean:
        clearCassandraInstances()
    else:
      runCassandra(cmdargs)


