#!/usr/bin/env python

import argparse
import json
import math
import random
import re
import subprocess

ALL_BENCHMARKS = ["avrora", "h2", "jython", "luindex", "lusearch", "xalan"]
CONVERGENCE_PATTERN = r'warmup (\d+)'

def findConvergence(options):
    convergence = dict()
    for benchmark in ALL_BENCHMARKS:
        print benchmark
        numIterations = 0
        for i in range(options.numtrials):
            stderr = subprocess.Popen(['java', '-jar', options.dacapo, benchmark, '-C'], stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()[1]
            n = parseNumIterations(stderr)
            print "Trial %d: %d" % (i + 1, n)
            numIterations += n
        convergence[benchmark] = int(math.ceil(float(numIterations) / options.numtrials))
        print

    with open("dacapo_convergences.json", "w") as f:
        json.dump(convergence, f, sort_keys=True, indent=4, separators=(',', ': '))

def parseNumIterations(stderr):
    iterations_numbers = map(int, re.findall(CONVERGENCE_PATTERN, stderr))
    return max(iterations_numbers)

if __name__ == "__main__":
    # Parse arguments
    parser = argparse.ArgumentParser(prog='run')
    parser.add_argument("-d", "--dacapo", action="store", default="dacapo-9.12-bach.jar", help="where dacapo is located")
    parser.add_argument("-n", "--numtrials", action="store", default=5, type=int, help="How many trials to run to get average convergence time")

    cmdargs = parser.parse_args()
    findConvergence(cmdargs)
