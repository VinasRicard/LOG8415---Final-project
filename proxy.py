from flask import Flask, request, jsonify
import mysql.connector
import random
from ping3 import ping
import requests

app = Flask(__name__)

# Define configurations for MySQL instances
manager_db = {"host": "manager_host_ip", "user": "root", "password": "password", "database": "sakila"}
worker_dbs = [
    {"host": "worker1_host_ip", "user": "root", "password": "password", "database": "sakila"},
    {"host": "worker2_host_ip", "user": "root", "password": "password", "database": "sakila"}
]

# Connect to MySQL database and execute query
def execute_query(db_config, query):
    try:
        conn = mysql.connector.connect(
            host=db_config["host"],
            user=db_config["user"],
            password=db_config["password"],
            database=db_config["database"]
        )
        cursor = conn.cursor()
        cursor.execute(query)
        results = cursor.fetchall()
        conn.close()
        return results
    except mysql.connector.Error as err:
        return {"error": str(err)}

# Direct Hit: Routes all write requests to the manager and read requests to random workers
def direct_hit(query, write=False):
    db_config = manager_db if write else random.choice(worker_dbs)
    return execute_query(db_config, query)

# Random: Routes read requests randomly across worker nodes
def random_route(query):
    db_config = random.choice(worker_dbs)
    return execute_query(db_config, query)

# Customized: Routes read requests to the worker with the lowest ping time
def customized_route(query):
    db_config = min(worker_dbs, key=lambda db: ping(db["host"]))
    return execute_query(db_config, query)

@app.route('/query', methods=['POST'])
def handle_query():
    data = request.get_json()
    query = data.get("query")
    routing_strategy = data.get("strategy", "direct")  # Default to direct if not provided
    write = data.get("write", False)

    if routing_strategy == "direct":
        result = direct_hit(query, write=write)
    elif routing_strategy == "random":
        result = random_route(query)
    elif routing_strategy == "customized":
        result = customized_route(query)
    else:
        return jsonify({"error": "Invalid routing strategy specified"}), 400

    return jsonify(result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
