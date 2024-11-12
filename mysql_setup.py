import mysql.connector
import sys

# Configuration settings for MySQL manager and workers
config = {
    'host': 'localhost',  # Localhost since this runs on each instance
    'user': 'root',
    'password': '12345678',  # Replace with actual password
    'database': 'sakila'
}

# Set up the MySQL database and user permissions
def setup_mysql():
    try:
        # Connect to MySQL
        conn = mysql.connector.connect(
            host=config['host'],
            user=config['user'],
            password=config['password']
        )
        cursor = conn.cursor()
        
        # Create the Sakila database if it doesn't already exist
        cursor.execute("CREATE DATABASE IF NOT EXISTS sakila;")
        print("Sakila database created or already exists.")

        # Ensure remote access for user 'root' (for testing purposes)
        cursor.execute("CREATE USER IF NOT EXISTS 'root'@'%' IDENTIFIED BY 'your_mysql_root_password';")
        cursor.execute("GRANT ALL PRIVILEGES ON sakila.* TO 'root'@'%';")
        cursor.execute("FLUSH PRIVILEGES;")
        print("Remote access configured for root user.")

        # Close connections
        cursor.close()
        conn.close()
        print("MySQL setup complete.")

    except mysql.connector.Error as err:
        print(f"Error: {err}")
        sys.exit(1)

if __name__ == '__main__':
    setup_mysql()
