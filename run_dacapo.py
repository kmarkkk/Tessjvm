#!/usr/bin/env python

import argparse
import datetime
import json
import os
import shutil
import subprocess
import time
import re
from threading import Thread

ALL_BENCHMARKS = ["avrora", "h2", "jython", "luindex", "lusearch", "xalan"]
OSV_IMAGE_DIR = "osv_images"

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
        proc, stdout, stderr, i = procsAndFiles.pop()
        proc.kill()
        stdout.close()
        stderr.close()

    #Remove OSV Image Directory
    if options.xen:
        shutil.rmtree(OSV_IMAGE_DIR)

def cleanUpTracer(tracer, trace_bin):

    def summary():
        outputdir = os.path.dirname(trace_bin)
        stdout = open(os.path.join(outputdir, 'xenalyze_summary'), 'w')
        stderr = open(os.path.join(outputdir, 'xenalyze_summary_err'), 'w')
        subprocess.call(["xenalyze", "--cpu-hz", "2.67G", "--summary", trace_bin], stdout=stdout, stderr=stderr)
        subprocess.call(["sudo", "rm", trace_bin])

    subprocess.call(["sudo", "pkill", "-TERM", "-P", str(tracer.pid)])
    thread = Thread(target=summary)
    thread.start()

def makeOSvImageCopies(options, numCopies):
    mkdir(OSV_IMAGE_DIR)
    basename = os.path.basename(options.image)
    for i in range(numCopies):
        image_path =  "%s_%d" % (os.path.join(OSV_IMAGE_DIR, basename), i + 1)
        subprocess.call(['cp', options.image, image_path])

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

def dacapoXenRunCommand(options, i, numjvms):
    basename = os.path.basename(options.image)
    image_path =  "%s_%d" % (os.path.join(OSV_IMAGE_DIR, basename), i + 1)
    cmd = ["./scripts/run.py", "-i", image_path, "-m", options.memsize, "-c", options.vcpus, '-p', 'xen', '-a', options.cpus,
            "--cpupool", options.cpupool, '--test', options.test, '--numjvms', str(numjvms)]
    if options.losetup:
        cmd += ['-l']
    return cmd

def getDacapoConvergences(options):
    try:
        with open('dacapo_convergences.json', 'r') as f: 
            return json.load(f)
    except IOError:
        subprocess.call(["./dacapo_converge.py", '-d', options.dacapo])
        return getDacapoConvergences(options)

def pauseFirst(stdout, test, pid):
    while True:
        with open(stdout, 'r') as fout:
            output = fout.read()
            if "OSv" in output:
                subprocess.call(["sudo", "xl", "pause", "osv-%s-%d" % (test, pid)])
                break
        #Wait 1 Second before checking again
        time.sleep(1)         

def pauseAfterWarmUp(stdout, test, pid, numIterations):
    while True:
        with open(stdout, 'r') as fout:
            output = fout.read()
            if ("completed warmup %d" % numIterations) in output:
                subprocess.call(["sudo", "xl", "pause", "osv-%s-%d" % (test, pid)])
                break
        #Wait 1 Second before checking again
        time.sleep(1)

def waitForNIterations(stdout, test, pid, numIterations):
    while True:
        with open(stdout, 'r') as fout:
            output = fout.read()
            if ("completed warmup %d" % numIterations) in output or '[backtrace]' in output:
                break
        #Wait 1 Second before checking again
        time.sleep(1)

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
    experimentdir = os.path.join(resultsdir, options.test)
    platformdir = os.path.join(experimentdir, platform)

    mkdir(resultsdir)
    mkdir(experimentdir)
    mkdir(platformdir)

    # Parse which dacapo benchmark to run
    if options.benchmark == "all":
        benchmarks = ALL_BENCHMARKS
    else:
        benchmarks = options.benchmark.split(",")

    # Save experiment system state (revision #, env vars, timestamp, benchmark(s) run)
    sys_state = dict()
    sys_state['git_revision'] = subprocess.Popen(['git', 'rev-parse', 'HEAD'], stdout=subprocess.PIPE).communicate()[0]
    sys_state['env_vars'] = dict(os.environ)
    sys_state['options'] = dict(vars(options))
    sys_state['CPU'] = parseCpuModel()
    sys_state['Memory'] = parseMemory()
    sys_state_file = open(os.path.join(platformdir, 'sys_state_%s.json' % datetime.datetime.now().isoformat()), 'w')
    json.dump(sys_state, sys_state_file, sort_keys=True, indent=4, separators=(',', ': '))
    sys_state_file.close()

    #Loading Min Heap Sizes
    with open("dacapo_min_heap.json") as f:
        minheaps = json.load(f)

    #Loading Dacapo Convergences
    convergences = getDacapoConvergences(options)

    # Run Benchmarks under various numbers of JVMS and Heap Sizes
    procsAndFiles = None
    for benchmark in benchmarks:
        printVerbose(options, "Benchmark: %s" % benchmark)
        numBenchmarkIterations = convergences[benchmark] + 5
        numjvms = options.startjvms
        while numjvms <= options.numjvms:
            printVerbose(options, "Num JVMs: %d" % numjvms)
            heapsize = max(options.startheap, minheaps[benchmark])
            maxheap = options.maxheap
            while heapsize <= maxheap:
                try:
                    printVerbose(options, "Heapsize: %dMB" % heapsize)
                    procsAndFiles = []

                    outputdir = os.path.join(platformdir, "%s_%02djvms_%04dMB" % (benchmark, numjvms, heapsize))
                    if options.safe and os.path.exists(outputdir):
                        heapsize *= 2
                        continue
                    else:
                        mkdir(outputdir, clean=True)

                    # If using xen, set the new image execute line first before running the image
                    if options.xen:
                        # Make the image copies
                        makeOSvImageCopies(options, options.numjvms)
                        for i in range(numjvms):
                            numIterations = 40
                            if options.gangscheduled:
                                numIterations = numBenchmarkIterations + 10
                            dacapo_cmd = " ".join(['/java.so', '-Xmx%dM' % heapsize, '-XX:+PrintGCTimeStamps', '-XX:+PrintGCDetails', '-XX:+UseParallelOldGC',
                                                     '-jar', "/dacapo.jar", "-n", str(numIterations), benchmark])
                            cmd = dacapoXenRunCommand(options, i, numjvms)
                            cmd += ['-e', dacapo_cmd, '--set-image-only']
                            printVerbose(options, " ".join(cmd))
                            subprocess.check_call(cmd)

                    # Start Xen Trace
                    tracer = subprocess.Popen(["sudo", "xentrace", "-D", "-e", "0x0002f000", os.path.join(outputdir, 'trace_file.bin')])

                    for i in range(numjvms):
                        cmd = ['java', '-Xmx%dM' % heapsize, '-jar', options.dacapo, '--scratch-directory', 'scratch%d' % i, "-n", str(numBenchmarkIterations), benchmark]

                        if options.xen:
                            cmd = dacapoXenRunCommand(options, i, numjvms)

                        # Open stdout and stderr files to pipe output to
                        stdout = open(os.path.join(outputdir, 'stdout%02d' % (i + 1)), 'a')
                        stderr = open(os.path.join(outputdir, 'stderr%02d' % (i + 1)), 'a')

                        printVerbose(options, " ".join(cmd))
                        if options.stdout:
                            proc = subprocess.Popen(cmd)
                        else:
                            proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)
                        procsAndFiles.append((proc, stdout, stderr, i))

                    if options.xen and (options.pausefirst or options.gangscheduled):
                        threads = []
                        # Wait for all Xen domains start up first before running them
                        for proc, stdout, stderr, i in procsAndFiles:
                            thread = Thread(target=pauseFirst, args=(os.path.join(outputdir, 'stdout%02d' % (i + 1)), options.test, proc.pid))
                            threads.append(thread)
                            thread.start()
                        for thread in threads:
                            thread.join()
                        # Now let them run again
                        if options.gangscheduled:
                            for proc, stdout, stderr, i in procsAndFiles:
                                subprocess.call(["sudo", "xl", "cpupool-migrate", "osv-%s-%d" % (options.test, proc.pid), 'GangSched-Pool'])
                            domain1 = "osv-%s-%d" % (options.test, procsAndFiles[0][0].pid)
                            xl_list = subprocess.check_output(['sudo', 'xl', 'list'])
                            domain1_id = re.findall(r"%s\s*(\d*)" % domain1, xl_list)[0]
                            subprocess.call(["sudo", "./gsc", '-d', domain1_id, '-p', '1', '-c', '1,2,3', '-t', 'tt,200,100'])
                        else:
                            for proc, stdout, stderr, i in procsAndFiles:
                                subprocess.call(["sudo", "xl", "unpause", "osv-%s-%d" % (options.test, proc.pid)])

                    if options.xen and options.pauseafterwarmup:
                        threads = []
                        # Wait for all Xen domains to warm up before continuing on
                        for proc, stdout, stderr, i in procsAndFiles:
                            thread = Thread(target=pauseAfterWarmUp, args=(os.path.join(outputdir, 'stdout%02d' % (i + 1)), options.test, proc.pid, convergences[benchmark]))
                            threads.append(thread)
                            thread.start()
                        for thread in threads:
                            thread.join()
                        # Now let them run again
                        for proc, stdout, stderr, i in procsAndFiles:
                            subprocess.call(["sudo", "xl", "unpause", "osv-%s-%d" % (options.test, proc.pid)])

                    if options.xen and not options.gangscheduled:
                        print "DESTROY"
                        threads = []
                        # Detect when all Xen domains have hit some iteration
                        for proc, stdout, stderr, i in procsAndFiles:
                            thread = Thread(target=waitForNIterations, args=(os.path.join(outputdir, 'stdout%02d' % (i + 1)), options.test, proc.pid, numBenchmarkIterations))
                            threads.append(thread)
                            thread.start()
                        for thread in threads:
                            thread.join()
                        # Now destroy them
                        for proc, stdout, stderr, i in procsAndFiles:
                            subprocess.call(["sudo", "xl", "destroy", "osv-%s-%d" % (options.test, proc.pid)])

                    while procsAndFiles:
                        proc, stdout, stderr, i = procsAndFiles.pop()
                        proc.wait()
                        stdout.close()
                        stderr.close()
                    cleanUpTracer(tracer, os.path.join(outputdir, 'trace_file.bin'))
                    heapsize *= 2
                except (KeyboardInterrupt, subprocess.CalledProcessError) as e:
                    print "Detecting KeyboardInterrupt: Cleaning up Experiments"
                    cleanUp(options, procsAndFiles)
                    raise e
            if numjvms == options.numjvms:
                numjvms *= 2
            else:
                numjvms = min(numjvms * 2, options.numjvms)

    cleanUp(options, procsAndFiles)


if __name__ == "__main__":
    # Parse arguments
    parser = argparse.ArgumentParser(prog='run')
    parser.add_argument("-t", "--test", action="store", default="dacapo", help="choose test to run: dacapo, cassandra")
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
    parser.add_argument("-a", "--cpus", action="store", default="all", help="Which CPU's to pin to for Xen")
    parser.add_argument("--safe", action="store_true", default=False, help="Run in 'Safe' Mode (don't rerun and overwrite tests which already have folders)")
    parser.add_argument("--cpupool", action="store", default="Pool-0", help="Which Xen cpupool to use")
    parser.add_argument("--pausefirst", action="store_true", default=False, help="Whether or not to pause all the domains first and unpause them all at the same time")
    parser.add_argument("--pauseafterwarmup", action="store_true", default=False, help="Whether or not to set a barrier after warming up domains")
    
    cmdargs = parser.parse_args()
    if cmdargs.test == "dacapo":
        runDacapo(cmdargs)
    else:
        raise Exception("Uknown test %s" % cmdargs.test)


