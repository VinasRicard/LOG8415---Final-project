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

# Launch mysql clusters
def launch_mysql_cluster(ec2_client, image_id, instance_type, key_name, security_group_id, subnet_id):
    user_data_script = '''#!/bin/bash
                          sudo apt update -y
                          sudo apt install -y mysql-server
                          wget https://downloads.mysql.com/docs/sakila-db.tar.gz
                          tar -xzf sakila-db.tar.gz
                          mysql < sakila-db/sakila-schema.sql
                          mysql < sakila-db/sakila-data.sql
                          '''
    response = ec2_client.run_instances(
        ImageId=image_id,
        InstanceType=instance_type,
        KeyName=key_name,
        SecurityGroupIds=[security_group_id],
        SubnetId=subnet_id,
        UserData=user_data_script,
        MinCount=3,
        MaxCount=3
    )
    instances = [i['InstanceId'] for i in response['Instances']]
    for instance_id in instances:
        ec2_client.get_waiter('instance_running').wait(InstanceIds=[instance_id])
        print(f"MySQL instance {instance_id} is running.")
    return instances

# Launch Proxy Server
def launch_proxy_server(ec2_client, image_id, instance_type, key_name, security_group_id, subnet_id):
    user_data_script = '''#!/bin/bash
                          sudo apt update -y
                          sudo apt install -y python3-pip
                          pip3 install flask requests
                          '''
    response = ec2_client.run_instances(
        ImageId=image_id,
        InstanceType=instance_type,
        KeyName=key_name,
        SecurityGroupIds=[security_group_id],
        SubnetId=subnet_id,
        UserData=user_data_script,
        MinCount=1,
        MaxCount=1
    )
    proxy_id = response['Instances'][0]['InstanceId']
    ec2_client.get_waiter('instance_running').wait(InstanceIds=[proxy_id])
    return proxy_id

# Launch Gatekeeper and Trusted Host
def launch_gatekeeper_and_trusted_host(ec2_client, image_id, instance_type, key_name, security_group_id, subnet_id):
    user_data_script = '''#!/bin/bash
                          sudo apt update -y
                          sudo apt install -y python3-pip
                          pip3 install flask requests
                          '''
    response = ec2_client.run_instances(
        ImageId=image_id,
        InstanceType=instance_type,
        KeyName=key_name,
        SecurityGroupIds=[security_group_id],
        SubnetId=subnet_id,
        UserData=user_data_script,
        MinCount=2,
        MaxCount=2
    )
    instances = [i['InstanceId'] for i in response['Instances']]
    for instance_id in instances:
        ec2_client.get_waiter('instance_running').wait(InstanceIds=[instance_id])
    return instances

# Transfer files to instances
def transfer_files(instance_ip, key_file, files):
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_client.connect(instance_ip, username='ubuntu', key_filename=key_file)
    scp = paramiko.SFTPClient.from_transport(ssh_client.get_transport())
    for file in files:
        scp.put(file, f"/home/ubuntu/{os.path.basename(file)}")
    scp.close()
    ssh_client.close()

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

        # INSTANCES

        print("Launching EC2 instances...")
        # Launch instances
        mysql_instances = launch_mysql_cluster(ec2_client, image_id, 't2.micro', key_name, security_group_id, subnet_id)
        
        '''
        proxy_id = launch_proxy_server(ec2_client, image_id, 't2.large', key_name, security_group_id, subnet_id)
        gatekeeper_and_trusted_host = launch_gatekeeper_and_trusted_host(ec2_client, image_id, 't2.large', key_name, security_group_id, subnet_id)
        # Retrieve public IPs
        ec2_resource = boto3.resource('ec2')
        instances_ips = [ec2_resource.Instance(i).public_ip_address for i in mysql_instances + [proxy_id] + gatekeeper_and_trusted_host]
        print("Instance IPs:", instances_ips)
        # Transfer application files
        key_file_path = os.path.expanduser(f"~/.aws/{key_name}.pem")
        transfer_files(instances_ips[0], key_file_path, ["proxy.py", "gatekeeper.py", "trusted_host.py"])
        for ip in instances_ips[1:]:
            transfer_files(ip, key_file_path, ["mysql_setup.py"])
        '''

    except Exception as e:
        print(f"Error during execution: {e}")

if __name__ == "__main__":
    main()