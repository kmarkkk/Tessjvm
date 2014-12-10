#!/usr/bin/env python

import os
import matplotlib.pyplot as plt
import numpy as np
import re
import argparse
import json
from collections import defaultdict
from scipy.stats import cumfreq

DACAPO_DIR='dacapo'
DACAPO_BENCHMARKS = ['avrora', 'h2', 'jython', 'luindex', 'lusearch', 'xalan']
MEM_SIZES = {'avrora': [64, 128, 256],
             'h2': [],
             'jython': [64, 128, 256],
             'luindex': [64, 128, 256],
             'lusearch': [64, 128, 256],
             'xalan': [64, 128, 256]
            }
JVM_COUNTS = {'avrora': [1, 2, 4, 8, 16, 32],
              'h2': [],
              'jython': [1, 2, 4, 8, 16],
              'luindex': [1, 2, 4, 8, 16, 24, 32],
              'lusearch': [1, 2, 4, 8, 16, 32],
              'xalan': [1, 2, 4, 8, 16, 24, 32]
              }
with open('dacapo_convergences.json', 'r') as f:
  CONVERGENCES = json.load(f)

def plot_runtimes(benchmark, benchmark_experiments, os_type, results_dir, output_dir, output_extension):
  print "Parsing and plotting runtime results for %d %s experiments...\n" % (len(benchmark_experiments), benchmark)

  runtime_results = parse_runtime_results(benchmark, benchmark_experiments, os_type)

  if len(runtime_results) == 0:
    print "Not enough results found for %s. Skipping..." % benchmark
    return

  # Initialize values we'll need for the x-axis
  memory_sizes = MEM_SIZES[benchmark]
  xs = range(1,len(memory_sizes)+1)
  bar_width, offset = 0.1, -0.2 # These offset the bar series from each other. Designed for 5 bar series.
  color_iter = iter(['b', 'g', 'r', 'c', 'm', 'y', '#989898']) # Colors for successive bar series

  plt.clf()
  ax = plt.subplot(111)
  # Add an extra entry to the x-axis so we can see all of the experiments
  ax.set_xlim(0, len(memory_sizes)+1)

  for jvm_count, memsize_to_results in sorted(runtime_results.iteritems(), key=lambda t: t[0]):
    avg_runtimes = [memsize_to_results[memsize] for memsize in memory_sizes]
    ax.bar([x + offset for x in xs], avg_runtimes, width=bar_width, color=next(color_iter), align="center", label="%d JVMs" % jvm_count)
    offset += bar_width

  # Apply labels and bounds
  plt.title("%s Mean Run Times" % benchmark)
  plt.ylabel("Runtime (ms)")
  plt.xlabel("Memory Size")
  plt.xticks(xs, map(lambda v: str(v)+"MB", memory_sizes))
  # Move legend to the right
  box = ax.get_position()
  ax.set_position([box.x0, box.y0, box.width * 0.85, box.height])
  ax.legend(loc='center left', bbox_to_anchor=(1, 0.5))

  save_or_show_current(output_dir, 'runtimes', benchmark, output_extension)

def plot_cdfs(benchmark, benchmark_experiments, os_type, results_dir, output_dir, output_extension):
  print "Parsing and plotting runtime results for %d %s experiments...\n" % (len(benchmark_experiments), benchmark)

  runtime_results = parse_runtime_results(benchmark, benchmark_experiments, os_type, False)

  if len(runtime_results) == 0:
    print "Not enough results found for %s. Skipping..." % benchmark
    return

  keyed_by_mem_size = defaultdict(list)
  for jvm_count, memsize_to_results in sorted(runtime_results.iteritems(), key=lambda t: t[0]):
    for memsize, runtimes in memsize_to_results.iteritems():
      keyed_by_mem_size[memsize].append((jvm_count, runtimes))

  for mem_size, jvm_to_runtimes in sorted(keyed_by_mem_size.iteritems(), key=lambda t: t[0]):
    plt.clf()
    ax = plt.subplot(111)
    longest_time = max(reduce(lambda x,y: x + y, [t[1] for t in jvm_to_runtimes]))
    shortest_time = min(reduce(lambda x,y: x + y, [t[1] for t in jvm_to_runtimes]))
    for jvm_count, runtime_list in jvm_to_runtimes:
      cum_freqs, ll, binsize, xp = cumfreq(runtime_list, numbins=len(runtime_list))
      normed_cum_freqs = map(lambda x: x/max(cum_freqs), cum_freqs)
      padded_x = [shortest_time*0.8, min(runtime_list)] + sorted(runtime_list) + [longest_time*1.1]
      padded_y = [0, 0] + normed_cum_freqs + [1]
      ax.plot(padded_x, padded_y, label="%d JVMs" % jvm_count)

    # Apply labels and bounds
    plt.title("%s Cumulative Distribution Function (%d MB Heap)" % (benchmark, mem_size))
    plt.ylabel("Fraction of Jobs Completed")
    plt.xlabel("Time (ms)")
    plt.xlim(shortest_time*0.8, longest_time*1.1)
    plt.ylim(-0.025, 1.025)
    # Move legend to the right1
    box = ax.get_position()
    ax.set_position([box.x0, box.y0, box.width * 0.85, box.height])
    ax.legend(loc='center left', bbox_to_anchor=(1, 0.5))

    save_or_show_current(output_dir, 'cdfs', benchmark, output_extension, suffix='%03dMB' % mem_size)

def plot_slowdowns(benchmark, benchmark_experiments, os_type, results_dir, output_dir, output_extension):
  print "Parsing and plotting runtime slowdowns for %d %s experiments...\n" % (len(benchmark_experiments), benchmark)

  runtime_results = parse_runtime_results(benchmark, benchmark_experiments, os_type)

  if len(runtime_results) == 0:
    print "Not enough results found for %s. Skipping..." % benchmark
    return

  plt.clf()
  ax = plt.subplot(111)

  # We're going to kind of invert the dictionary so it maps {mem_size -> [(jvm_count, avg_runtime),...]}
  keyed_by_mem_size = defaultdict(list)
  for jvm_count, memsize_to_results in sorted(runtime_results.iteritems(), key=lambda t: t[0]):
    for memsize, avg_runtime in memsize_to_results.iteritems():
      keyed_by_mem_size[memsize].append((jvm_count, avg_runtime))

  max_slowdown = 0
  for mem_size, runtime_list in sorted(keyed_by_mem_size.iteritems(), key=lambda t: t[0]):
    jvms = [t[0] for t in runtime_list]
    slowdowns = [float(runtime)/runtime_list[0][1] for runtime in [t[1] for t in runtime_list]]
    max_slowdown = max([max_slowdown] + slowdowns)
    ax.plot(jvms, slowdowns, '--d', label="%d MB" % mem_size)

  # Apply labels and bounds
  plt.title("%s Runtime Slowdown with Increasing JVM Count" % benchmark)
  plt.ylabel("Slowdown")
  plt.xlabel("Number of JVMs")
  plt.xlim(0, max(jvms)*1.1)
  plt.ylim(0, max_slowdown*1.1)

  plt.legend(loc='upper left')

  save_or_show_current(output_dir, 'slowdowns', benchmark, output_extension)

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

def parse_runtime_results(benchmark, benchmark_experiments, os_type, aggregate=True):
  # Returns dictionary of the form: {num_jvms -> {mem_size -> avg_runtime_ms}}
  jvms_to_results = defaultdict(lambda : defaultdict(int))
  for exp in benchmark_experiments:
    benchmark, num_jvms, mem_size = re.search("([a-zA-Z0-9]*)_(\d+)jvms_(\d+)MB$", exp).groups()
    num_jvms, mem_size = int(num_jvms), int(mem_size)

    exp_path = "/".join([results_dir, DACAPO_DIR, os_type, exp])

    exp_times = []
    for jvm in range(1, num_jvms+1):
      # Runtimes are logged in the stderr files on linux and stout files on xen
      if os_type == "xen":
        filename = "/".join([exp_path, "stdout%02d" % jvm])
      else:
        filename = "/".join([exp_path, "stderr%02d" % jvm])
      with open(filename, 'r') as f:
        contents = f.read()
      all_per_jvm_times = map(int, re.findall("%s .* in (\d+) msec" % benchmark, contents))
      index_start = CONVERGENCES[benchmark]
      index_end = index_start + 5
      per_jvm_times = all_per_jvm_times[index_start:index_end]
      if len(per_jvm_times) < 5:
        print "Unable to find 5 valid runtimes for %s" % exp
        continue
      # We'll use the sum
      if aggregate:
        exp_times.append(np.sum(per_jvm_times))
      else:
        exp_times += per_jvm_times
    # To find standard deviation for each experiment, call "np.std(exp_times)" here
    if aggregate:
      jvms_to_results[num_jvms][mem_size] = np.mean(exp_times)
    else:
      jvms_to_results[num_jvms][mem_size] = exp_times

  return jvms_to_results

def parse_gc(benchmark, benchmark_experiments, os_type):
  # Returns dictionary of the form: {num_jvms -> {mem_size -> (minior avg_runtime_s, major avg_runtime_s}}
  jvms_to_results = defaultdict(lambda : defaultdict(int))
  for exp in benchmark_experiments:
    benchmark, num_jvms, mem_size = re.search("([a-zA-Z0-9]*)_(\d+)jvms_(\d+)MB$", exp).groups()
    num_jvms, mem_size = int(num_jvms), int(mem_size)

    exp_path = "/".join([results_dir, DACAPO_DIR, os_type, exp])

    exp_times = []
    for jvm in range(1, num_jvms+1):
      # Runtimes are logged in the stderr files on linux and stout files on xen
      if os_type == "xen":
        filename = "/".join([exp_path, "stdout%02d" % jvm])
      else:
        filename = "/".join([exp_path, "stderr%02d" % jvm])
      with open(filename, 'r') as f:
        contents = f.read()
      index_start = CONVERGENCES[benchmark] + 1
      index_end = index_start + 4
      try:
        contents = re.findall(r"starting warmup %d ([\s\S]*) completed warmup %d" % (index_start, index_end), contents)[0]
      except:
        print jvm
        print "Unable to find 5 valid runtimes for %s" % exp
        continue
      major_gc_per_jvm_times = map(float, re.findall(r"\[Full GC.*, ([.\d]*) secs", contents))
      minor_gc_per_jvm_times = map(float, re.findall(r"\[GC.*, ([.\d]*) secs", contents))
      # We'll use the sum
      exp_times.append((np.sum(major_gc_per_jvm_times), np.sum(minor_gc_per_jvm_times)))
    # To find standard deviation for each experiment, call "np.std(exp_times)" here
    major_times, minor_times = zip(*exp_times)
    jvms_to_results[num_jvms][mem_size] = (np.mean(major_times), np.mean(minor_times))

  return jvms_to_results

def save_or_show_current(output_dir, subdirectory, benchmark, output_extension, suffix=None):
  if output_dir:
    dest_dir = "%s/%s" % (output_dir, subdirectory)
    if not os.path.exists(dest_dir):
      os.makedirs(dest_dir)
    if suffix:
      plt.savefig("%s/%s_%s.%s" % (dest_dir, benchmark, suffix, output_extension))
    else:
      plt.savefig("%s/%s.%s" % (dest_dir, benchmark, output_extension))
  else:
    plt.show()

if __name__ == "__main__":
  parser = argparse.ArgumentParser(prog='run')
  parser.add_argument("-t", "--type", action="store", default='runtime', help="name the type of graph you wish to generate")
  parser.add_argument("-x", "--xen", action="store_const", default='linux', const='xen', help="enable to parse xen results instead of linux")
  parser.add_argument("-r", "--resultsdir", action="store", help="name of the directory containing the results")
  parser.add_argument("-o", "--outputdir", action="store", default=False, help="provide a directory to save the experiment results into")
  parser.add_argument("-e", "--extension", action="store", default="eps", help="if -o is provided, this is the file type extension for the graph images")
  parser.add_argument("-b", "--benchmark", action="store", default=False, help="parse a specific benchmark")
  cmdargs = parser.parse_args()
  
  results_dir = cmdargs.resultsdir

  experiments_dir = '/'.join([results_dir, DACAPO_DIR, cmdargs.xen])
  all_experiments = os.listdir(experiments_dir)

  if cmdargs.type == 'runtime':
    plotter = plot_runtimes
  elif cmdargs.type == 'slowdown':
    plotter = plot_slowdowns
  elif cmdargs.type == 'gc':
    plotter = plot_gc
  elif cmdargs.type == 'cdf':
    plotter= plot_cdfs
  else:
    raise ValueError("Unknown graph type")

  if cmdargs.benchmark:
    benchmark_experiments = filter(lambda s: re.match("^%s_.*" % cmdargs.benchmark, s), all_experiments)
    plotter(cmdargs.benchmark, benchmark_experiments, cmdargs.xen, results_dir, cmdargs.outputdir, cmdargs.extension)
  else:
    for benchmark in DACAPO_BENCHMARKS:
      benchmark_experiments = filter(lambda s: re.match("^%s_.*" % benchmark, s), all_experiments)
      plotter(benchmark, benchmark_experiments, cmdargs.xen, results_dir, cmdargs.outputdir, cmdargs.extension)


