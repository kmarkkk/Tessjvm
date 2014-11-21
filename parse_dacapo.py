#!/usr/bin/env python

import os
import matplotlib.pyplot as plt
import re
import argparse

RESULTS_DIR='results_iter1'
DACAPO_DIR='dacapo'
DACAPO_BENCHMARKS = ['avrora', 'h2', 'jython', 'luindex', 'lusearch', 'xalan']

def parse_benchmark(benchmark, benchmark_experiments, os_type):

  print "Parsing runtime statistics for %d %s experiments" % (len(benchmark), benchmark)
  runtime_results = parse_runtime_results(benchmark, benchmark_experiments)

  print runtime_results
  #print "Parsing Experiment %s with %d JVMs and memory size = %d" % (benchmark, int(num_jvms), int(mem_size))
  xs, ys, zs = [list(tuple_vector) for tuple_vector in zip(*sorted(runtime_results, key=lambda t: -t[0]))]
  

  ax = plt.subplot(111)
  ax.bar([x - 0.1 for x in xs], ys, width=0.2, color="b", align="center", log=True)
  ax.bar([x + 0.1 for x in xs], zs, width=0.2, color="g", align="center", log=True)
  plt.show()
  #plot_line(jvm_vec, runtime_vec, "Numeric JVM Identifier", "Runtime in ms", "Dacapo %s on %s" % (benchmark, operating_system))
  
  return

# Extract just the average run time for each experiment
def parse_runtime_results(benchmark, benchmark_experiments):
  # Returns list of tuples of the form (num_jvms, mem_size, avg_runtime_ms)
  results = []
  for exp in benchmark_experiments:
    benchmark, num_jvms, mem_size = re.search("([a-zA-Z0-9]*)_(\d+)jvms_(\d+)MB$", exp).groups()
    num_jvms, mem_size = int(num_jvms), int(mem_size)

    # Get the average run time
    exp_path = "/".join([RESULTS_DIR, DACAPO_DIR, os_type, exp])
    cur_times = []

    for jvm in range(1, num_jvms+1):
      # Runtimes are logged in the stderr files
      filename = "/".join([exp_path, "stderr%d" % jvm])
      with open(filename, 'r') as f:
        contents = f.read()
        m = re.search("PASSED in (\d+) msec", contents)
        cur_times.append(int(m.groups()[0]))

    results.append((num_jvms, mem_size, float(sum(cur_times))/len(cur_times)))
  return results

def plot_line(x_vec, y_vec, xlabel, ylabel, title):
  plt.figure()
  plt.plot(x_vec, y_vec)
  plt.xlabel(xlabel)
  plt.ylabel(ylabel)
  plt.title(title)
  plt.show()

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

  for benchmark in DACAPO_BENCHMARKS[:1]:
    benchmark_experiments = filter(lambda s: re.match("^%s_.*" % benchmark, s), all_experiments)
    parse_benchmark(benchmark, benchmark_experiments, os_type)


