#!/bin/bash

echo "Ejecutando main.py para configurar la infraestructura en AWS..."
python main.py

echo "Esperando a que main.py finalice..."
sleep 2  # Ajusta si es necesario; se usa para asegurarse de que los recursos se hayan desplegado.

echo "Ejecutando setup_replication.py para configurar la replicación..."
python setup_replication.py

echo "Instalación completa. Pruebas en progreso..."
