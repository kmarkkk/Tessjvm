#!/usr/bin/env python

import argparse
import datetime
import json
import os
import shutil
import subprocess
import time
from threading import Thread

ALL_BENCHMARKS = ["avrora", "h2", "jython", "luindex", "lusearch", "xalan"]
OSV_IMAGE_DIR = "osv_images"
TEST = "dacapo-jit"
TEMPDIR = "jittemp"

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
        shutil.rmtree(TEMPDIR)

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
            "--cpupool", options.cpupool, '--test', TEST, '--numjvms', str(numjvms)]
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

def waitForNIterations(stdout, test, pid, numIterations):
    while True:
        with open(stdout, 'r') as fout:
            output = fout.read()
            if ("completed warmup %d" % numIterations) in output:
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
    experimentdir = os.path.join(resultsdir, TEST)
    platformdir = os.path.join(experimentdir, platform)

    mkdir(resultsdir)
    mkdir(experimentdir)
    mkdir(platformdir)
    mkdir(TEMPDIR)

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
    convergences = getDacapoConvergences(options)

    # Run Benchmarks under various numbers of JVMS and Heap Sizes
    procsAndFiles = None
    for benchmark in benchmarks:
        printVerbose(options, "Benchmark: %s" % benchmark)
        numBenchmarkIterations = convergences[benchmark] + 5 + 1
        numjvms = options.numjvms
        heapsize = max(options.startheap, minheaps[benchmark])
        maxheap = options.maxheap
        while heapsize <= maxheap:
            printVerbose(options, "Num JVMs: %d" % numjvms)
            printVerbose(options, "Heapsize: %dMB" % heapsize)

            outputdir = os.path.join(platformdir, "%s_%02djvms_%04dMB" % (benchmark, numjvms, heapsize))
            if options.safe and os.path.exists(outputdir):
                heapsize *= 2
                continue
            else:
                mkdir(outputdir, clean=True)

            for iter_num in range(options.iterations):
                try:
                    # First warmup an image under load
                    procsAndFiles = []

                    # If using xen, set the new image execute line first before running the image
                    if options.xen:
                        # Make the image copies
                        makeOSvImageCopies(options, options.numjvms)
                        for i in range(numjvms):
                            dacapo_cmd = " ".join(['/java.so', '-Xmx%dM' % heapsize, '-jar', "/dacapo.jar", "-n", '20', benchmark])
                            cmd = dacapoXenRunCommand(options, i, numjvms)
                            cmd += ['-e', dacapo_cmd, '--set-image-only']
                            printVerbose(options, " ".join(cmd))
                            subprocess.check_call(cmd)

                    for i in range(numjvms):
                        cmd = ['java', '-Xmx%dM' % heapsize, '-jar', options.dacapo, '--scratch-directory', 'scratch%d' % i, "-n", str(numBenchmarkIterations), benchmark]

                        if options.xen:
                            cmd = dacapoXenRunCommand(options, i, numjvms)

                        # Open stdout and stderr files to pipe output to
                        stdout = open(os.path.join(TEMPDIR, 'tempout%02d' % (i + 1)), 'w')
                        stderr = open(os.path.join(TEMPDIR, 'temperr%02d' % (i + 1)), 'w')

                        printVerbose(options, " ".join(cmd))
                        if options.stdout:
                            proc = subprocess.Popen(cmd)
                        else:
                            proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)
                        procsAndFiles.append((proc, stdout, stderr, i))

                    if options.xen and options.pausefirst:
                        threads = []
                        # Wait for all Xen domains start up first before running them
                        for proc, stdout, stderr, i in procsAndFiles:
                            thread = Thread(target=pauseFirst, args=(os.path.join(TEMPDIR, 'tempout%02d' % (i + 1)), TEST, proc.pid))
                            threads.append(thread)
                            thread.start()
                        for thread in threads:
                            thread.join()
                        # Now let them run again
                        for proc, stdout, stderr, i in procsAndFiles:
                            subprocess.call(["sudo", "xl", "unpause", "osv-%s-%d" % (TEST, proc.pid)])

                    if options.xen:
                        # Detect when Domain-1 has finished warming up
                        proc0, stdout0, stderr0, i0 = procsAndFiles[0]
                        thread = Thread(target=waitForNIterations, args=(os.path.join(TEMPDIR, 'tempout%02d' % (i0 + 1)), TEST, proc0.pid, convergences[benchmark]))
                        thread.start()
                        thread.join()
                        # Pause Domain-1
                        subprocess.call(["sudo", "xl", "pause", "osv-%s-%d" % (TEST, proc0.pid)])
                        # Now destroy the other domains
                        for proc, stdout, stderr, i in procsAndFiles[1:]:
                            subprocess.call(["sudo", "xl", "destroy", "osv-%s-%d" % (TEST, proc.pid)])
                        # Unpause Domain-1
                        subprocess.call(["sudo", "xl", "unpause", "osv-%s-%d" % (TEST, proc0.pid)])
                        # Wait for Domain-1 to finish test
                        thread = Thread(target=waitForNIterations, args=(os.path.join(TEMPDIR, 'tempout%02d' % (i0 + 1)), TEST, proc0.pid, numBenchmarkIterations))
                        thread.start()
                        thread.join()
                        # Destroy Domain-1
                        subprocess.call(["sudo", "xl", "destroy", "osv-%s-%d" % (TEST, proc0.pid)])
                        # Copy temp stdout of Domain-z1 somewhere to save it
                        subprocess.call(['cp', os.path.join(TEMPDIR, 'tempout%02d' % (i0 + 1)), os.path.join(outputdir, 'stdout%02d' % (iter_num + 1))])

                    while procsAndFiles:
                        proc, stdout, stderr, i = procsAndFiles.pop()
                        proc.wait()
                        stdout.close()
                        stderr.close()

                except (KeyboardInterrupt, subprocess.CalledProcessError) as e:
                    print "Detecting KeyboardInterrupt: Cleaning up Experiments"
                    cleanUp(options, procsAndFiles)
                    raise e
            heapsize *= 2

    cleanUp(options, procsAndFiles)


if __name__ == "__main__":
    # Parse arguments
    parser = argparse.ArgumentParser(prog='run')
    parser.add_argument("-b", "--benchmark", action="store", default="all", help="which dacapo benchmarks to run")
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
    parser.add_argument("--iterations", action="store", default=5, type=int, help="How many iterations of the test to run")
    
    cmdargs = parser.parse_args()
    runDacapo(cmdargs)


