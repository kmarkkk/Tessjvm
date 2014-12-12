#!/bin/bash

################################################################################
# This Bash script removes all the CPUs except the CPU 0 from the default CPU
# pool (Pool-0) and gives the CPUs to a newly created CPU pool.
#
# Author: Juan A. Colmenares <juancol@eecs.berkeley.edu>
################################################################################

DEFAULT_POOL="Pool-0"
NEW_CPUPOOL="GangSched-Pool"
MY_SCHED="gang"
#MY_SCHED="credit"

# VCPU 0 is the only allowed to Domain 0.
#sudo xl vcpu-set 0 0
# Domain 0's VCPU 0 can only run on CPU 0.
#sudo xl vcpu-pin 0 0 0

sudo service xencommons start

sudo xl cpupool-create name=\'$NEW_CPUPOOL\' sched=\'$MY_SCHED\'

sudo xl cpupool-cpu-remove $DEFAULT_POOL 1
sudo xl cpupool-cpu-remove $DEFAULT_POOL 2
sudo xl cpupool-cpu-remove $DEFAULT_POOL 3

sudo xl cpupool-cpu-add $NEW_CPUPOOL 1
sudo xl cpupool-cpu-add $NEW_CPUPOOL 2
sudo xl cpupool-cpu-add $NEW_CPUPOOL 3
