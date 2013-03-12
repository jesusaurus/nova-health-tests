#!/usr/bin/env bash

echo "*********************************************************************"
echo "Begin Nova Health Checks"
echo "*********************************************************************"

# This script exits on an error so that errors don't compound and you see
# only the first error that occured.
set -o errexit

# Print the commands being run so that we can see the command that triggers
# an error.  It is also useful for following allowing as the install occurs.
set -o xtrace


# Settings
# ========

# Keep track of the current directory
SCRIPT_DIR=$(cd $(dirname "$0") && pwd)
TOP_DIR=$(cd $SCRIPT_DIR/..; pwd)
UBUNTU_IMAGE=67074
XSMALL_FLAVOR=100
ACTIVE_TIMEOUT=500
INSTANCE_NAME='test'

nova boot $INSTANCE_NAME --image $UBUNTU_IMAGE --flavor $XSMALL_FLAVOR

if ! timeout $ACTIVE_TIMEOUT sh -c "while ! nova list | grep $INSTANCE_NAME | grep ACTIVE; do sleep 1; done"; then
    echo "Volume $INSTANCE_NAME not created"
    exit 1
fi

nova list

nova delete $INSTANCE_NAME
if ! timeout $ACTIVE_TIMEOUT sh -c "while nova show $INSTANCE_NAME; do sleep 1; done"; then
    echo "server didn't terminate!"
    exit 1
fi

set +o xtrace
echo "*********************************************************************"
echo "SUCCESS: End DevStack Exercise: $0"
echo "*********************************************************************"