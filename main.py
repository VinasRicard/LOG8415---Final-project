import boto3
import sys, os, time
import json
from botocore.exceptions import ClientError
import paramiko

import boto3
import time

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
        {'protocol': 'tcp', 'port_range': 8000, 'source': '96.127.217.181/32'}
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

# Launch cluster instances
def launch_clusters(ec2_client, image_id, instance_type, key_name, security_group_id, subnet_id, num_instances):
    """
    Launches EC2 worker instances.
    Args:
        ec2_client: The EC2 client.
        image_id: The AMI ID for the instance.
        instance_type: The type of instance (e.g., 't2.micro').
        key_name: The key pair name to use for SSH access.
        security_group_id: The security group ID.
        subnet_id: The subnet ID.
        num_instances: Number of instances to launch.
    Returns:
        List of worker instance objects.
    """
    #Script to install MySQL and the Sakila database inside the instances

    user_data_script = '''#!/bin/bash
                        # Update the apt package index
                        sudo apt update
                        
                        sudo apt install -y python3-pip python3-venv

                        # Install required Python packages globally
                        sudo pip3 install flask requests torch transformers

                        # Install MySQL and Sakila
                        sudo apt update
                        sudo apt install -y mysql-server
                        wget https://downloads.mysql.com/docs/sakila-db.tar.gz
                        tar -xzf sakila-db.tar.gz
                        mysql < sakila-db/sakila-schema.sql
                        mysql < sakila-db/sakila-data.sql

                        
                        # Wait for the app.py file to be transferred
                        while [ ! -f /home/ubuntu/worker.py ]; do
                            sleep 5
                        done
                        
                        # Run Docker Compose as root to avoid permission issues
                        cd /home/ubuntu
                        sudo docker-compose up -d
                        '''

    try:
        response = ec2_client.run_instances(
            ImageId=image_id,
            MinCount=num_instances,
            MaxCount=num_instances,
            InstanceType=instance_type,
            KeyName=key_name,
            SecurityGroupIds=[security_group_id],
            SubnetId=subnet_id,
            UserData=user_data_script,
            # Extend size for pip and flask to be installed in docker
            BlockDeviceMappings=[
                {
                    'DeviceName': '/dev/sda1',
                    'Ebs': {
                        'VolumeSize': 20,  # Size in GiB
                        'VolumeType': 'gp2',
                        'DeleteOnTermination': True,
                    },
                },
            ],
            TagSpecifications=[
                {
                    'ResourceType': 'instance',
                    'Tags': [
                        {
                            'Key': 'Name',
                            'Value': 'LabInstance'
                        }
                    ]
                }
            ]
        )

        ec2_resource = boto3.resource('ec2')

        # Retrieve instance objects using the InstanceId
        instance_objects = [ec2_resource.Instance(instance['InstanceId']) for instance in response['Instances']]

        print(f"Launched {num_instances} {instance_type} instances.")
        # Wait for all instances to be in "running" state and collect instance details
        for instance in instance_objects:
            instance.wait_until_running()
            instance.reload()  # Reload instance attributes to get updated info
            print(f"Worker instance IP: {instance.public_ip_address}   ID: {instance.id}")

        return instance_objects

    except ClientError as e:
        print(f"Error launching instances: {e}")
        sys.exit(1)

# Launch proxy
def launch_proxy(ec2_client, image_id, instance_type, key_name, security_group_id, subnet_id, num_instances):
    """
    Launches EC2 worker instances.
    Args:
        ec2_client: The EC2 client.
        image_id: The AMI ID for the instance.
        instance_type: The type of instance (e.g., 't2.micro').
        key_name: The key pair name to use for SSH access.
        security_group_id: The security group ID.
        subnet_id: The subnet ID.
        num_instances: Number of instances to launch.
    Returns:
        List of worker instance objects.
    """
    #Script to install MySQL and the Sakila database inside the instances
    user_data_script_test = '''#!/bin/bash
                        # Update the apt package index
                        sudo apt update

                        # Install Docker
                        sudo apt install -y docker.io
                        sudo systemctl start docker
                        sudo systemctl enable docker

                        # Install Docker Compose
                        sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
                        sudo chmod +x /usr/local/bin/docker-compose

                        # Add ubuntu user to the Docker group
                        sudo usermod -aG docker ubuntu
                        
                        # Wait for the app.py file to be transferred
                        while [ ! -f /home/ubuntu/app.py ]; do
                            sleep 5
                        done
                        
                        # Run Docker Compose as root to avoid permission issues
                        cd /home/ubuntu
                        sudo docker-compose up -d
                        '''

    user_data_script = '''#!/bin/bash
                        # Update the apt package index
                        sudo apt update
                        
                        sudo apt install -y python3-pip python3-venv

                        # Install required Python packages globally
                        sudo pip3 install flask requests torch transformers

                        # Install Docker
                        sudo apt install -y docker.io
                        sudo systemctl start docker
                        sudo systemctl enable docker

                        # Install Docker Compose
                        sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
                        sudo chmod +x /usr/local/bin/docker-compose

                        # Add ubuntu user to the Docker group
                        sudo usermod -aG docker ubuntu
                        
                        # Wait for the app.py file to be transferred
                        while [ ! -f /home/ubuntu/worker.py ]; do
                            sleep 5
                        done
                        
                        # Run Docker Compose as root to avoid permission issues
                        cd /home/ubuntu
                        sudo docker-compose up -d
                        '''

    try:
        response = ec2_client.run_instances(
            ImageId=image_id,
            MinCount=num_instances,
            MaxCount=num_instances,
            InstanceType=instance_type,
            KeyName=key_name,
            SecurityGroupIds=[security_group_id],
            SubnetId=subnet_id,
            UserData=user_data_script,
            # Extend size for pip and flask to be installed in docker
            BlockDeviceMappings=[
                {
                    'DeviceName': '/dev/sda1',
                    'Ebs': {
                        'VolumeSize': 20,  # Size in GiB
                        'VolumeType': 'gp2',
                        'DeleteOnTermination': True,
                    },
                },
            ],
            TagSpecifications=[
                {
                    'ResourceType': 'instance',
                    'Tags': [
                        {
                            'Key': 'Name',
                            'Value': 'LabInstance'
                        }
                    ]
                }
            ]
        )

        ec2_resource = boto3.resource('ec2')

        # Retrieve instance objects using the InstanceId
        instance_objects = [ec2_resource.Instance(instance['InstanceId']) for instance in response['Instances']]

        print(f"Launched {num_instances} {instance_type} instances.")
        # Wait for all instances to be in "running" state and collect instance details
        for instance in instance_objects:
            instance.wait_until_running()
            instance.reload()  # Reload instance attributes to get updated info
            print(f"Worker instance IP: {instance.public_ip_address}   ID: {instance.id}")

        return instance_objects

    except ClientError as e:
        print(f"Error launching instances: {e}")
        sys.exit(1)

#???
def launch_orchestrator(ec2_client, image_id, instance_type, key_name, security_group_id, subnet_id):
    """
    Launches EC2 orchestrator instance.
    Args:
        ec2_client: The EC2 client.
        image_id: The AMI ID for the instance.
        instance_type: The type of instance (e.g., 't2.micro').
        key_name: The key pair name to use for SSH access.
        security_group_id: The security group ID.
        subnet_id: The subnet ID.
    Returns:
        orchestrator instance
    """
    user_data_script = '''#!/bin/bash
                        sudo apt update -y
                        sudo apt install -y python3-pip python3-venv
                        cd /home/ubuntu
                        python3 -m venv venv
                        echo "source venv/bin/activate" >> /home/ubuntu/.bashrc
                        source venv/bin/activate
                        
                        pip3 install flask requests redis
                        
                        # Wait for the my_fastapi.py file to be transferred
                        while [ ! -f /home/ubuntu/orchestrator.py ]; do
                            sleep 5
                        done
                        
                        python3 orchestrator.py
                        '''

    try:
        response = ec2_client.run_instances(
            ImageId=image_id,
            MinCount=1,
            MaxCount=1,
            InstanceType=instance_type,
            KeyName=key_name,
            SecurityGroupIds=[security_group_id],
            SubnetId=subnet_id,
            UserData=user_data_script,
            TagSpecifications=[
                {
                    'ResourceType': 'instance',
                    'Tags': [
                        {
                            'Key': 'Name',
                            'Value': 'LabInstance'
                        }
                    ]
                }
            ]
        )

        ec2_resource = boto3.resource('ec2')

        # Retrieve instance objects using the InstanceId
        orchestrator_list = [ec2_resource.Instance(instance['InstanceId']) for instance in response['Instances']]
        orchestrator = orchestrator_list[0]

        orchestrator.wait_until_running()
        orchestrator.reload()

        print(f"Orchestrator launched IP: {orchestrator.public_ip_address}   ID: {orchestrator.id}")
        with open('orchestrator_ip.txt', 'w') as file:
            file.write(orchestrator.public_ip_address)

        return orchestrator

    except ClientError as e:
        print(f"Error launching instances: {e}")
        sys.exit(1)

#???
def change_ips(instances):
    """
    Function to modify public IP instances in test.json file
    Args:
        instances: list of ip addresses
    Returns:
    """
    try:
        with open("test.json", "r") as f:
            data = json.load(f)

        # Change the IP for both containers
        for i in range(len(instances)):
            data[f"cont1work{i + 1}"]["ip"] = instances[i].public_ip_address
            data[f"cont2work{i + 1}"]["ip"] = instances[i].public_ip_address

        with open("test.json", "w") as f:
            json.dump(data, f)

    except Exception as e:
        print(f"Error during r/w json file: {e}")

# Transfer the files to the instances????
def transfer_worker(instance_ip, key_file):
    """
    Function to transfer FlaskApp file to workers
    Args:
        instance_ip: public IP of the instance
        key_file: path to pem key file
    Returns:
    """
    try:
        # Create an SSH client instance
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Connect to the instance
        ssh_client.connect(instance_ip, username='ubuntu', key_filename=key_file)

        # Clear a SCP instance
        scp = paramiko.SFTPClient.from_transport(ssh_client.get_transport())

        # Test files for transfer
        #scp.put("test-compose/compose.yaml", "/home/ubuntu/compose.yaml")
        #scp.put("test-compose/Dockerfile", "/home/ubuntu/Dockerfile")
        #scp.put("test-compose/requirements.txt", "/home/ubuntu/requirements.txt")
        #scp.put("test-compose/app.py", "/home/ubuntu/app.py")

        # Transfer essential files
        scp.put("docker-compose.yaml", "/home/ubuntu/docker-compose.yaml")
        scp.put("Dockerfile", "/home/ubuntu/Dockerfile")
        scp.put("requirements.txt", "/home/ubuntu/requirements.txt")
        scp.put("worker.py", "/home/ubuntu/worker.py")

        # Close connections
        scp.close()
        ssh_client.close()
        print(f"Files transferred to {instance_ip}")

    except Exception as e:
        print(f"Error transferring file to {instance_ip}: {e}")

#???
def transfer_orchestrator(orchestrator_ip, key_file):
    """
       Function to transfer FlaskApp file to orchestrator
       Args:
           orchestrator_ip: public IP of orchestrator
           key_file: path to pem key file
       Returns:
       """
    try:
        # Create an SSH client instance
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Connect to the instance
        ssh_client.connect(orchestrator_ip, username='ubuntu', key_filename=key_file)

        # Clear a SCP instance
        scp = paramiko.SFTPClient.from_transport(ssh_client.get_transport())

        # Transfer the file
        scp.put("test.json", "/home/ubuntu/test.json")
        scp.put("orchestrator.py", "/home/ubuntu/orchestrator.py")

        # Close connections
        scp.close()
        ssh_client.close()
        print(f"Files transferred to Orchestrator")

    except Exception as e:
        print(f"Error transferring file to Orchestrator: {e}")

# Manage the transfers???
def manage_transfer(instances, orchestrator, key_name):
    """
       Function which manages transfer functions
       Args:
           instances: list of worker instances
           orchestrator: orchestrator object
           key_name: path to pem key file
       Returns:
       """
    time.sleep(20)
    key_file_path = os.path.join(os.path.expanduser('~/.aws'), f"{key_name}.pem")
    for num, instance in enumerate(instances):
        transfer_worker(instance.public_ip_address, key_file_path)

    transfer_orchestrator(orchestrator.public_ip_address, key_file_path)

def main():
    try:
        # BASIC CONFIGURATION

        # Initialize EC2 and ELB clients
        ec2_client = boto3.client('ec2')
        elbv2_client = boto3.client('elbv2')

        # Define essential AWS configuration
        vpc_id = get_vpc_id(ec2_client)
        image_id = 'ami-0e86e20dae9224db8'

        # Get key pair, security group, and subnet
        key_name = get_key_pair(ec2_client)
        security_group_id = create_security_group(ec2_client, vpc_id)
        subnet_id = get_subnet(ec2_client, vpc_id)

        print("Launching EC2 instances...")
        # Create 3 t2.micro instances and install MySQL stand-alone on each of them
        clusters = launch_clusters(
            ec2_client, image_id, 't2.micro', key_name, security_group_id, subnet_id, 3
        )

        # PROXY

        # Create ne t2.large instance as the server which will route requests to MySQL Cluster
        proxy = launch_proxy(
            ec2_client, image_id, 't2.large', key_name, security_group_id, subnet_id, 1
        )

        # GATEKEEPER

        # Create the gatekeepper

        # Create the trusted host

        #launching the orchestrator????
        orchestrator = launch_orchestrator(
            ec2_client, image_id, 't2.large', key_name, security_group_id, subnet_id
        )
        #changing ips?????
        change_ips(clusters)
        #managing transfers?????
        manage_transfer(clusters, orchestrator, key_name)
        time.sleep(300) #waiting for docker to initialize for worker instances???

    except Exception as e:
        print(f"Error during execution: {e}")

if __name__ == "__main__":
    main()