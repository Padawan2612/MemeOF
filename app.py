from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
import os
import boto3
from werkzeug.utils import secure_filename
from botocore.exceptions import ClientError
from dotenv import load_dotenv
import uuid
import requests

# Cargar las variables de entorno desde el archivo .env
load_dotenv()

app = Flask(__name__)

# Configuración de la base de datos
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f'postgresql://{os.getenv("DB_USER")}:{os.getenv("DB_PASSWORD")}'
    f'@{os.getenv("DB_HOST")}/{os.getenv("DB_NAME")}'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inicializar SQLAlchemy
db = SQLAlchemy(app)

# Crear cliente de S3
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION')
)

# Obtener las credenciales de Immaga desde el archivo .env
IMAGGA_API_KEY = os.getenv('IMAGGA_API_KEY')
IMAGGA_API_SECRET = os.getenv('IMAGGA_API_SECRET')

# Definir el modelo para la tabla memes
class Meme(db.Model):
    __tablename__ = 'memes'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    descripcion = db.Column(db.String(255), nullable=False)
    ruta = db.Column(db.String(255), nullable=False)
    usuario = db.Column(db.String(100), nullable=False)
    cargada = db.Column(db.DateTime, default=db.func.now())

# Definir el modelo para la tabla etiquetas
class Etiqueta(db.Model):
    __tablename__ = 'etiquetas'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    meme_id = db.Column(db.String(36), db.ForeignKey('memes.id', ondelete='CASCADE'), nullable=False)
    etiqueta = db.Column(db.String(100), nullable=False)
    confianza = db.Column(db.Float, nullable=False)

# Crear las tablas en la base de datos
with app.app_context():
    db.create_all()
    print("Tablas creadas exitosamente.")

# Función para subir la imagen a S3
def upload_to_s3(file):
    try:
        # Verificar si el archivo es válido
        if not file or not file.filename:
            print("El archivo no tiene un nombre válido.")
            return None
        
        # Asegurar que el nombre del archivo es seguro
        filename = secure_filename(file.filename)
        if not filename:
            print("El nombre del archivo no es válido.")
            return None
        
        # Ruta donde se almacenará en el bucket
        file_path = f"memes/{filename}"
        print(f"Ruta en S3: {file_path}")

        # Validar las variables de entorno
        bucket_name = os.getenv('AWS_BUCKET_NAME')
        region = os.getenv('AWS_REGION')
        if not bucket_name or not region:
            print("Faltan las variables de entorno necesarias.")
            return None
        
        # Subir el archivo al bucket S3
        s3_client.upload_fileobj(
            file,
            bucket_name,
            file_path,
            ExtraArgs={'ACL': 'public-read', 'ContentType': file.content_type}
        )
        print("Archivo subido exitosamente a S3.")

        # Construir la URL pública del archivo
        file_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{file_path}"
        print(f"URL del archivo: {file_url}")
        return file_url

    except ClientError as e:
        print(f"Error al subir la imagen a S3: {e}")
        print(e.response)  # Muestra detalles del error
        return None

    except Exception as e:
        print(f"Error inesperado: {e}")
        return None

# Función para obtener etiquetas automáticas de Immaga
def obtener_etiquetas_immaga(imagen_url):
    api_url = 'https://api.imagga.com/v2/tags'
    params = {'image_url': imagen_url}

    # Cabeceras de autenticación usando las claves API
    auth = (IMAGGA_API_KEY, IMAGGA_API_SECRET)

    try:
        # Realizar la solicitud GET con las API Keys en la autenticación básica
        response = requests.get(api_url, auth=auth, params=params)

        # Verificar si la respuesta fue exitosa
        if response.status_code == 200:
            data = response.json()
            etiquetas = [item['tag']['en'] for item in data['result']['tags']]
            print(f"Etiquetas obtenidas de Immaga: {etiquetas}")
            return etiquetas
        else:
            print(f"Error al obtener etiquetas de Immaga: {response.status_code} - {response.text}")
            return []
    
    except requests.exceptions.RequestException as e:
        print(f"Error en la solicitud: {e}")
        return []

# Ruta de inicio
@app.route('/')
def index():
    return render_template('index.html', message="¡Bienvenido a MemeDB! Usa las rutas '/upload' para subir memes y '/search' para buscarlos.")

# Ruta para cargar memes
@app.route('/upload', methods=['GET', 'POST'])
def upload_meme():
    if request.method == 'POST':
        descripcion = request.form['descripcion']
        usuario = request.form['usuario']
        archivo = request.files['imagen']
        
        if archivo:
            # Subir la imagen a S3
            ruta_imagen = upload_to_s3(archivo)
            if ruta_imagen is None:
                return "Error al subir la imagen. Inténta nuevamente."

            # Obtener etiquetas automáticas de Immaga
            etiquetas_automáticas = obtener_etiquetas_immaga(ruta_imagen)
            if not etiquetas_automáticas:
                etiquetas_automáticas = []

            # Crear nuevo meme en la base de datos
            meme = Meme(descripcion=descripcion, ruta=ruta_imagen, usuario=usuario)
            db.session.add(meme)
            db.session.commit()

            # Agregar etiquetas personalizadas y automáticas a la base de datos
            etiquetas_personalizadas = request.form['etiquetas'].split(',') if 'etiquetas' in request.form else []
            all_etiquetas = etiquetas_personalizadas + etiquetas_automáticas

            for etiqueta in all_etiquetas:
                etiqueta_obj = Etiqueta(meme_id=meme.id, etiqueta=etiqueta.strip(), confianza=0.95)
                db.session.add(etiqueta_obj)
            db.session.commit()

            # Pasar las etiquetas al renderizado
            return render_template('upload.html', etiquetas=all_etiquetas, meme=meme)

    return render_template('upload.html')

# Ruta para buscar memes por etiqueta o descripción
@app.route('/search', methods=['GET'])
def search_meme():
    query = request.args.get('query')
    memes = []

    if query:
        memes = Meme.query.filter(Meme.descripcion.contains(query) | Meme.usuario.contains(query)).all()
        etiquetas = Etiqueta.query.filter(Etiqueta.etiqueta.contains(query)).all()
        meme_ids = [etiqueta.meme_id for etiqueta in etiquetas]
        memes += Meme.query.filter(Meme.id.in_(meme_ids)).all()
    else:
        memes = Meme.query.all()

    memes = list(set(memes))  # Eliminar duplicados

    # Obtener las etiquetas asociadas a los memes encontrados y limitar a 5
    meme_etiquetas = {}
    for meme in memes:
        etiquetas = Etiqueta.query.filter_by(meme_id=meme.id).limit(5).all()  # Limitar a 5 etiquetas
        meme_etiquetas[meme.id] = [etiqueta.etiqueta for etiqueta in etiquetas]

    return render_template('search.html', memes=memes, meme_etiquetas=meme_etiquetas)




# Iniciar la aplicación
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
