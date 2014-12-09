#!/usr/bin/env python

import argparse
import getpass
import os
import urllib
import subprocess
import shutil
import re
import datetime
import time
import atexit
import json

run_timestamp = time.time()

# Alias for loopback.
localIps = []
jmxPort = 8090
storagePort = 7000
sslStoragePort = 7010
nativeTrasportPort = 9042
rpcPort = 9160

def clearIps():
	global localIps
	localIps = []

def make_dir(mydir):
	if os.path.exists(mydir):
		shutil.rmtree(mydir)
	os.makedirs(mydir)

def do_setup():
	print '> Setting up Cassandra in directory ' + outdir
	print '> Working directory: ' + workdir
	print '>'

	download_path = workdir + '/downloads/' + cassandra_filename 
	if not os.path.exists(download_path):
		print '> Downloading Cassandra ' + cassandra_version
		download_url = cassandra_url.replace('${VERSION}', cassandra_version)
		print '> URL: ' + download_url
		make_dir(workdir + '/downloads')
		print '> TARGET FILE: ' + download_path
		print '> Downloading...'
		urllib.urlretrieve(download_url, download_path)
		print '> DONE'

		# Check this is actually a reasonable file, not an error page.
		if os.stat(download_path).st_size < 10000:
			print '[ERROR] Downloaded file too small -- check it is available ' + \
				'from the selected mirror.'
			os.remove(download_path)
			exit(1)
			
	else:
		print '> Use previously downloaded Cassandra package at ' + cassandra_filename
	print '>'

	print '> Creating Cassandra directory'
	make_dir(outdir)		
	p = subprocess.Popen(['tar', 'xfz', download_path], cwd=outdir, stdin=subprocess.PIPE)
	p.wait()
	print '> DONE'
	print '>'

# -------------------------------------------------------------------------------------------------

cassandra_instances = {}

def shutdown_cassandra_instances():
	print '> Shutting down Casssandra instances'
	print cassandra_instances
	for c in cassandra_instances.values():
		c['process'].terminate()
		#c['process'].kill()

	print '> Waiting for processes to terminate...'
	all_done = False
	while not all_done:
		all_done = True
		for c in cassandra_instances.values():
			if (c['process'].poll() == None):
				all_done = False
		time.sleep(0.01)
	print '> DONE'	

def do_start(args):
	clearIps()
	# Init all path variables.
	if hasattr(args, 'basedir')	:
		basedir = os.path.join(args.basedir, 'cassandra_cluster')
	else:
		basedir = os.path.join(os.getcwd(), 'cassandra_cluster')
	make_dir(basedir)
	print '> Running cassandra test on base dir ' + basedir
	# outdir = '/nscratch/' + getpass.getuser() + '/cassandra'
	workdir = os.path.join(basedir, 'work')
	rundir = workdir# + '/cassandra-' +  datetime.datetime.fromtimestamp(run_timestamp). \
	#	strftime('%Y-%m-%d-%H-%M-%S')

	instance_json = os.path.join(rundir, 'cassandra.json')

	# network_if = 'eth0'
	# Add all the ip alias. They may need to be pre-configured.
	for clusterIndex in xrange(args.num_clusters):
		for nodeIndex in xrange(args.num_nodes):
			localIps.append('127.0.0.' + str(nodeIndex + 1 + clusterIndex * args.num_nodes))

	# cassandra_filename = 'cassandra-' + cassandra_version + '.tar.gz'
	print args.cassandra_home
	cassandra_home = args.cassandra_home 

	local_dir = basedir
	saved_caches_dir = os.path.join(local_dir, 'saved_caches')
	commitlog_dir = os.path.join(local_dir, 'log')
	data_dir = os.path.join(local_dir, 'data')
	logfile = os.path.join(local_dir,'system.log')
	make_dir(saved_caches_dir)
	make_dir(commitlog_dir)
	make_dir(data_dir)
	make_dir(logfile)

	print '> Running cassandra on nodes: ' + ', '.join(localIps)

	confdir = os.path.join(basedir, 'config')
	print '> Configuration directory: ' + confdir
	make_dir(confdir)

	cyaml_fn = os.path.join(cassandra_home, 'conf/cassandra.yaml')
	cyamlenv_fn = os.path.join(cassandra_home, 'conf/cassandra-env.sh')
	print '> Reading configuration file ' + cyaml_fn
	with open(cyaml_fn, 'r') as fyaml:
		cassandra_yaml = fyaml.read()
	with open(cyamlenv_fn, 'r') as fyaml:
		cassandraenv_yaml = fyaml.read()

	for clusterIndex in xrange(args.num_clusters):
		clusterPrexfix = 'cluster' + str(clusterIndex)
		clusterSavedCachesDir = os.path.join(saved_caches_dir, clusterPrexfix)
		clusterDataDir = os.path.join(data_dir, clusterPrexfix)
		clusterLogDir = os.path.join(commitlog_dir, clusterPrexfix)
		make_dir(clusterSavedCachesDir)
		make_dir(clusterDataDir)
		make_dir(clusterLogDir)
		for nodeIndex in xrange(args.num_nodes):
			nodeName =  'node' + str(nodeIndex)
			nodeSavedCachesDir = os.path.join(clusterSavedCachesDir, nodeName)
			nodeDataDir = os.path.join(clusterDataDir, nodeName)
			nodeLogDir = os.path.join(clusterLogDir, nodeName)
			make_dir(nodeSavedCachesDir)
			make_dir(nodeDataDir)
			make_dir(nodeLogDir)
			myconfdir = os.path.join(confdir, clusterPrexfix, nodeName)
			print myconfdir
			print clusterPrexfix
			print '> Writing configuration for %s node ' % (clusterPrexfix) + str(nodeIndex) + ' (' + myconfdir + ')...' 
			make_dir(myconfdir)

			subprocess.call(['cp', '-r', cassandra_home + '/conf', myconfdir])

			# Change stack size for older versions of Cassandra (necessary to run)
			# subprocess.call(['sed', '-i', 's/Xss128k/Xss256k/', \
			# 	myconfdir + '/conf/cassandra-env.sh'])

			myip = localIps[clusterIndex * args.num_nodes + nodeIndex]
			my_commitlog_dir = os.path.join(commitlog_dir, clusterPrexfix, nodeName)
			my_saved_caches_dir = os.path.join(saved_caches_dir, clusterPrexfix, nodeName)
			my_data_dir = os.path.join(data_dir, clusterPrexfix, nodeName)

			# Change working directoreis
			my_cassandra_yaml = re.sub(re.compile('(cluster_name:).*$', flags=re.MULTILINE), \
				'\g<1> ' + 'Team OSv Cluster ' + str(clusterIndex), cassandra_yaml
				)

			my_cassandra_yaml = re.sub(re.compile('(commitlog_directory:).*$', flags=re.MULTILINE), \
				'\g<1> ' + my_commitlog_dir, my_cassandra_yaml
				)

			my_cassandra_yaml = re.sub(re.compile('(saved_caches_directory:).*$', flags=re.MULTILINE), \
				'\g<1> ' + my_saved_caches_dir, my_cassandra_yaml)

			my_cassandra_yaml = re.sub(re.compile('(data_file_directories:.*?\- ).*?$', flags=re.MULTILINE|re.DOTALL), \
			#my_cassandra_yaml = re.sub('(data_file_directories:).*?$', \
				'\g<1>' + my_data_dir, my_cassandra_yaml)

			my_cassandra_yaml = re.sub(re.compile('(listen_address:).*$', flags=re.MULTILINE), \
				'\g<1> ' + myip, my_cassandra_yaml
				)

			my_cassandra_yaml = re.sub(re.compile('(rpc_address:).*$', flags=re.MULTILINE), \
				'\g<1> ' + myip, my_cassandra_yaml
				)

			# my_cassandra_yaml = re.sub('(storage_port:).*$', \
			# 	'\g<1> ' + str(storagePort + nodeIndex), my_cassandra_yaml, \
			# 	flags=re.MULTILINE)

			# my_cassandra_yaml = re.sub('(ssl_storage_port:).*$', \
			# 	'\g<1> ' + str(sslStoragePort + nodeIndex), my_cassandra_yaml, \
			# 	flags=re.MULTILINE)

			# my_cassandra_yaml = re.sub('(native_transport_port:).*$', \
			# 	'\g<1> ' + str(nativeTrasportPort + nodeIndex), my_cassandra_yaml, \
			# 	flags=re.MULTILINE)

			# my_cassandra_yaml = re.sub('(rpc_port:).*$', \
			# 	'\g<1> ' + str(rpcPort + nodeIndex), my_cassandra_yaml, \
			# 	flags=re.MULTILINE)

			# my_cassandra_yaml = re.sub('# (broadcast_rpc_address:).*$', \
			# '\g<1> ' + 'myIp', my_cassandra_yaml, \
			# flags=re.MULTILINE)

			# Update seeds
			seeds_string = ','.join(localIps[clusterIndex * args.num_nodes : args.num_nodes * (clusterIndex + 1)])
			#seeds_string = localIps[0]
			my_cassandra_yaml = re.sub(re.compile('(- seeds:).*$',flags=re.MULTILINE), \
				'\g<1> "' + seeds_string + '"', my_cassandra_yaml
				)

			with open(myconfdir + '/conf/cassandra.yaml', 'w') as fyaml:
				fyaml.write(my_cassandra_yaml)

			my_cassandraenv_yaml = re.sub(re.compile('^(JMX_PORT=).*$', flags=re.MULTILINE), \
				'\g<1>"' + str(jmxPort + nodeIndex + clusterIndex * args.num_nodes) + '"', cassandraenv_yaml)

			with open(myconfdir + '/conf/cassandra-env.sh', 'w') as fyaml:
				fyaml.write(my_cassandraenv_yaml)


		print '> DONE set up nodes conf for cluster ' + str(clusterIndex)

	print '> Launching Cassandra clusters and nodes'
	print '>'
	print '> Output redirected to ' + rundir
	print '>'

	for clusterIndex in xrange(args.num_clusters):
		clusterPrexfix = 'cluster' + str(clusterIndex)
		for nodeIndex in xrange(args.num_nodes):
			print '> Launching Cassandra instance on ' + clusterPrexfix + ' node ' + str(nodeIndex)
			nodeName = 'node' + str(nodeIndex)
			myconfdir = os.path.join(confdir, clusterPrexfix, nodeName, 'conf')

			# srun_cmd = ['bash', 'run_cassandra.sh']
			srun_cmd = [os.path.join(cassandra_home, 'bin/cassandra'), '-f']

			myJmxPort = str(jmxPort + nodeIndex)
			print myJmxPort
			myenv = {'CASSANDRA_HOME': cassandra_home, 'CASSANDRA_CONF': myconfdir, 
			'JVM_OPTS':'-Xss256k'}
			if hasattr(args, 'heap'):
				myenv.update({'MAX_HEAP_SIZE':args.heap, 'HEAP_NEWSIZE':args.young})
			#	'JMX_PORT' : myJmxPort}
			myenv.update(os.environ)

			myrundir = os.path.join(rundir, clusterPrexfix, nodeName)
			make_dir(myrundir)
			myoutfile = myrundir + '/stdout'
			myerrfile = myrundir + '/stderr'

			fout = open(myoutfile, 'w')
			ferr = open(myerrfile, 'w')
			p = subprocess.Popen(srun_cmd, stdout=fout, stderr=ferr, env=myenv)
			cassandra_instances['node' + str(nodeIndex)] = {'process': p, 'out': myoutfile, 'err': myerrfile, 'pid':p.pid}

	# When exiting, make sure all children are terminated cleanly
	#if not hasattr(args, 'nosleep'):
	print cassandra_instances
	print '>'
	print '> Waiting for all nodes to finish starting up...'
	unfinished_nodes = cassandra_instances.keys()

	while unfinished_nodes:
		done_nodes = []
		for node in unfinished_nodes:
			with open(cassandra_instances[node]['out'], 'r') as fout:
				outdata = fout.read()	
			if re.search("Listening for thrift clients...", outdata) != None:
				done_nodes.append(node)
		for node in done_nodes:
			unfinished_nodes.remove(node)
		time.sleep(0.01)

	# Write a JSON description of the Cassandra instance that can be used by others.
	print '> Writing instance description to ' + instance_json
	cassandra_instance = { \
		'nodes' : localIps[:args.num_nodes], \
		'cli-path' : cassandra_home + '/bin/cassandra-cli', \
	}

	json_str = json.dumps(cassandra_instance)
	with open(instance_json, 'w') as fjson:
		fjson.write(json_str)	

	print '>'
	print '> ALL NODES ARE UP! TERMINATE THIS PROCESS TO SHUT DOWN CASSANDRA CLUSTER.'
	if hasattr(args, 'nosleep'):
		return cassandra_instances
	else:
		atexit.register(shutdown_cassandra_instances)
		while True:
			time.sleep(0.5)

# -------------------------------------------------------------------------------------------------
if __name__ == '__main__':
	parser = argparse.ArgumentParser(description='Run script for running multiple Cassandra nodes on a single machine.')
	parser.add_argument('action', nargs=1, help='the action to perform (setup|start|stop)')
	parser.add_argument('-c', '--cassandra-home', action="store", help='the path to the cassandra home)')
	parser.add_argument('-nc', "--num-clusters", action="store", default=1, type=int, help="the number of clusters to run")
	parser.add_argument('-nn', "--num-nodes", action="store", default=1, type=int, help="the number of nodes per cluster")

	args = parser.parse_args()

	print '> COMMAND = ' + str(args.action)

	print args

	if args.action[0] == 'setup':
		do_setup()
	elif args.action[0] == 'start':
		do_start(args)
	else:
		print '[ERROR] Unknown action \'' + args.action[0] + '\''
