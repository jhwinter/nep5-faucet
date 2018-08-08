#!/bin/bash

# Spylse Inc. 2018


CONTAINER=$(docker ps -aqf name=nep5-faucet)

if [ -n "$CONTAINER" ]; then
	echo "Stopping container named nep5-faucet"
	docker stop nep5-faucet 1>/dev/null
	echo "Removing container named nep5-faucet"
	docker rm nep5-faucet 1>/dev/null
fi

echo "Starting container..."
docker run --detach \
--name nep5-faucet \
--network bridge \
--publish 8080:8080/tcp \
nep5-faucet python3 /app/faucet.py
