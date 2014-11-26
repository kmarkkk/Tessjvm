#!/usr/bin/env python

import os
import matplotlib.pyplot as plt
import numpy as np
import re
import argparse
from collections import defaultdict

RESULTS_DIR='results_iter1'
DACAPO_DIR='dacapo'
DACAPO_BENCHMARKS = ['avrora', 'h2', 'jython', 'luindex', 'lusearch', 'xalan']

def parse_benchmark(benchmark, benchmark_experiments, os_type):
  print "Parsing runtime results for %d %s experiments...\n" % (len(benchmark_experiments), benchmark)

  runtime_results = parse_runtime_results(benchmark, benchmark_experiments, os_type)

  # Initialize values we'll need for the x-axis
  all_memory_sizes = [128, 256, 512, 1024, 2048, 4096]
  xs = range(1,len(all_memory_sizes)+1)
  # These offset the bar series from each other. Designed for 5 bar series.
  bar_width = 0.1
  offset = -0.2

  # Colors for successive bar series
  color_iter = iter(['b', 'g', 'r', 'c', 'm', 'y'])

  ax = plt.subplot(111)
  # Add an extra entry to the x-axis so we can see all of the experiments
  ax.set_xlim(0, len(all_memory_sizes)+1)

  for jvm_count, memsize_to_results in sorted(runtime_results.iteritems(), key=lambda t: t[0]):
    avg_runtimes = [memsize_to_results[memsize] for memsize in all_memory_sizes]
    ax.bar([x + offset for x in xs], avg_runtimes, width=bar_width, color=next(color_iter), align="center", label="%d JVMs" % jvm_count)
    offset += bar_width

  # Apply labels
  plt.title(" %s Mean Run Times" % benchmark)
  plt.ylabel("Runtime (ms)")
  plt.xlabel("Memory Size")
  plt.xticks(xs, map(lambda v: str(v)+"MB", all_memory_sizes))
  plt.legend()

  # Show the plot
  plt.show()

def parse_runtime_results(benchmark, benchmark_experiments, os_type):
  # Returns dictionary of the form: {num_jvms -> {mem_size -> avg_runtime_ms}}
  jvms_to_results = defaultdict(lambda : defaultdict(int))
  for exp in benchmark_experiments:
    benchmark, num_jvms, mem_size = re.search("([a-zA-Z0-9]*)_(\d+)jvms_(\d+)MB$", exp).groups()
    num_jvms, mem_size = int(num_jvms), int(mem_size)

    exp_path = "/".join([RESULTS_DIR, DACAPO_DIR, os_type, exp])

    exp_times = []
    for jvm in range(1, num_jvms+1):
      # Runtimes are logged in the stderr files on linux and stout files on xen
      if os_type == "xen":
        filename = "/".join([exp_path, "stdout%d" % jvm])
      else:
        filename = "/".join([exp_path, "stderr%d" % jvm])
      with open(filename, 'r') as f:
        contents = f.read()
        all_per_jvm_times = map(int, re.findall("%s .* in (\d+) msec" % benchmark, contents))
        # We always look at the last five runs for each JVM in this experiment
        per_jvm_times = all_per_jvm_times[-5:]
        if len(per_jvm_times) < 5:
          print "Unable to find 5 valid runtimes for %s" % exp
          continue
      # We'll use the mean
      exp_times.append(np.mean(per_jvm_times))

    jvms_to_results[num_jvms][mem_size] = np.mean(exp_times)

  return jvms_to_results

if __name__ == "__main__":
  parser = argparse.ArgumentParser(prog='run')
  parser.add_argument("-x", "--xen", action="store_true", default=False, help="enable to parse xen results instead of linux")
  cmdargs = parser.parse_args()

  if cmdargs.xen:
    os_type = 'xen'
  else:
    os_type = 'linux'

  experiments_dir = '/'.join([RESULTS_DIR, DACAPO_DIR, os_type])
  all_experiments = os.listdir(experiments_dir)

  for benchmark in DACAPO_BENCHMARKS:
    benchmark_experiments = filter(lambda s: re.match("^%s_.*" % benchmark, s), all_experiments)
    parse_benchmark(benchmark, benchmark_experiments, os_type)


