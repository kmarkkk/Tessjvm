#!/usr/bin/env python

import os
import matplotlib.pyplot as plt
import numpy as np
import re
import argparse
from collections import defaultdict, namedtuple

YCSB_DIR = 'cassandra_ycsb'
RESULT_METRICS = ['iter', 'ovr_runtime', 'ovr_thruput', 'r_latency', 'u_latency']
RESULT_LABELS = {'ovr_runtime': ('Average Overall Runtime', 'Time (ms)'),
                 'ovr_thruput': ('Average Overall Throughput', 'Operations per second'),
                 'r_latency': ('Read Operation Latency', u'Latency (\u03bcs)'),
                 'u_latency': ('Update Operation Latency', u'Latency \u03bcs)')}

YCSB_IterResult = namedtuple('YCSB_IterResult', RESULT_METRICS)

JVM_COUNTS = [1, 2, 4, 6, 8]

def plot(plot_type, experiments, os_type, results_dir, output_dir, output_extension):
  results = parse_results(experiments, os_type)
  avg_runtimes = []
  
  for jvm_count in JVM_COUNTS:
    iter_results = results[jvm_count]
    avg_runtimes.append(np.mean([getattr(iter_result, plot_type) for iter_result in iter_results]))

  plt.clf()
  plt.plot(JVM_COUNTS, avg_runtimes, '-d')
  plt.title(RESULT_LABELS[plot_type][0])
  plt.ylabel(RESULT_LABELS[plot_type][1])
  plt.xlabel("Number of JVMs")
  plt.xlim(0, max(JVM_COUNTS)+1)

  save_or_show_current(output_dir, plot_type, output_extension)

def parse_results(experiments, os_type):
  # Returns dictionary of the form: {num_jvms -> YCSB_Result}
  jvms_to_results = {}
  for exp in experiments:
    jvm_count = int(re.search("(\d+)jvms$", exp).groups()[0])
    exp_path = "/".join([results_dir, YCSB_DIR, os_type, exp])

    num_iterations = 5
    results = []
    for iteration in range(1, num_iterations+1):
      # Runtimes are logged in the stderr files on linux and stout files on xen
      if os_type == "xen":
        filename = "/".join([exp_path, "ycsbrunstdout%02d" % iteration])
      else:
        filename = "/".join([exp_path, "ycsbrunstdout%02d" % iteration])
      with open(filename, 'r') as f:
        contents = f.read()

      overall_runtime_ms = float(re.search("RunTime\(ms\), (\d+\.\d+)", contents).groups()[0])
      overall_throughput_ops_sec = float(re.search("Throughput\(ops/sec\), (\d+\.\d+)", contents).groups()[0])
      update_latency, read_latency, cleanup_latency = map(float, re.findall("AverageLatency\(us\), (\d+\.\d+)", contents))
      
      results.append(YCSB_IterResult(iteration, overall_runtime_ms, overall_throughput_ops_sec, update_latency, read_latency))
    jvms_to_results[jvm_count] = results
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
    for metric in RESULT_METRICS[1:]:
      plot(metric, experiments, cmdargs.xen, results_dir, cmdargs.outputdir, cmdargs.extension)
  else:
    plot(cmdargs.type, experiments, cmdargs.xen, results_dir, cmdargs.outputdir, cmdargs.extension)
    

