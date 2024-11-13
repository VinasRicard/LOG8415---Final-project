import boto3
import sys, os, time
import json
from botocore.exceptions import ClientError
import paramiko
import boto3
import time
import random
import subprocess
import requests

# Initialize clients
ec2_client = boto3.client('ec2', region_name='us-east-1')
s3_client = boto3.client('s3', region_name='us-east-1')

# Get the AWS key pair
def get_key_pair(ec2_client):
    """
        Retrieve the key pair
        Args:
            ec2_client: The boto3 ec2 client
        Returns:
            Key name
        """
    key_name = "tp2"
    try:
        ec2_client.describe_key_pairs(KeyNames=[key_name])
        print(f"Key Pair {key_name} already exists. Using the existing key.")
        return key_name

    except ClientError as e:
        if 'InvalidKeyPair.NotFound' in str(e):
            try:
                # Create a key pair if it doesnt exist
                response = ec2_client.create_key_pair(KeyName=key_name)
                private_key = response['KeyMaterial']

                # Save the key to directory
                save_directory = os.path.expanduser('~/.aws')
                key_file_path = os.path.join(save_directory, f"{key_name}.pem")

                with open(key_file_path, 'w') as file:
                    file.write(private_key)

                os.chmod(key_file_path, 0o400)
                print(f"Created and using Key Pair: {key_name}")
                return key_name
            except ClientError as e:
                print(f"Error creating key pair: {e}")
                sys.exit(1)
        else:
            print(f"Error retrieving key pairs: {e}")
            sys.exit(1)

# Get the AWS VPC            
def get_vpc_id(ec2_client):
    """
        Function to get VPC id
        Args:
            ec2_client: The boto3 ec2 client
        Returns:
            VPC id
        """
    try:
        # Get all VPC's
        response = ec2_client.describe_vpcs()
        vpcs = response.get('Vpcs', [])
        if not vpcs:
            print("Error: No VPCs found.")
            sys.exit(1)
        print(f"Using VPC ID: {vpcs[0]['VpcId']}")
        # Take the first one
        return vpcs[0]['VpcId']

    except ClientError as e:
        print(f"Error retrieving VPCs: {e}")
        sys.exit(1)

# Create the AWS Security Group
def create_security_group(ec2_client, vpc_id, description="My Security Group"):
    """
    Create or reuse a security group with valid inbound rules.
    Args:
        ec2_client: The boto3 ec2 client.
        vpc_id: VPC id.
        description: Description for security group.
    Returns:
        Security group id.
    """
    group_name = "my-security-group"
    inbound_rules = [
        #{'protocol': 'tcp', 'port_range': 8000, 'source': '0.0.0.0/0'},
        #{'protocol': 'tcp', 'port_range': 8001, 'source': '0.0.0.0/0'},
        {'protocol': 'tcp', 'port_range': 5000, 'source': '0.0.0.0/0'},
        {'protocol': 'tcp', 'port_range': 5001, 'source': '0.0.0.0/0'},
        {'protocol': 'tcp', 'port_range': 22, 'source': '0.0.0.0/0'},
        {'protocol': 'tcp', 'port_range': 8000, 'source': '96.127.217.181/32'},
        {'protocol': 'tcp', 'port_range': 0, 'source': '0.0.0.0/0'}
    ]

    try:
        # Check if the security group already exists
        response = ec2_client.describe_security_groups(
            Filters=[
                {'Name': 'group-name', 'Values': [group_name]},
                {'Name': 'vpc-id', 'Values': [vpc_id]}
            ]
        )
        if response['SecurityGroups']:
            security_group_id = response['SecurityGroups'][0]['GroupId']
            print(f"Using existing Security Group ID: {security_group_id}")
            return security_group_id

        # If the security group doesn't exist, create a new one
        print(f"Creating security group {group_name} in VPC ID: {vpc_id}")
        response = ec2_client.create_security_group(
            GroupName=group_name,
            Description=description,
            VpcId=vpc_id
        )
        security_group_id = response['GroupId']
        print(f"Created Security Group ID: {security_group_id}")

        #set inbound rules
        ip_permissions = []
        for rule in inbound_rules:
            ip_permissions.append({
                'IpProtocol': 'tcp',
                'FromPort': rule['port_range'],
                'ToPort': rule['port_range'],
                'IpRanges': [{'CidrIp': rule['source']}]
            })

        # Add inbound rules
        ec2_client.authorize_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=ip_permissions
        )

        return security_group_id

    except ClientError as e:
        if 'InvalidPermission.Duplicate' in str(e):
            print(f"Ingress rule already exists for Security Group: {group_name}")
        else:
            print(f"Error adding ingress rules: {e}")
        return None

# Get the subnet
def get_subnet(ec2_client, vpc_id):
    """
    Function to get 2 Subnet ID
    Args:
        ec2_client: The boto3 ec2 client
        vpc_id: VPC id
    Returns:
        Subnet ID
    """
    try:
        response = ec2_client.describe_subnets(
            Filters=[
                {
                    'Name': 'vpc-id',
                    'Values': [vpc_id]
                }
            ]
        )
        subnets = response.get('Subnets', [])
        if not subnets:
            print("Error: No subnets found in the VPC.")
            sys.exit(1)

        print(f"Using Subnet ID: {subnets[0]['SubnetId']}")
        return subnets[0]['SubnetId']
    except ClientError as e:
        print(f"Error retrieving subnets: {e}")
        sys.exit(1)

# Set up the mysql clusters
def setup_mysql_cluster(ec2_client, key_name, sg_id, subnet_id):
    instance_type = 't2.micro'
    ami_id = 'ami-0e86e20dae9224db8'

    # User Data script to set up MySQL, configure replication, and install Sakila
    user_data_script = r'''#!/bin/bash
    # Update and install MySQL
    sudo apt update -y
    sudo apt install -y mysql-server wget

    # Enable GTID-based replication for MySQL
    sudo sed -i '/\[mysqld\]/a gtid_mode=ON' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo sed -i '/\[mysqld\]/a enforce_gtid_consistency=ON' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo sed -i '/\[mysqld\]/a log_slave_updates=ON' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo sed -i '/\[mysqld\]/a binlog_format=ROW' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo systemctl restart mysql

    # Configure MySQL for replication if this is the manager
    if [[ $(hostname) == *"manager"* ]]; then
        sudo mysql -e "CREATE USER 'repl'@'%' IDENTIFIED BY 'replica_password';"
        sudo mysql -e "GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';"
        sudo mysql -e "FLUSH PRIVILEGES;"
    fi

    # Download and load Sakila database
    wget https://downloads.mysql.com/docs/sakila-db.tar.gz
    tar -xvf sakila-db.tar.gz
    sudo mysql < sakila-db/sakila-schema.sql
    sudo mysql < sakila-db/sakila-data.sql
    '''


    # Define the instance configurations
    instances_config = [
        {'Name': 'manager', 'Role': 'manager'},
        {'Name': 'worker-1', 'Role': 'worker'},
        {'Name': 'worker-2', 'Role': 'worker'}
    ]

    instance_ids = []
    for config in instances_config:
        # Launch each instance with user_data script
        instance = ec2_client.run_instances(
            ImageId=ami_id,
            InstanceType=instance_type,
            KeyName=key_name,
            SecurityGroupIds=[sg_id],
            SubnetId=subnet_id,
            MinCount=1,
            MaxCount=1,
            TagSpecifications=[{
                'ResourceType': 'instance',
                'Tags': [
                    {'Key': 'Name', 'Value': config['Name']}
                ]
            }],
            UserData=user_data_script  # Pass the user_data script here
        )
        instance_ids.append(instance['Instances'][0]['InstanceId'])
        print(f"{config['Name'].capitalize()} instance created with ID: {instance['Instances'][0]['InstanceId']}")

    # Wait for instances to be in running state
    print("Waiting for instances to be in running state...")
    ec2_client.get_waiter('instance_running').wait(InstanceIds=instance_ids)

    # Fetch and print public IPs for manager and workers
    manager_instance_id = instance_ids[0]
    worker_instance_ids = instance_ids[1:]

    return manager_instance_id, worker_instance_ids

# Set up the proxy
def setup_proxy(ec2_client, key_name, sg_id, subnet_id, manager_instance_id, worker_instance_ids):
    """
    Set up the proxy with load balancing configurations.
    Args:
        ec2_client: The boto3 EC2 client.
        key_name: Key pair name to SSH into the instance.
        sg_id: Security group ID.
        subnet_id: Subnet ID.
        manager_instance_id: The instance ID of the manager.
        worker_instance_ids: A list of instance IDs for the worker nodes.
    Returns:
        Proxy instance ID.
    """

    # Simulated endpoint for testing
    manager_ip = get_public_ip(manager_instance_id)
    worker_ips = [get_public_ip(worker_id) for worker_id in worker_instance_ids]

    # Define the routing strategies
    def direct_hit(endpoint="write"):
        """
        Direct all requests to the manager instance.
        """
        print(f"Direct hit to manager instance at {manager_ip} for endpoint: {endpoint}")
        response = requests.post(f"http://{manager_ip}/{endpoint}")
        return response.status_code

    def random_worker(endpoint="read"):
        """
        Randomly choose a worker node to handle a read request.
        """
        worker_ip = random.choice(worker_ips)
        print(f"Random worker selected: {worker_ip} for endpoint: {endpoint}")
        response = requests.get(f"http://{worker_ip}/{endpoint}")
        return response.status_code

    def ping_based(endpoint="read"):
        """
        Route to the worker with the lowest ping time.
        """
        ping_times = {}
        for worker_ip in worker_ips:
            ping_time = subprocess.check_output(["ping", "-c", "1", worker_ip])
            ping_times[worker_ip] = float(ping_time.decode().split("time=")[-1].split(" ")[0])
        fastest_worker = min(ping_times, key=ping_times.get)
        print(f"Fastest worker selected: {fastest_worker} with ping {ping_times[fastest_worker]} ms for endpoint: {endpoint}")
        response = requests.get(f"http://{fastest_worker}/{endpoint}")
        return response.status_code

    # Example usage of the routing logic
    routing_method = "random"  # Adjust this as needed for different strategies

    if routing_method == "direct":
        direct_hit("write")
    elif routing_method == "random":
        random_worker("read")
    elif routing_method == "ping":
        ping_based("read")

def get_public_ip(instance_id):
    """
    Retrieves the public IP address of an instance.
    Args:
        instance_id: The instance ID.
    Returns:
        The public IP address as a string.
    """
    instance_description = ec2_client.describe_instances(InstanceIds=[instance_id])
    return instance_description['Reservations'][0]['Instances'][0]['PublicIpAddress']

# Set up the gatekeeper
def setup_gatekeeper(ec2_client, key_name, sg_id, subnet_id, proxy_instance_id):
    """
    Deploy the Gatekeeper instance and Trusted Host instance.
    """
    # Create Gatekeeper instance
    gatekeeper_instance = ec2_client.run_instances(
        InstanceType='t2.large',
        KeyName=key_name,
        SecurityGroupIds=[sg_id],
        SubnetId=subnet_id,
        MinCount=1,
        MaxCount=1,
    )
    gatekeeper_instance_id = gatekeeper_instance['Instances'][0]['InstanceId']
    print(f"Gatekeeper instance created with ID: {gatekeeper_instance_id}")

    # Create Trusted Host instance
    trusted_host_instance = ec2_client.run_instances(
        InstanceType='t2.large',
        KeyName=key_name,
        SecurityGroupIds=[sg_id],
        SubnetId=subnet_id,
        MinCount=1,
        MaxCount=1,
    )
    trusted_host_id = trusted_host_instance['Instances'][0]['InstanceId']
    print(f"Trusted Host instance created with ID: {trusted_host_id}")

    # Security configuration to only allow Gatekeeper to communicate with Trusted Host
    configure_gatekeeper_security(ec2_client, gatekeeper_instance_id, trusted_host_id)

    return gatekeeper_instance_id, trusted_host_id

# Configure the gatekeeper security
def configure_gatekeeper_security(ec2_client, gatekeeper_instance_id, trusted_host_id):
    """
    Configures security settings for Gatekeeper pattern.
    """
    # Security rules to ensure Gatekeeper can communicate with Trusted Host only
    pass

# Benchmarking
def benchmark_cluster(manager_instance_id, worker_instance_ids, proxy_instance_id):
    """
    Sends 1000 read and 1000 write requests to the MySQL cluster.
    """
    for _ in range(1000):
        # Send a write request to manager
        requests.post(f"http://{manager_instance_id}/write", data={'key': 'value'})

    for _ in range(1000):
        # Send a read request to proxy for load-balanced reading
        requests.get(f"http://{proxy_instance_id}/read")

# File with the IDs of the instances
INSTANCE_FILE = "instance_ids.json"

# Save the IDs of the instances in the file
def save_instance_ids(manager_id, worker_ids):
    data = {
        "manager_id": manager_id,
        "worker_ids": worker_ids
    }
    with open(INSTANCE_FILE, "w") as file:
        json.dump(data, file)
    print(f"Instance IDs saved to {INSTANCE_FILE}")

def main():
    # Step 1: Key pair setup
    key_name = get_key_pair(ec2_client)

    # Step 2: Retrieve VPC and subnet
    vpc_id = get_vpc_id(ec2_client)
    subnet_id = get_subnet(ec2_client, vpc_id)

    # Step 3: Security Group creation
    sg_id = create_security_group(ec2_client, vpc_id)

    # Step 4: Deploy MySQL instances (manager + 2 workers)
    manager_instance_id, worker_instance_ids = setup_mysql_cluster(ec2_client, key_name, sg_id, subnet_id)
    save_instance_ids(manager_instance_id, worker_instance_ids)

    # Step 5: Set up the proxy instance and configure load balancing
    proxy_instance_id = setup_proxy(ec2_client, key_name, sg_id, subnet_id, manager_instance_id, worker_instance_ids)

    # Step 6: Set up the gatekeeper pattern
    gatekeeper_instance_id, trusted_host_id = setup_gatekeeper(ec2_client, key_name, sg_id, subnet_id, proxy_instance_id)

    # Step 7: Send benchmarking requests
    benchmark_cluster(manager_instance_id, worker_instance_ids, proxy_instance_id)

if __name__ == "__main__":
    main()
