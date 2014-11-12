#!/usr/bin/env python

import argparse
import datetime
import json
import os
import shutil
import subprocess

ALL_BENCHMARKS = ["avrora", "h2", "jython", "luindex", "lusearch", "xalan"]
EXPERIMENT = "dacapo"
TYPE = "linux"

def printVerbose(options, statement):
    if options.verbose:
        print statement

def mkdir(directory, clean=False):
    if not os.path.exists(directory):
        os.makedirs(directory)
    elif clean:
        shutil.rmtree(directory)
        os.makedirs(directory)

def cleanUp(options, procs_and_files):
    #Cleanup Scratch Directories
    for i in range(options.numjvms):
        subprocess.Popen(['rm', '-rf', 'scratch%d' % i])

    #Kill Ongoing processes
    if procs_and_files:
        for proc, stdout in procs_and_files:
            proc.kill()
            stdout.close()

def runDacapo(options):
    # Build the Directory Structure
    resultsdir = options.resultsdir
    experimentdir = os.path.join(resultsdir, EXPERIMENT)
    typedir = os.path.join(experimentdir, TYPE)

    mkdir(resultsdir)
    mkdir(experimentdir)
    mkdir(typedir)

    # Parse which dacapo benchmark to run
    if options.benchmark == "all":
        benchmarks = ALL_BENCHMARKS
    else:
        assert options.benchmark in ALL_BENCHMARKS
        benchmarks = [options.benchmark]

    # Save experiement system state (revision #, env vars, timestamp, benchmark(s) run)
    sys_state = dict()
    sys_state['git_revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'])
    sys_state['env_vars'] = dict(os.environ)
    sys_state['benchmarks'] = benchmarks
    sys_state_file = open(os.path.join(typedir, 'sys_state_%s.json' % datetime.datetime.now().isoformat()), 'w')
    json.dump(sys_state, sys_state_file, sort_keys=True, indent=4, separators=(',', ': '))
    sys_state_file.close()

    # Run Benchmarks under various numbers of JVMS and Heap Sizes
    for benchmark in benchmarks:
        printVerbose(options, "Benchmark: %s" % benchmark)
        numjvms = 1
        while numjvms <= options.numjvms:
            printVerbose(options, "Num JVMs: %d" % numjvms)
            heapsize = 128
            while heapsize <= options.maxheap:
                try:
                    printVerbose(options, "Heapsize: %dMB" % heapsize)
                    procs_and_files = []
                    for i in range(numjvms):
                        outputdir = os.path.join(typedir, "%s_%djvms_%dMB" % (benchmark, numjvms, heapsize))
                        mkdir(outputdir, clean=True)

                        stdout = open(os.path.join(outputdir, 'stdout'), 'a')

                        cmd = ['java', '-Xmx%dM' % heapsize, '-jar', options.dacapo, '--scratch-directory', 'scratch%d' % i, benchmark]
                        printVerbose(options, " ".join(cmd))
                        proc = subprocess.Popen(cmd, stdout=stdout, stderr=stdout)
                        procs_and_files.append((proc, stdout))

                    for proc, stdout in procs_and_files:
                        proc.wait()
                        stdout.close()
                        procs_and_files.remove((proc, stdout))
                    heapsize *= 2
                except KeyboardInterrupt as e:
                    print "Detecting KeyboardInterrupt: Cleaning up Experiements"
                    cleanUp(options, procs_and_files)
                    raise e
            numjvms *= 2

    cleanUp(options, procs_and_files)


if __name__ == "__main__":
    # Parse arguments
    parser = argparse.ArgumentParser(prog='run')
    parser.add_argument("-b", "--benchmark", action="store", default="all", help="which dacapo benchmarks to run")
    parser.add_argument("-n", "--numjvms", action="store", default=64, type=int, help="max amount of JVM's to test on")
    parser.add_argument("-d", "--dacapo", action="store", default="dacapo-9.12-bach.jar", help="where dacapo is located")
    parser.add_argument("-r", "--resultsdir", action="store", help="where to store results")
    parser.add_argument("-m", "--maxheap", action="store", type=int, default=4096, help="max head size")
    parser.add_argument("-v", "--verbose", action="store_true", default=False, help="be more verbose")
    cmdargs = parser.parse_args()
    
    runDacapo(cmdargs)


