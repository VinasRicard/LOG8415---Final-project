import boto3
import os
from botocore.exceptions import ClientError

def terminate_running_instances():
    """
    Function to delete all running instances
    """
    session = boto3.Session()
    ec2 = session.resource('ec2')

    # Get running instances and their IDs
    running_instances = ec2.instances.filter(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])
    instance_ids = [instance.id for instance in running_instances]

    if not instance_ids:
        print("No running instances found to terminate.")
    else:
        # Terminate running instances
        ec2.instances.filter(InstanceIds=instance_ids).terminate()
        print(f"Terminating instances: {instance_ids}")

def remove_key_file():
    """
    Function to remove key file
    """
    # Get path of key file
    key_file_path = os.path.expanduser("~/.aws/tp2.pem")

    try:
        os.remove(key_file_path)
        print(f"Key file '{key_file_path}' has been deleted successfully.")
    except FileNotFoundError:
        print(f"The file '{key_file_path}' does not exist.")
    except PermissionError:
        print(f"Error: Permission denied when trying to delete '{key_file_path}'.")
    except Exception as e:
        print(f"An error occurred: {e}")
        
def delete_security_group(ec2_client, group_name):
    """
    Function to delete security group
    """
    try:
        ec2_client.delete_security_group(
            GroupName=group_name
        )
        print(f"Successfully deleted security group: {group_name}")
    except ClientError as e:
        print(f"Error deleting security group: {e}")

def delete_key_pair(ec2_client, key_name):
    """
    Function to delete key pair
    Args:
        elbv2_client: elbv2 boro3 client
        key_name: Name of the key
    """
    try:
        response = ec2_client.delete_key_pair(KeyName=key_name)
        print(f"Key pair '{key_name}' deleted successfully.")
    except ClientError as e:
        print(f"No key pair {key_name} found")
    except IndexError:
        print(f"Key pair '{key_name}' not found.")

if __name__ == "__main__":
    ec2_client = boto3.client('ec2')
    elbv2_client = boto3.client('elbv2')
    terminate_running_instances()
    remove_key_file()
    delete_security_group(ec2_client, "my-security-group")
    delete_key_pair(ec2_client, 'tp2')

