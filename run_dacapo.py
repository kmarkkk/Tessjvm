#!/usr/bin/env python

import argparse
import datetime
import json
import os
import shutil
import subprocess

ALL_BENCHMARKS = ["avrora", "h2", "jython", "luindex", "lusearch", "xalan"]
EXPERIMENT = "dacapo"

def printVerbose(options, statement):
    if options.verbose:
        print statement

def mkdir(directory, clean=False):
    if not os.path.exists(directory):
        os.makedirs(directory)
    elif clean:
        shutil.rmtree(directory)
        os.makedirs(directory)

def cleanUp(options, procs, stdout, stderr):
    #Cleanup Scratch Directories
    for i in range(options.numjvms):
        subprocess.Popen(['rm', '-rf', 'scratch%d' % i])

    #Kill Ongoing processes
    if procs:
        for proc in procs:
            proc.kill()

    #Flush and Close the currently open stdout/stderr file
    if stdout:
        stdout.close()
    if stderr:
        stderr.close()

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

def runDacapo(options):
    if options.xen:
        if options.gangscheduled:
            platform = "xen_gangscheduled"
        else:
            platform = "xen"
    else:
        platform = "linux"

    # Build the Directory Structure
    resultsdir = options.resultsdir
    experimentdir = os.path.join(resultsdir, EXPERIMENT)
    platformdir = os.path.join(experimentdir, platform)

    mkdir(resultsdir)
    mkdir(experimentdir)
    mkdir(platformdir)

    # Parse which dacapo benchmark to run
    if options.benchmark == "all":
        benchmarks = ALL_BENCHMARKS
    else:
        assert options.benchmark in ALL_BENCHMARKS
        benchmarks = [options.benchmark]

    # Save experiement system state (revision #, env vars, timestamp, benchmark(s) run)
    sys_state = dict()
    sys_state['git_revision'] = subprocess.Popen(['git', 'rev-parse', 'HEAD'], stdout=subprocess.PIPE).communicate()[0]
    sys_state['env_vars'] = dict(os.environ)
    sys_state['benchmarks'] = benchmarks
    sys_state['CPU'] = parseCpuModel()
    sys_state['Memory'] = parseMemory()
    sys_state_file = open(os.path.join(platformdir, 'sys_state_%s.json' % datetime.datetime.now().isoformat()), 'w')
    json.dump(sys_state, sys_state_file, sort_keys=True, indent=4, separators=(',', ': '))
    sys_state_file.close()

    # Run Benchmarks under various numbers of JVMS and Heap Sizes
    for benchmark in benchmarks:
        printVerbose(options, "Benchmark: %s" % benchmark)
        numjvms = options.startjvms
        while numjvms <= options.numjvms:
            printVerbose(options, "Num JVMs: %d" % numjvms)
            heapsize = options.startheap
            while heapsize <= options.maxheap:
                try:
                    printVerbose(options, "Heapsize: %dMB" % heapsize)
                    procs = []

                    outputdir = os.path.join(platformdir, "%s_%djvms_%dMB" % (benchmark, numjvms, heapsize))
                    mkdir(outputdir, clean=True)
                    stdout = open(os.path.join(outputdir, 'stdout'), 'a')
                    stderr = open(os.path.join(outputdir, 'stderr'), 'a')
                    for i in range(numjvms):
                        cmd = ['java', '-Xmx%dM' % heapsize, '-jar', options.dacapo, '--scratch-directory', 'scratch%d' % i, benchmark]

                        if options.xen:
                            dacapo_cmd = " ".join(['/java.so', '-Xmx%dM' % heapsize, '-jar', "/dacapo.jar", benchmark])
                            cmd = ["./scripts/run.py", "-i", options.image, "-m", options.memsize, "-c", options.vcpus, 
                                    '-e', dacapo_cmd, '-p', 'xen']
                            if options.losetup:
                                cmd += ['-l']

                        printVerbose(options, " ".join(cmd))
                        if options.stdout:
                            proc = subprocess.Popen(cmd)
                        else:
                            proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)
                        procs.append(proc)

                    for proc in procs:
                        proc.wait()
                        procs.remove(proc)
                    stdout.close()
                    stderr.close()
                    heapsize *= 2
                except KeyboardInterrupt as e:
                    print "Detecting KeyboardInterrupt: Cleaning up Experiements"
                    cleanUp(options, procs, stdout, stderr)
                    raise e
            numjvms *= 2

    cleanUp(options, procs, stdout, stderr)


if __name__ == "__main__":
    # Parse arguments
    parser = argparse.ArgumentParser(prog='run')
    parser.add_argument("-b", "--benchmark", action="store", default="all", help="which dacapo benchmarks to run")
    parser.add_argument("--startjvms", action="store", default=1, type=int, help="starting amount of JVM's to test on")
    parser.add_argument("-n", "--numjvms", action="store", default=64, type=int, help="max amount of JVM's to test on")
    parser.add_argument("-d", "--dacapo", action="store", default="dacapo-9.12-bach.jar", help="where dacapo is located")
    parser.add_argument("-r", "--resultsdir", action="store", help="where to store results")
    parser.add_argument("--startheap", action="store", default=128, type=int, help="starting heap size")
    parser.add_argument("-p", "--maxheap", action="store", type=int, default=4096, help="max heap size")
    parser.add_argument("-v", "--verbose", action="store_true", default=False, help="be more verbose")
    parser.add_argument("-s", "--stdout", action="store_true", default=False, help="Output to stdout rather than to results dir")
    parser.add_argument("-x", "--xen", action="store_true", default=False, help="whether or not to run on xen")
    parser.add_argument("-g", "--gangscheduled", action="store_true", default=False, help="whether or not the version of xen has gang scheduling")
    parser.add_argument("-i", "--image", action="store", default=None, help="location of the osv image with dacapo on it")
    parser.add_argument("-m", "--memsize", action="store", default="2G", help="specify memory: ex. 1G, 2G, ...")
    parser.add_argument("-c", "--vcpus", action="store", default="4", help="specify number of vcpus")
    parser.add_argument("-l", "--losetup", action="store_true", default=False, help="Whether or not use loop devices as disk image.")
    cmdargs = parser.parse_args()
    
    runDacapo(cmdargs)


