import boto3
import sys, os, time
import json
from botocore.exceptions import ClientError
import paramiko
import time
import random
import subprocess
import requests
import time
import botocore.exceptions

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
def setup_manager(ec2_client, key_name, sg_id, subnet_id):
    instance_type = 't2.micro'
    ami_id = 'ami-0e86e20dae9224db8'

    # User Data script to set up MySQL, FastAPI and configure replication for manager
    user_data_script = '''#!/bin/bash
    # Actualiza el sistema e instala dependencias
    sudo apt update -y
    sudo apt install -y mysql-server wget python3-pip python3-venv

    # Crea un entorno virtual para las dependencias de Python
    python3 -m venv /home/ubuntu/myenv
    source /home/ubuntu/myenv/bin/activate

    # Instala FastAPI, Uvicorn y el conector de MySQL en el entorno virtual
    pip install fastapi uvicorn mysql-connector-python

    # Configuración de MySQL
    sudo sed -i '/\[mysqld\]/a server-id=1' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo sed -i '/\[mysqld\]/a gtid_mode=ON' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo sed -i '/\[mysqld\]/a enforce_gtid_consistency=ON' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo sed -i '/\[mysqld\]/a log_slave_updates=ON' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo sed -i '/\[mysqld\]/a binlog_format=ROW' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo sed -i 's/^bind-address\s*=.*$/bind-address = 0.0.0.0/' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo systemctl restart mysql

    # Carga la base de datos Sakila
    wget https://downloads.mysql.com/docs/sakila-db.tar.gz
    tar -xvf sakila-db.tar.gz
    sudo mysql < sakila-db/sakila-schema.sql
    sudo mysql < sakila-db/sakila-data.sql

    # Crea y configura el usuario 'api_user' para conectarse a MySQL
    sudo mysql -e "CREATE USER 'api_user'@'localhost' IDENTIFIED BY 'api_password';"
    sudo mysql -e "GRANT ALL PRIVILEGES ON sakila.* TO 'api_user'@'localhost';"
    sudo mysql -e "FLUSH PRIVILEGES;"

    # Setup replication user for manager
    sudo mysql -e "CREATE USER 'repl'@'%' IDENTIFIED BY 'replica_password';"
    sudo mysql -e "GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';"
    sudo mysql -e "FLUSH PRIVILEGES;"

    # Change replication user 'repl' to use mysql_native_password
    sudo mysql -e "ALTER USER 'repl'@'%' IDENTIFIED WITH mysql_native_password BY 'replica_password';"
    sudo mysql -e "FLUSH PRIVILEGES;"

    # Crea el archivo de la aplicación FastAPI
    cat <<EOF > /home/ubuntu/app.py
from fastapi import FastAPI
import mysql.connector
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):
    column1: str
    column2: str

def get_db_connection():
    conn = mysql.connector.connect(
        host="localhost", 
        user="api_user",  # Usando el usuario 'api_user'
        password="api_password",  # Contraseña para 'api_user'
        database="sakila"
    )
    return conn

@app.post("/insert_item/")
async def insert_item(item: Item):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "INSERT INTO actor (first_name, last_name) VALUES (%s, %s)"
    cursor.execute(query, (item.column1, item.column2))
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Item inserted successfully"}
EOF

    source /home/ubuntu/myenv/bin/activate

    # Cambia los permisos del archivo para garantizar su ejecución
    chown ubuntu:ubuntu /home/ubuntu/app.py
    chmod 755 /home/ubuntu/app.py

    # Ejecuta la aplicación FastAPI con Uvicorn en el entorno virtual
    cd /home/ubuntu && nohup /home/ubuntu/myenv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 --reload &
    chmod +x /home/ubuntu/app.py
    pip install fastapi uvicorn mysql-connector-python
    nohup /home/ubuntu/myenv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 &
    '''

    # Launch the manager instance
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
                {'Key': 'Name', 'Value': 'manager'}
            ]
        }],
        UserData=user_data_script  # Pass the user_data script for manager
    )

    # Get the instance ID and private IP of the manager
    manager_instance_id = instance['Instances'][0]['InstanceId']
    print(f"Manager instance created with ID: {manager_instance_id}")

    # Wait for the instance to be in running state
    print("Waiting for manager instance to be in running state...")
    ec2_client.get_waiter('instance_running').wait(InstanceIds=[manager_instance_id])

    # Fetch private IP of the manager
    manager_private_ip = ec2_client.describe_instances(InstanceIds=[manager_instance_id])['Reservations'][0]['Instances'][0]['PrivateIpAddress']
    print(f"Manager's private IP: {manager_private_ip}")

    return manager_instance_id, manager_private_ip

def setup_worker(ec2_client, key_name, sg_id, subnet_id, manager_private_ip, worker_name, server_id):
    instance_type = 't2.micro'
    ami_id = 'ami-0e86e20dae9224db8'

    # User Data script to set up MySQL, FastAPI, and configure replication for workers
    user_data_script = f'''#!/bin/bash
    # Update and install MySQL, Python, and dependencies
    sudo apt update -y
    sudo apt install -y mysql-server wget python3-pip python3-venv

    # Set the server-id for the worker (should be unique, e.g., 2 for worker1, 3 for worker2)
    sudo sed -i '/\[mysqld\]/a server-id={server_id}' /etc/mysql/mysql.conf.d/mysqld.cnf

    # Enable GTID-based replication for MySQL
    sudo sed -i '/\[mysqld\]/a gtid_mode=ON' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo sed -i '/\[mysqld\]/a enforce_gtid_consistency=ON' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo sed -i '/\[mysqld\]/a log_slave_updates=ON' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo sed -i '/\[mysqld\]/a binlog_format=ROW' /etc/mysql/mysql.conf.d/mysqld.cnf
    sudo systemctl restart mysql

    # Download and load Sakila database on the worker
    wget https://downloads.mysql.com/docs/sakila-db.tar.gz
    tar -xvf sakila-db.tar.gz
    if [ -f sakila-db/sakila-schema.sql ]; then
        echo "Loading schema..."
        sudo mysql < sakila-db/sakila-schema.sql
    else
        echo "Schema file not found."
    fi

    if [ -f sakila-db/sakila-data.sql ]; then
        echo "Loading data..."
        sudo mysql < sakila-db/sakila-data.sql
    else
        echo "Data file not found."
    fi

    # Configure the worker to connect to the manager for replication
    sudo mysql -e "CHANGE MASTER TO MASTER_HOST='{manager_private_ip}', MASTER_USER='repl', MASTER_PASSWORD='replica_password', MASTER_AUTO_POSITION=1; START SLAVE;"

    # Create a Python virtual environment and install FastAPI
    python3 -m venv /home/ubuntu/myenv
    source /home/ubuntu/myenv/bin/activate

    pip install fastapi uvicorn mysql-connector-python

    # Create the FastAPI app to handle read requests
    cat <<EOF > /home/ubuntu/app.py
from fastapi import FastAPI
import mysql.connector
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):
    column1: str
    column2: str

def get_db_connection():
    conn = mysql.connector.connect(
        host="localhost", 
        user="api_user",  # Using the same user for read access
        password="api_password",  # Same password for 'api_user'
        database="sakila"
    )
    return conn

@app.get("/get_item/")
async def get_item(item_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT first_name, last_name FROM actor WHERE actor_id = %s"
    cursor.execute(query, (item_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    if result:
        return result;
    else:
        return {{"status": 200, "message": "Error"}}

EOF

    source /home/ubuntu/myenv/bin/activate

    chown ubuntu:ubuntu /home/ubuntu/app.py
    chmod 755 /home/ubuntu/app.py

    # Ejecuta la aplicación FastAPI con Uvicorn en el entorno virtual
    cd /home/ubuntu && nohup /home/ubuntu/myenv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 --reload &
    chmod +x /home/ubuntu/app.py
    pip install fastapi uvicorn mysql-connector-python
    nohup /home/ubuntu/myenv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 &

    '''

    # Launch the worker instance
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
                {'Key': 'Name', 'Value': worker_name}
            ]
        }],
        UserData=user_data_script  # Pass the user_data script for workers
    )

    # Get the instance ID of the worker
    worker_instance_id = instance['Instances'][0]['InstanceId']
    print(f"{worker_name} instance created with ID: {worker_instance_id}")

    # Wait for the instance to be in running state
    print(f"Waiting for {worker_name} instance to be in running state...")
    ec2_client.get_waiter('instance_running').wait(InstanceIds=[worker_instance_id])

    # Fetch the private IP of the worker instance
    worker_private_ip = ec2_client.describe_instances(InstanceIds=[worker_instance_id])['Reservations'][0]['Instances'][0]['PrivateIpAddress']
    print(f"{worker_name}'s private IP: {worker_private_ip}")

    return worker_instance_id

def setup_mysql_cluster(ec2_client, key_name, sg_id, subnet_id):
    # Create the manager
    manager_instance_id, manager_private_ip = setup_manager(ec2_client, key_name, sg_id, subnet_id)

    # Create workers and pass the manager's IP
    worker_instance_ids = []
    for i, worker_name in enumerate(['worker1', 'worker2'], start=2):  # Starting server-id from 2 for worker1
        worker_instance_id = setup_worker(ec2_client, key_name, sg_id, subnet_id, manager_private_ip, worker_name, i)
        worker_instance_ids.append(worker_instance_id)

    return manager_instance_id, worker_instance_ids

# Set up the proxy
def setup_proxy(ec2_client, key_name, sg_id, subnet_id, manager_ip, worker_ips):
    user_data_script_proxy = f'''#!/bin/bash
    sudo apt update -y
    sudo apt install -y python3-pip python3.12-venv python3-setuptools
    pip3 install fastapi uvicorn requests
    cat << EOF > /home/ubuntu/app.py
from fastapi import FastAPI
import requests
import random
import subprocess
import logging
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,  # Set the log level to INFO or DEBUG depending on your needs
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Create a logger
logger = logging.getLogger(__name__)

app = FastAPI()

# Modelo Item
class Item(BaseModel):
    column1: str
    column2: str

manager_ip = "{manager_ip}"
worker_ips = {worker_ips}

@app.post("/write")
def write(item: Item):
    logger.info(f"Received write request with item: {{item}}")
    response = requests.post(f"http://{manager_ip}:8000/insert_item/", json=item.dict())  # Fixed the f-string formatting
    logger.info(f"Successfully forwarded request to manager. Response: {{response.json()}}")
    return response.json()

@app.get("/random-read/")
def random_read(item_id: int):
    worker_ip = random.choice(worker_ips)
    response = requests.get(f"http://{{worker_ip}}:8000/get_item/?item_id={{item_id}}")
    return response.json()

@app.get("/direct-read/")
def direct_read(item_id: int):
    worker_ip = worker_ips[0]
    response = requests.get(f"http://{{worker_ip}}:8000/get_item/?item_id={{item_id}}")
    return response.json()

@app.get("/ping-read/")
def ping_read(item_id: int):
    ping_times = {{}}
    for worker_ip in worker_ips:
        ping_time = subprocess.check_output(["ping", "-c", "1", worker_ip]).decode().split("time=")[-1].split(" ")[0]
        ping_times[worker_ip] = float(ping_time)
    fastest_worker = min(ping_times, key=ping_times.get)
    response = requests.get(f"http://{{fastest_worker}}:8000/get_item/?item_id={{item_id}}")
    return response.json()

EOF

    # Update package list
    sudo apt update

    # Install python3-venv if not installed
    sudo apt install python3.12-venv

    # Create the virtual environment
    sudo python3 -m venv /home/ubuntu/myenv

    # Activate the virtual environment
    source /home/ubuntu/myenv/bin/activate

    # Upgrade pip in the virtual environment
    sudo /home/ubuntu/myenv/bin/pip install --upgrade pip

    # Install the required Python packages
    sudo /home/ubuntu/myenv/bin/pip install fastapi uvicorn mysql-connector-python requests

    # Run the FastAPI application
    cd /home/ubuntu
    nohup /home/ubuntu/myenv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 --reload &
    
    '''
    ami_id = 'ami-0e86e20dae9224db8'

    proxy_instance = ec2_client.run_instances(
        InstanceType='t2.large',
        ImageId=ami_id,
        KeyName=key_name,
        SecurityGroupIds=[sg_id],
        SubnetId=subnet_id,
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[{
            'ResourceType': 'instance',
            'Tags': [{'Key': 'Name', 'Value': 'proxy'}]
        }],
        UserData=user_data_script_proxy
    )
    proxy_instance_id = proxy_instance['Instances'][0]['InstanceId']
    print(f"Proxy instance created with ID: {proxy_instance_id}")

    return proxy_instance_id

def get_public_ip(instance_id):
    retries = 3
    for i in range(retries):
        try:
            instance_description = ec2_client.describe_instances(InstanceIds=[instance_id])
            public_ip = instance_description['Reservations'][0]['Instances'][0].get('PublicIpAddress')
            return public_ip
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'InvalidInstanceID.NotFound':
                print(f"Instance {instance_id} not found. Retrying in 30 seconds...")
                time.sleep(30)
            else:
                raise e
    raise Exception(f"Unable to retrieve public IP for instance {instance_id} after {retries} retries.")

# Set up the gatekeeper
def setup_gatekeeper(ec2_client, key_name, sg_id, subnet_id, proxy_ip):
    """
    Deploy the Gatekeeper and Trusted Host instances and configure them with FastAPI to securely handle requests.
    Args:
        ec2_client: The boto3 EC2 client.
        key_name: Key pair name to SSH into the instance.
        sg_id: Security group ID.
        subnet_id: Subnet ID.
        proxy_ip: Public IP of the Proxy instance to which Trusted Host will forward requests.
    Returns:
        Tuple with Gatekeeper and Trusted Host instance IDs.
    """
    # Script to configure the Trusted Host with FastAPI to handle requests from Gatekeeper
    user_data_script_trusted_host = f'''#!/bin/bash
    sudo apt update -y
    sudo apt install -y python3-pip python3.12-venv python3-setuptools
    pip3 install fastapi uvicorn requests
    cat << EOF > /home/ubuntu/app.py
from fastapi import FastAPI
import requests
import random
import subprocess
import logging
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,  # Set the log level to INFO or DEBUG depending on your needs
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Create a logger
logger = logging.getLogger(__name__)

app = FastAPI()

# Modelo Item
class Item(BaseModel):
    column1: str
    column2: str

proxy_ip = "{proxy_ip}"

@app.post("/write")
def write(item: Item):
    logger.info(f"Received write request with item: {{item}}")
    response = requests.post(f"http://{proxy_ip}:8000/write", json=item.dict())
    return response.json()

@app.get("/random-read/")
def random_read(item_id: int):
    response = requests.get(f"http://{proxy_ip}:8000/random-read/?item_id={{item_id}}")
    return response.json()

@app.get("/direct-read/")
def direct_read(item_id: int):
    response = requests.get(f"http://{proxy_ip}:8000/direct-read/?item_id={{item_id}}")
    return response.json()

@app.get("/ping-read/")
def ping_read(item_id: int):
    response = requests.get(f"http://{proxy_ip}:8000/ping-read/?item_id={{item_id}}")
    return response.json()

EOF

    # Update package list
    sudo apt update

    # Install python3-venv if not installed
    sudo apt install python3.12-venv

    # Create the virtual environment
    sudo python3 -m venv /home/ubuntu/myenv

    # Activate the virtual environment
    source /home/ubuntu/myenv/bin/activate

    # Upgrade pip in the virtual environment
    sudo /home/ubuntu/myenv/bin/pip install --upgrade pip

    # Install the required Python packages
    sudo /home/ubuntu/myenv/bin/pip install fastapi uvicorn mysql-connector-python requests

    # Run the FastAPI application
    cd /home/ubuntu
    nohup /home/ubuntu/myenv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 --reload &
    
    '''

    # Launch the Trusted Host instance
    ami_id = 'ami-0e86e20dae9224db8'

    trusted_host_instance = ec2_client.run_instances(
        InstanceType='t2.large',
        KeyName=key_name,
        ImageId=ami_id,
        SecurityGroupIds=[sg_id],
        SubnetId=subnet_id,
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[{
            'ResourceType': 'instance',
            'Tags': [{'Key': 'Name', 'Value': 'trusted_host'}]
        }],
        UserData=user_data_script_trusted_host
    )
    trusted_host_instance_id = trusted_host_instance['Instances'][0]['InstanceId']
    ec2_client.get_waiter('instance_running').wait(InstanceIds=[trusted_host_instance_id])
    trusted_host_ip = get_public_ip(trusted_host_instance_id)
    print(f"Trusted Host instance created with ID: {trusted_host_instance_id} and IP: {trusted_host_ip}")

    # Script to configure the Gatekeeper with FastAPI to validate requests and forward to Trusted Host
    user_data_script_gatekeeper = f'''#!/bin/bash
    sudo apt update -y
    sudo apt install -y python3-pip python3.12-venv python3-setuptools
    pip3 install fastapi uvicorn requests
    cat << EOF > /home/ubuntu/app.py
from fastapi import FastAPI
import requests
import random
import subprocess
import logging
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,  # Set the log level to INFO or DEBUG depending on your needs
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Create a logger
logger = logging.getLogger(__name__)

app = FastAPI()

# Modelo Item
class Item(BaseModel):
    column1: str
    column2: str

trusted_host_ip = "{trusted_host_ip}"

@app.post("/write")
def write(item: Item):
    logger.info(f"Received write request with item: {{item}}")
    response = requests.post(f"http://{trusted_host_ip}:8000/write", json=item.dict())
    return response.json()

@app.get("/random-read/")
def random_read(item_id: int):
    response = requests.get(f"http://{trusted_host_ip}:8000/random-read/?item_id={{item_id}}")
    return response.json()

@app.get("/direct-read/")
def direct_read(item_id: int):
    response = requests.get(f"http://{trusted_host_ip}:8000/direct-read/?item_id={{item_id}}")
    return response.json()

@app.get("/ping-read/")
def ping_read(item_id: int):
    response = requests.get(f"http://{trusted_host_ip}:8000/ping-read/?item_id={{item_id}}")
    return response.json()

EOF

    # Update package list
    sudo apt update

    # Install python3-venv if not installed
    sudo apt install python3.12-venv

    # Create the virtual environment
    sudo python3 -m venv /home/ubuntu/myenv

    # Activate the virtual environment
    source /home/ubuntu/myenv/bin/activate

    # Upgrade pip in the virtual environment
    sudo /home/ubuntu/myenv/bin/pip install --upgrade pip

    # Install the required Python packages
    sudo /home/ubuntu/myenv/bin/pip install fastapi uvicorn mysql-connector-python requests

    # Run the FastAPI application
    cd /home/ubuntu
    nohup /home/ubuntu/myenv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 --reload &
    
    '''

    # Launch the Gatekeeper instance
    ami_id = 'ami-0e86e20dae9224db8'

    gatekeeper_instance = ec2_client.run_instances(
        InstanceType='t2.large',
        KeyName=key_name,
        ImageId=ami_id,
        SecurityGroupIds=[sg_id],
        SubnetId=subnet_id,
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[{
            'ResourceType': 'instance',
            'Tags': [{'Key': 'Name', 'Value': 'gatekeeper'}]
        }],
        UserData=user_data_script_gatekeeper
    )
    gatekeeper_instance_id = gatekeeper_instance['Instances'][0]['InstanceId']
    ec2_client.get_waiter('instance_running').wait(InstanceIds=[gatekeeper_instance_id])
    gatekeeper_ip = get_public_ip(gatekeeper_instance_id)
    print(f"Gatekeeper instance created with ID: {gatekeeper_instance_id} and IP: {gatekeeper_ip}")

    # Security configuration to ensure only Gatekeeper can communicate with Trusted Host
    #configure_gatekeeper_security(ec2_client, sg_id, trusted_host_ip)

    return gatekeeper_instance_id, trusted_host_instance_id

# Configure the gatekeeper security
def configure_gatekeeper_security(ec2_client, sg_id, trusted_host_ip):
    '''
    ec2_client.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                'IpProtocol': 'tcp',  # Example: Allowing TCP protocol
                'FromPort': 22,       # Example: Allowing SSH (port 22)
                'ToPort': 22,         # Example: Allowing SSH (port 22)
                'IpRanges': [
                    {
                        'CidrIp': trusted_host_ip,  # Use trusted_host_ip here
                        'Description': 'SSH access from trusted host'
                    }
                ]
            }
        ]
    )
    '''

# Benchmarking
'''
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
'''
        
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
    manager_ip = get_public_ip(manager_instance_id)
    worker_ips = [get_public_ip(worker_id) for worker_id in worker_instance_ids]
    proxy_instance_id = setup_proxy(ec2_client, key_name, sg_id, subnet_id, manager_ip, worker_ips)

    # Step 6: Set up the gatekeeper pattern
    proxy_ip = get_public_ip(proxy_instance_id)
    gatekeeper_instance_id, trusted_host_id = setup_gatekeeper(ec2_client, key_name, sg_id, subnet_id, proxy_ip)

    # Step 7: Send benchmarking requests
    # benchmark_cluster(manager_instance_id, worker_instance_ids, proxy_instance_id)

if __name__ == "__main__":
    main()
