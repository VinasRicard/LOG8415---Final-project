import boto3
import paramiko
import json
import time
from botocore.exceptions import ClientError

# Inicializar cliente de EC2
ec2_client = boto3.client('ec2', region_name='us-east-1')

# Archivo JSON con los IDs de las instancias
INSTANCE_FILE = "instance_ids.json"

# Cargar IDs de las instancias desde el archivo JSON
def load_instance_ids():
    with open(INSTANCE_FILE, "r") as file:
        data = json.load(file)
    return data["manager_id"], data["worker_ids"]

# Obtiene la IP pública de cada instancia
def get_public_ip(instance_id):
    response = ec2_client.describe_instances(InstanceIds=[instance_id])
    return response['Reservations'][0]['Instances'][0]['PublicIpAddress']

# Ejecuta comandos en la instancia mediante SSH
def execute_ssh_command(ip, key_path, command):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ip, username="ubuntu", key_filename=key_path)
    stdin, stdout, stderr = ssh.exec_command(command)
    output = stdout.read().decode()
    error = stderr.read().decode()
    ssh.close()
    return output, error

# Habilita GTID en la instancia de MySQL
def configure_mysql_for_gtid(ip, key_path):
    commands = [
        r"sudo sed -i '/\[mysqld\]/a gtid_mode=ON' /etc/mysql/mysql.conf.d/mysqld.cnf",
        r"sudo sed -i '/\[mysqld\]/a enforce_gtid_consistency=ON' /etc/mysql/mysql.conf.d/mysqld.cnf",
        r"sudo sed -i '/\[mysqld\]/a log_slave_updates=ON' /etc/mysql/mysql.conf.d/mysqld.cnf",
        r"sudo sed -i '/\[mysqld\]/a binlog_format=ROW' /etc/mysql/mysql.conf.d/mysqld.cnf",
        "sudo systemctl restart mysql"
    ]
    for command in commands:
        output, error = execute_ssh_command(ip, key_path, command)
        if error:
            print(f"Error ejecutando comando en {ip}: {error}")
        else:
            print(f"Comando ejecutado en {ip}: {command}")

# Configura el usuario de replicación en el manager
def setup_replication_user_on_manager(manager_ip, key_path):
    commands = [
        "sudo mysql -e \"CREATE USER 'repl'@'%' IDENTIFIED BY 'replica_password';\"",
        "sudo mysql -e \"GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';\"",
        "sudo mysql -e \"FLUSH PRIVILEGES;\""
    ]
    for command in commands:
        output, error = execute_ssh_command(manager_ip, key_path, command)
        if error:
            print(f"Error configurando usuario de replicación en manager {manager_ip}: {error}")
        else:
            print(f"Usuario de replicación configurado en manager {manager_ip}")

# Configura la replicación en cada worker
def configure_replication_on_worker(worker_ip, manager_public_ip, key_path):
    command = f"sudo mysql -e \"CHANGE MASTER TO MASTER_HOST='{manager_public_ip}', MASTER_USER='repl', MASTER_PASSWORD='replica_password', MASTER_AUTO_POSITION=1; START SLAVE;\""
    output, error = execute_ssh_command(worker_ip, key_path, command)
    if error:
        print(f"Error configurando replicación en worker {worker_ip}: {error}")
    else:
        print(f"Replicación configurada en worker {worker_ip}")

# Verifica el estado de la replicación en cada worker
def check_replication_status(worker_ip, key_path):
    command = "sudo mysql -e 'SHOW SLAVE STATUS\\G'"
    output, error = execute_ssh_command(worker_ip, key_path, command)
    if "Slave_IO_Running: Yes" in output and "Slave_SQL_Running: Yes" in output:
        print(f"Replicación exitosa en {worker_ip}")
    else:
        print(f"Problema en replicación en {worker_ip}: {output or error}")

def main():
    # Cargar los IDs de las instancias desde el archivo JSON
    manager_id, worker_ids = load_instance_ids()

    # Ruta al archivo de la clave SSH
    key_path = "~/.aws/tp2.pem"

    # Obtener las IPs públicas de las instancias
    manager_public_ip = get_public_ip(manager_id)
    worker_public_ips = [get_public_ip(worker_id) for worker_id in worker_ids]

    # Configurar GTID en el manager y los workers
    print("Configurando GTID en el manager y workers...")
    configure_mysql_for_gtid(manager_public_ip, key_path)
    for worker_ip in worker_public_ips:
        configure_mysql_for_gtid(worker_ip, key_path)

    # Configurar el usuario de replicación en el manager
    print("Configurando usuario de replicación en el manager...")
    setup_replication_user_on_manager(manager_public_ip, key_path)

    # Configurar la replicación en cada worker
    print("Configurando replicación en los workers...")
    for worker_ip in worker_public_ips:
        configure_replication_on_worker(worker_ip, manager_public_ip, key_path)

    # Verificar el estado de la replicación
    print("Verificando el estado de la replicación en cada worker...")
    for worker_ip in worker_public_ips:
        check_replication_status(worker_ip, key_path)

if __name__ == "__main__":
    main()