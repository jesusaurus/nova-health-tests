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
ACTIVE_TIMEOUT=500
INSTANCE_NAME='test'

# Boot this image, use first bare image if unset
DEFAULT_IMAGE_NAME=${DEFAULT_IMAGE_NAME:-precise}

DEFAULT_FLAVOR_NAME=${DEFAULT_FLAVOR_NAME:-small}

# List the images available
glance image-list

# Grab the id of the image to launch
IMAGE=$(glance image-list | egrep " $DEFAULT_IMAGE_NAME " | awk '{print $2}')
echo ${IMAGE:?Failure getting image $DEFAULT_IMAGE_NAME.}

# List the flavors available
nova flavor-list

# Grab the id of the flavor to launch
FLAVOR=$(nova flavor-list | egrep "$DEFAULT_FLAVOR_NAME" | awk '{print $2}')
echo ${FLAVOR:?Failure getting flavor $DEFAULT_FLAVOR_NAME.}


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