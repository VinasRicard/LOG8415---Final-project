#!/bin/bash

# Install Docker and set up environment
sudo apt-get update
sudo apt-get install -y docker.io

# Deploy MySQL containers on each EC2 instance
ssh -i "path/to/key.pem" ubuntu@manager-instance "docker run -d mysql:5.7"
ssh -i "path/to/key.pem" ubuntu@worker-instance-1 "docker run -d mysql:5.7"
ssh -i "path/to/key.pem" ubuntu@worker-instance-2 "docker run -d mysql:5.7"

# Run benchmarking
python3 benchmark.py
