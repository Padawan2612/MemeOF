# Usar la imagen base de Python
FROM python:3.9-slim

# Establecer el directorio de trabajo dentro del contenedor
WORKDIR /app

# Instalar dependencias del sistema necesarias para psycopg2
RUN apt-get update && apt-get install -y gcc libpq-dev

# Copiar el archivo requirements.txt al contenedor
COPY requirements.txt /app/

# Actualizar pip y luego instalar las dependencias
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación al contenedor
COPY . /app/

# Exponer el puerto que usará la app
EXPOSE 5000

# Comando para iniciar la aplicación usando Flask
CMD ["flask", "run", "--host=0.0.0.0"]
