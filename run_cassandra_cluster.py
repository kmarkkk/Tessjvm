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

	print '> Waiting for processes to terminate...'
	all_done = True
	while not all_done:
		all_done = True
		for c in cassandra_instances.values():
			if (c['process'].poll() == None):
				all_done = False
		time.sleep(0.01)
	print '> DONE'	

def do_start(args):

	# Init all path variables.
	basedir = os.getcwd() + '/cassandra_cluster'
	make_dir(basedir)
	print '> Running cassandra test on base dir ' + basedir
	# outdir = '/nscratch/' + getpass.getuser() + '/cassandra'
	workdir = basedir + '/work'
	rundir = workdir + '/cassandra-' +  datetime.datetime.fromtimestamp(run_timestamp). \
		strftime('%Y-%m-%d-%H-%M-%S')

	instance_json = rundir + '/cassandra.json'

	# network_if = 'eth0'
	# Add all the ip alias. They may need to be pre-configured.
	for nodeIndex in xrange(args.num_nodes):
		localIps.append('127.0.0.' + str(nodeIndex + 1))

	# cassandra_filename = 'cassandra-' + cassandra_version + '.tar.gz'
	print args.cassandra_home
	cassandra_home = args.cassandra_home 

	local_dir = basedir
	saved_caches_dir = local_dir + '/saved_caches'
	commitlog_dir = local_dir + '/log'
	data_dir = local_dir + '/data'
	logfile = local_dir + '/system.log'

	print '> Running cassandra on nodes: ' + ', '.join(localIps[:args.num_nodes])

	confdir = basedir + '/config'
	print '> Configuration directory: ' + confdir
	make_dir(confdir)

	cyaml_fn = cassandra_home + '/conf/cassandra.yaml'
	cyamlenv_fn = cassandra_home + '/conf/cassandra-env.sh'
	print '> Reading configuration file ' + cyaml_fn
	with open(cyaml_fn, 'r') as fyaml:
		cassandra_yaml = fyaml.read()
	with open(cyamlenv_fn, 'r') as fyaml:
		cassandraenv_yaml = fyaml.read()

	for nodeIndex in xrange(args.num_nodes):
		nodeName = 'node' + str(nodeIndex)
		myconfdir = confdir + '/' + nodeName
		print '> Writing configuration for node ' + str(nodeIndex) + ' (' + myconfdir + ')...'
		make_dir(myconfdir)

		subprocess.call(['cp', '-r', cassandra_home + '/conf', myconfdir])

		# Change stack size for older versions of Cassandra (necessary to run)
		# subprocess.call(['sed', '-i', 's/Xss128k/Xss256k/', \
		# 	myconfdir + '/conf/cassandra-env.sh'])

		myip = localIps[nodeIndex]
		my_commitlog_dir = commitlog_dir + '/' + nodeName
		my_saved_caches_dir = saved_caches_dir + '/' + nodeName
		my_data_dir = data_dir + '/' + nodeName

		# Change working directoreis
		my_cassandra_yaml = re.sub(re.compile('(commitlog_directory:).*$', flags=re.MULTILINE), \
			'\g<1> ' + my_commitlog_dir, cassandra_yaml
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
		seeds_string = ','.join(localIps[:args.num_nodes])
		#seeds_string = localIps[0]
		my_cassandra_yaml = re.sub(re.compile('(- seeds:).*$',flags=re.MULTILINE), \
			'\g<1> "' + seeds_string + '"', my_cassandra_yaml
			)

		with open(myconfdir + '/conf/cassandra.yaml', 'w') as fyaml:
			fyaml.write(my_cassandra_yaml)

		my_cassandraenv_yaml = re.sub(re.compile('^(JMX_PORT=).*$', flags=re.MULTILINE), \
			'\g<1>"' + str(jmxPort + nodeIndex) + '"', cassandraenv_yaml)

		with open(myconfdir + '/conf/cassandra-env.sh', 'w') as fyaml:
			fyaml.write(my_cassandraenv_yaml)


	print '> DONE set up nodes conf'
	print '>'
	print '> Launching Cassandra nodes'
	print '>'
	print '> Output redirected to ' + rundir
	print '>'
	# Create symlink for latest run
	subprocess.call(['ln', '-s', '-f', rundir, workdir + '/latest'])

	for nodeIndex in xrange(args.num_nodes):
		print '> Launching Cassandra instance on node ' + str(nodeIndex)
		myconfdir = confdir + '/node' + str(nodeIndex) + '/conf'

		srun_cmd = ['bash', 'run_cassandra.sh']

		myJmxPort = str(jmxPort + nodeIndex)
		myenv = {'CASSANDRA_HOME': cassandra_home, 'CASSANDRA_CONF': myconfdir}
		#	'JMX_PORT' : myJmxPort}
		myenv.update(os.environ)

		myrundir = rundir + '/node' + str(nodeIndex)
		make_dir(myrundir)
		myoutfile = myrundir + '/stdout'
		myerrfile = myrundir + '/stderr'

		fout = open(myoutfile, 'w')
		ferr = open(myerrfile, 'w')
		p = subprocess.Popen(srun_cmd, stdout=fout, stderr=ferr, env=myenv)
		cassandra_instances['node' + str(nodeIndex)] = {'process': p, 'out': myoutfile, 'err': myerrfile}

	# When exiting, make sure all children are terminated cleanly
	atexit.register(shutdown_cassandra_instances)

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
	while True:
		time.sleep(0.5)

# -------------------------------------------------------------------------------------------------

parser = argparse.ArgumentParser(description='Run script for running multiple Cassandra nodes on a single machine.')
parser.add_argument('action', nargs=1, help='the action to perform (setup|start|stop)')
parser.add_argument('-c', '--cassandra-home', action="store", help='the path to the cassandra home)')
parser.add_argument('-n', "--num-nodes", action="store", default=1, type=int, help="the number of nodes to run")

args = parser.parse_args()

print '> COMMAND = ' + str(args.action)

print args

if args.action[0] == 'setup':
	do_setup()
elif args.action[0] == 'start':
	do_start(args)
else:
	print '[ERROR] Unknown action \'' + args.action[0] + '\''
