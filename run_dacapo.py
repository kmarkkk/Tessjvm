#!/usr/bin/env python

import argparse
import datetime
import json
import os
import shutil
import subprocess

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
        proc, stdout, stderr = procsAndFiles.pop()
        proc.kill()
        stdout.close()
        stderr.close()

    #Remove OSV Image Directory
    if options.xen
        shutil.rmtree(OSV_IMAGE_DIR)

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

def dacapoXenRunCommand(options, i, heapsize):
    OSV_SLACK = 256 #256MB
    basename = os.path.basename(options.image)
    image_path =  "%s_%d" % (os.path.join(OSV_IMAGE_DIR, basename), i + 1)
    cmd = ["./scripts/run.py", "-i", image_path, "-m", "%d" % (heapsize + OSV_SLACK), "-c", options.vcpus, '-p', 'xen', '-a', options.cpus, '--early-destroy']
    if options.losetup:
        cmd += ['-l']
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

def getDacapoConvergences():
    try:
        with open('dacapo_convergences.json', 'r') as f: 
            return json.load(f)
    except IOError:
        subprocess.call(["./dacapo_converge.py", '-d', options.dacapo])
        return getDacapoConvergences()

def runCassandra(options):
    # Check for ycsb and cassandra home.
    if not options.ycsb_home or not os.path.exists(options.ycsb_home):
        raise Exception("Invalid ycsb home %s" % options.ycsb_home)
    if not options.cassandra_home or not os.path.exists(options.cassandra_home):
        raise Exception("Invalid cassandra home %s" % options.cassandra_home)
    if not options.workload or not os.path.exists(options.workload):
        raise Exception("Invalid workload file %s" % options.workload)


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
    while numjvms <= options.numjvms:
        printVerbose(options, "Num JVMs: %d" % numjvms)
        try:
            procsAndFiles = []
            outputdir = os.path.join(platformdir, "%s_%djvms" % (options.workload, numjvms))
            mkdir(outputdir, clean=True)
            for i in xrange(numjvms):
                #cmd = ['java', '-Xmx%dM' % heapsize, '-jar', options.dacapo, '--scratch-directory', 'scratch%d' % i, benchmark]

                #if options.xen:
                    #dacapo_cmd = " ".join(['/java.so', '-Xmx%dM' % heapsize, '-jar', "/dacapo.jar", benchmark])
                    #cmd = ["./scripts/run.py", "-i", options.image, "-m", options.memsize, "-c", options.vcpus, 
                     #       '-e', dacapo_cmd, '-p', 'xen']

                # Open stdout and stderr files to pipe output to
                stdout = open(os.path.join(outputdir, 'stdout%d' % (i + 1)), 'a')
                stderr = open(os.path.join(outputdir, 'stderr%d' % (i + 1)), 'a')

                printVerbose(options, " ".join(cmd))
                if options.stdout:
                    proc = subprocess.Popen(cmd)
                else:
                    proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)
                procsAndFiles.append((proc, stdout, stderr))

            while procsAndFiles:
                proc, stdout, stderr = procsAndFiles.pop()
                proc.wait()
                stdout.close()
                stderr.close()
            heapsize *= 2
        except KeyboardInterrupt as e:
            print "Detecting KeyboardInterrupt: Cleaning up Experiements"
            cleanUp(options, procsAndFiles)
            raise e
        numjvms *= 2

    cleanUp(options, procsAndFiles)

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
        assert options.benchmark in ALL_BENCHMARKS
        benchmarks = [options.benchmark]

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
    convergences = getDacapoConvergences()

    # Run Benchmarks under various numbers of JVMS and Heap Sizes
    procsAndFiles = None
    for benchmark in benchmarks:
        printVerbose(options, "Benchmark: %s" % benchmark)
        numBenchmarkIterations = str(convergences[benchmark] + 5)
        numjvms = options.startjvms
        while numjvms <= options.numjvms:
            printVerbose(options, "Num JVMs: %d" % numjvms)
            heapsize = max(options.startheap, minheaps[benchmark])
            maxheap = min(options.maxheap, parseMemsize(options.memsize) / numjvms)
            while heapsize <= maxheap:
                try:
                    printVerbose(options, "Heapsize: %dMB" % heapsize)
                    procsAndFiles = []

                    outputdir = os.path.join(platformdir, "%s_%djvms_%dMB" % (benchmark, numjvms, heapsize))
                    mkdir(outputdir, clean=True)

                    # If using xen, set the new image execute line first before running the image
                    if options.xen:
                        # First create the image copies
                        makeOSvImageCopies(options, numjvms)
                        for i in range(numjvms):
                            dacapo_cmd = " ".join(['/java.so', '-Xmx%dM' % heapsize, '-jar', "/dacapo.jar", "-n", numBenchmarkIterations, benchmark])
                            cmd = dacapoXenRunCommand(options, i, heapsize)
                            cmd += ['-e', dacapo_cmd, '--set-image-only']
                            printVerbose(options, " ".join(cmd))
                            subprocess.check_call(cmd)

                    for i in range(numjvms):
                        cmd = ['java', '-Xmx%dM' % heapsize, '-jar', options.dacapo, '--scratch-directory', 'scratch%d' % i, "-n", numBenchmarkIterations, benchmark]

                        if options.xen:
                            cmd = dacapoXenRunCommand(options, i, heapsize)

                        # Open stdout and stderr files to pipe output to
                        stdout = open(os.path.join(outputdir, 'stdout%d' % (i + 1)), 'a')
                        stderr = open(os.path.join(outputdir, 'stderr%d' % (i + 1)), 'a')

                        printVerbose(options, " ".join(cmd))
                        if options.stdout:
                            proc = subprocess.Popen(cmd)
                        else:
                            proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)
                        procsAndFiles.append((proc, stdout, stderr))

                    while procsAndFiles:
                        proc, stdout, stderr = procsAndFiles.pop()
                        proc.wait()
                        stdout.close()
                        stderr.close()
                    heapsize *= 2
                except (KeyboardInterrupt, subprocess.CalledProcessError) as e:
                    print "Detecting KeyboardInterrupt: Cleaning up Experiements"
                    cleanUp(options, procsAndFiles)
                    raise e
            numjvms *= 2

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
    parser.add_argument("--ycsb-home", action="store", default="", help="path to the ycsb home")
    parser.add_argument("--cassandra-home", action="store", default="", help="path to the cassandra home")
    parser.add_argument("--workload", action="store", default="", help="the workload file to run by ycsb")
    parser.add_argument("-a", "--cpus", action="store", default="0-11", help="Which CPU's to pin to for Xen")
    
    cmdargs = parser.parse_args()
    if cmdargs.test == "dacapo":
        runDacapo(cmdargs)
    elif cmdargs.test == "cassandra":
        runCassandra(cmdargs)
    else:
        raise Exception("Uknown test %s" % cmdargs.test)


