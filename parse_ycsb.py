#!/usr/bin/env python

import os
import matplotlib.pyplot as plt
import numpy as np
import re
import argparse
from collections import defaultdict, namedtuple

YCSB_DIR = 'cassandra_ycsb'
RESULT_METRICS = ['ovr_runtime', 'ovr_thruput', 'r_latency', 'u_latency']
RESULT_LABELS = {'ovr_runtime': ('Average Overall Runtime', 'Time (ms)'),
                 'ovr_thruput': ('Average Overall Throughput', 'Operations per second'),
                 'r_latency': ('Read Operation Latency', u'Latency (\u03bcs)'),
                 'u_latency': ('Update Operation Latency', u'Latency \u03bcs)')}

YCSB_Result = namedtuple('YCSB_Result', RESULT_METRICS)

JVM_COUNTS = [1, 2, 4]

def plot(plot_type, experiments, os_type, results_dir, output_dir, output_extension):
  ycsb_results = parse_results(experiments, os_type)

  metric_values = []  
  plt.clf()
  for jvm_count in JVM_COUNTS:
    ycsb_result = ycsb_results[jvm_count]
    metric_values.append(getattr(ycsb_result, plot_type))
  
  plt.plot(JVM_COUNTS, metric_values, '-d')
  plt.title(RESULT_LABELS[plot_type][0])
  plt.ylabel(RESULT_LABELS[plot_type][1])
  plt.xlabel("Number of JVMs")
  plt.xlim(0, max(JVM_COUNTS)+1)
  plt.ylim(0, max(metric_values)*1.1)

  save_or_show_current(output_dir, plot_type, output_extension)

def parse_results(experiments, os_type):
  jvms_to_results = defaultdict(list)
  for exp in experiments:
    jvm_count = int(re.search("(\d+)jvms$", exp).groups()[0])
    exp_path = "/".join([results_dir, YCSB_DIR, os_type, exp])
    per_jvm_averages = defaultdict(list)
    for jvm in range(1, jvm_count+1):
      num_iterations = 5
      iter_results = defaultdict(list)
      for iteration in range(1, num_iterations+1):
        # Runtimes are logged in the stderr files on linux and stout files on xen
        if os_type == "xen":
          filename = "/".join([exp_path, "ycsbrunstdout%02d%02d" % (jvm, iteration)])
        else:
          filename = "/".join([exp_path, "ycsbrunstdout%02d%02d" % (jvm, iteration)])
        with open(filename, 'r') as f:
          contents = f.read()
        # Store results from each iteration this JVM ran
        iter_results['ovr_runtime'].append(float(re.search("RunTime\(ms\), (\d+\.\d+)", contents).groups()[0]))
        iter_results['ovr_thruput'].append(float(re.search("Throughput\(ops/sec\), (\d+\.\d+)", contents).groups()[0]))
        u_latency, r_latency, cleanup_latency = map(float, re.findall("AverageLatency\(us\), (\d+\.\d+)", contents))
        iter_results['u_latency'].append(u_latency)
        iter_results['r_latency'].append(r_latency)
      # Record average across iterations for each JVM instance
      for metric in RESULT_METRICS:
        per_jvm_averages[metric].append(np.mean(iter_results[metric]))
    # Record average across JVM instances for this experiment
    cross_jvm_averages = []
    for metric in RESULT_METRICS:
      cross_jvm_averages.append(np.mean(per_jvm_averages[metric]))
    jvms_to_results[jvm_count] = YCSB_Result(*cross_jvm_averages)
  return jvms_to_results

def plot_gc(benchmark, benchmark_experiments, os_type, results_dir, output_dir, output_extension):
  print "Parsing and plotting gc slowdowns for %d %s experiments...\n" % (len(benchmark_experiments), benchmark)

  runtime_results = parse_gc(benchmark, benchmark_experiments, os_type)

  if len(runtime_results) == 0:
    print "Not enough results found for %s. Skipping..." % benchmark
    return

  plt.clf()
  ax = plt.subplot(111)

  GC_TYPE, GC_INDEX = "Minor", 1

  # We're going to kind of invert the dictionary so it maps {mem_size -> [(jvm_count, avg_runtime),...]}
  keyed_by_mem_size = defaultdict(list)
  for jvm_count, memsize_to_results in sorted(runtime_results.iteritems(), key=lambda t: t[0]):
    for memsize, avg_runtime in memsize_to_results.iteritems():
      keyed_by_mem_size[memsize].append((jvm_count, avg_runtime[GC_INDEX]))

  max_slowdown = 0
  for mem_size, runtime_list in sorted(keyed_by_mem_size.iteritems(), key=lambda t: t[0]):
    jvms = [t[0] for t in runtime_list]
    slowdowns = [float(runtime)/runtime_list[0][1] for runtime in [t[1] for t in runtime_list]]
    max_slowdown = max(max_slowdown + slowdowns)
    ax.plot(jvms, slowdowns, '--d', label="%d MB" % mem_size)

  # Apply labels and bounds
  plt.title("%s %s GC Runtime Slowdown with Increasing JVM Count" % (benchmark, GC_TYPE))
  plt.ylabel("Slowdown")
  plt.xlabel("Number of JVMs")
  plt.xlim(0, max(jvms)*1.1)
  plt.ylim(0, max_slowdown*1.1)
  plt.legend(loc='upper left')

  save_or_show_current(output_dir, 'slowdowns', benchmark, output_extension)

def parse_gc(experiments, os_type):
  # Returns dictionary of the form: {num_jvms -> {mem_size -> (minior avg_runtime_s, major avg_runtime_s}}
  jvms_to_results = defaultdict(lambda : defaultdict(int))
  for exp in experiments:
    jvm_count = int(re.search("(\d+)jvms$", exp).groups()[0])
    exp_path = os.path.join(results_dir, YCSB_DIR, os_type, exp)
    num_iterations = 5
    results = []
    exp_times = []
    for jvm in xrange(1, jvm_count+1):
      # Runtimes are logged in the stderr files on linux and stout files on xen
      if os_type == "xen":
        filename = os.path.join(exp_path, "stdout%02d" % jvm)
      else:
        filename = os.path.join(exp_path, "stderr%02d" % jvm)
      with open(filename, 'r') as f:
        contents = f.read()

      major_gc_per_jvm_times = map(float, re.findall(r"\[Full GC.*, ([.\d]*) secs", contents))
      minor_gc_per_jvm_times = map(float, re.findall(r"\[GC.*, ([.\d]*) secs", contents))
      # We'll use the sum
      exp_times.append((np.sum(major_gc_per_jvm_times), np.sum(minor_gc_per_jvm_times)))
    # To find standard deviation for each experiment, call "np.std(exp_times)" here
    major_times, minor_times = zip(*exp_times)
    jvms_to_results[jvm_count] = (np.mean(major_times), np.mean(minor_times))
  return jvms_to_results

def save_or_show_current(output_dir, plot_type, output_extension):
  if output_dir:
    dest_dir = "%s/ycsb" % output_dir
    if not os.path.exists(dest_dir):
      os.makedirs(dest_dir)
    plt.savefig("%s/%s.%s" % (dest_dir, plot_type, output_extension))
  else:
    plt.show()

if __name__ == "__main__":
  parser = argparse.ArgumentParser(prog='run')
  parser.add_argument("-t", "--type", action="store", default='all', help="name the type of graph you wish to generate")
  parser.add_argument("-x", "--xen", action="store_const", default='linux', const='xen', help="enable to parse xen results instead of linux")
  parser.add_argument("-r", "--resultsdir", action="store", help="name of the directory containing the results")
  parser.add_argument("-o", "--outputdir", action="store", default=False, help="provide a directory to save the experiment results into")
  parser.add_argument("-e", "--extension", action="store", default="eps", help="if -o is provided, this is the file type extension for the graph images")
  cmdargs = parser.parse_args()

  results_dir = cmdargs.resultsdir

  experiments_dir = '/'.join([results_dir, YCSB_DIR, cmdargs.xen])
  all_experiments = os.listdir(experiments_dir)

  experiments = filter(lambda s: re.match(".*jvms$", s), all_experiments)
  if cmdargs.type == 'all':
    for metric in RESULT_METRICS:
      plot(metric, experiments, cmdargs.xen, results_dir, cmdargs.outputdir, cmdargs.extension)
  elif cmdargs.type == 'gc':
    parse_gc(experiments, cmdargs.xen)
  else:
    plot(cmdargs.type, experiments, cmdargs.xen, results_dir, cmdargs.outputdir, cmdargs.extension)


