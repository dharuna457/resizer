from flask import Flask, render_template, request, send_file, jsonify, session
from PIL import Image, ImageEnhance, ImageFilter, ExifTags
import io
import base64
import os
import uuid
from werkzeug.utils import secure_filename
import zipfile
from datetime import datetime
import json

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure upload and temp directories exist
UPLOAD_FOLDER = 'uploads'
TEMP_FOLDER = 'temp'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_image_info(image_path):
    """Extract comprehensive image information"""
    with Image.open(image_path) as img:
        info = {
            'width': img.width,
            'height': img.height,
            'format': img.format,
            'mode': img.mode,
            'size_bytes': os.path.getsize(image_path)
        }
        
        # Try to get EXIF data
        try:
            exif = img._getexif()
            if exif:
                info['exif'] = {}
                for tag_id, value in exif.items():
                    tag = ExifTags.TAGS.get(tag_id, tag_id)
                    info['exif'][tag] = str(value)
        except:
            info['exif'] = {}
            
        return info

def resize_image(image_path, options):
    """Resize image with various options"""
    with Image.open(image_path) as img:
        # Auto-rotate based on EXIF
        try:
            for orientation in ExifTags.TAGS.keys():
                if ExifTags.TAGS[orientation] == 'Orientation':
                    break
            exif = img._getexif()
            if exif is not None:
                orientation_value = exif.get(orientation)
                if orientation_value == 3:
                    img = img.rotate(180, expand=True)
                elif orientation_value == 6:
                    img = img.rotate(270, expand=True)
                elif orientation_value == 8:
                    img = img.rotate(90, expand=True)
        except:
            pass
        
        original_width, original_height = img.size
        
        # Calculate new dimensions
        if options['unit'] == 'percent':
            new_width = int(original_width * options['width'] / 100)
            new_height = int(original_height * options['height'] / 100)
        elif options['unit'] == 'pixels':
            new_width = int(options['width'])
            new_height = int(options['height'])
        elif options['unit'] == 'inches':
            dpi = options.get('dpi', 72)
            new_width = int(options['width'] * dpi)
            new_height = int(options['height'] * dpi)
        elif options['unit'] == 'centimeters':
            dpi = options.get('dpi', 72)
            new_width = int(options['width'] * dpi / 2.54)
            new_height = int(options['height'] * dpi / 2.54)
        
        # Ensure minimum size
        new_width = max(1, new_width)
        new_height = max(1, new_height)
        
        # Resize with quality options
        resample_method = Image.LANCZOS
        if options.get('resample_method') == 'nearest':
            resample_method = Image.NEAREST
        elif options.get('resample_method') == 'bilinear':
            resample_method = Image.BILINEAR
        elif options.get('resample_method') == 'bicubic':
            resample_method = Image.BICUBIC
        
        # Create new image with background
        if options.get('background_color') and img.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', (new_width, new_height), options['background_color'])
            img = img.convert('RGBA')
            resized = img.resize((new_width, new_height), resample_method)
            background.paste(resized, (0, 0), resized)
            result_img = background
        else:
            result_img = img.resize((new_width, new_height), resample_method)
        
        # Apply enhancements
        if options.get('brightness', 1.0) != 1.0:
            enhancer = ImageEnhance.Brightness(result_img)
            result_img = enhancer.enhance(options['brightness'])
        
        if options.get('contrast', 1.0) != 1.0:
            enhancer = ImageEnhance.Contrast(result_img)
            result_img = enhancer.enhance(options['contrast'])
        
        if options.get('saturation', 1.0) != 1.0:
            enhancer = ImageEnhance.Color(result_img)
            result_img = enhancer.enhance(options['saturation'])
        
        if options.get('sharpness', 1.0) != 1.0:
            enhancer = ImageEnhance.Sharpness(result_img)
            result_img = enhancer.enhance(options['sharpness'])
        
        # Apply filters
        if options.get('blur', 0) > 0:
            result_img = result_img.filter(ImageFilter.GaussianBlur(options['blur']))
        
        if options.get('sharpen'):
            result_img = result_img.filter(ImageFilter.SHARPEN)
        
        return result_img

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file selected'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if file and allowed_file(file.filename):
        # Generate unique filename
        file_id = str(uuid.uuid4())
        filename = secure_filename(file.filename)
        file_extension = filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{file_id}.{file_extension}"
        
        filepath = os.path.join(UPLOAD_FOLDER, unique_filename)
        file.save(filepath)
        
        # Store file info in session
        session['current_file'] = {
            'id': file_id,
            'original_name': filename,
            'path': filepath
        }
        
        # Get image information
        info = get_image_info(filepath)
        
        # Create base64 preview
        with Image.open(filepath) as img:
            # Create thumbnail for preview
            img.thumbnail((300, 300), Image.LANCZOS)
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=85)
            buffer.seek(0)
            preview_b64 = base64.b64encode(buffer.getvalue()).decode()
        
        return jsonify({
            'success': True,
            'file_id': file_id,
            'filename': filename,
            'info': info,
            'preview': f"data:image/jpeg;base64,{preview_b64}"
        })
    
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/resize', methods=['POST'])
def resize():
    if 'current_file' not in session:
        return jsonify({'error': 'No file uploaded'}), 400
    
    data = request.get_json()
    file_info = session['current_file']
    
    try:
        # Resize the image
        resized_img = resize_image(file_info['path'], data)
        
        # Save resized image
        output_format = data.get('format', 'JPEG').upper()
        if output_format == 'JPG':
            output_format = 'JPEG'
        
        result_id = str(uuid.uuid4())
        result_filename = f"{result_id}.{output_format.lower()}"
        result_path = os.path.join(TEMP_FOLDER, result_filename)
        
        save_options = {}
        if output_format == 'JPEG':
            save_options['quality'] = data.get('quality', 90)
            save_options['optimize'] = True
        elif output_format == 'PNG':
            save_options['optimize'] = True
        
        resized_img.save(result_path, format=output_format, **save_options)
        
        # Create preview
        preview_img = resized_img.copy()
        preview_img.thumbnail((300, 300), Image.LANCZOS)
        buffer = io.BytesIO()
        preview_img.save(buffer, format='JPEG', quality=85)
        buffer.seek(0)
        preview_b64 = base64.b64encode(buffer.getvalue()).decode()
        
        # Store result info
        session['last_result'] = {
            'id': result_id,
            'path': result_path,
            'filename': result_filename,
            'size': os.path.getsize(result_path),
            'width': resized_img.width,
            'height': resized_img.height
        }
        
        return jsonify({
            'success': True,
            'result_id': result_id,
            'preview': f"data:image/jpeg;base64,{preview_b64}",
            'info': {
                'width': resized_img.width,
                'height': resized_img.height,
                'size': os.path.getsize(result_path),
                'filename': result_filename
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<result_id>')
def download(result_id):
    if 'last_result' not in session or session['last_result']['id'] != result_id:
        return "File not found", 404
    
    result_info = session['last_result']
    return send_file(
        result_info['path'],
        as_attachment=True,
        download_name=result_info['filename'],
        mimetype='application/octet-stream'
    )

@app.route('/batch_resize', methods=['POST'])
def batch_resize():
    """Handle multiple files for batch processing"""
    if 'files' not in request.files:
        return jsonify({'error': 'No files uploaded'}), 400
    
    files = request.files.getlist('files')
    options = json.loads(request.form.get('options', '{}'))
    
    if not files:
        return jsonify({'error': 'No files selected'}), 400
    
    results = []
    batch_id = str(uuid.uuid4())
    
    # Create batch folder
    batch_folder = os.path.join(TEMP_FOLDER, batch_id)
    os.makedirs(batch_folder, exist_ok=True)
    
    for file in files:
        if file and allowed_file(file.filename):
            try:
                # Save original file
                filename = secure_filename(file.filename)
                temp_path = os.path.join(batch_folder, f"temp_{filename}")
                file.save(temp_path)
                
                # Resize
                resized_img = resize_image(temp_path, options)
                
                # Save result
                output_format = options.get('format', 'JPEG').upper()
                if output_format == 'JPG':
                    output_format = 'JPEG'
                
                result_filename = f"resized_{filename}"
                result_path = os.path.join(batch_folder, result_filename)
                
                save_options = {}
                if output_format == 'JPEG':
                    save_options['quality'] = options.get('quality', 90)
                
                resized_img.save(result_path, format=output_format, **save_options)
                
                results.append({
                    'original': filename,
                    'resized': result_filename,
                    'size': os.path.getsize(result_path)
                })
                
                # Clean up temp file
                os.remove(temp_path)
                
            except Exception as e:
                results.append({
                    'original': file.filename,
                    'error': str(e)
                })
    
    # Create ZIP file
    zip_path = os.path.join(TEMP_FOLDER, f"{batch_id}.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for result in results:
            if 'resized' in result:
                file_path = os.path.join(batch_folder, result['resized'])
                zipf.write(file_path, result['resized'])
    
    session['batch_result'] = {
        'id': batch_id,
        'zip_path': zip_path,
        'results': results
    }
    
    return jsonify({
        'success': True,
        'batch_id': batch_id,
        'results': results
    })

@app.route('/download_batch/<batch_id>')
def download_batch(batch_id):
    if 'batch_result' not in session or session['batch_result']['id'] != batch_id:
        return "Batch not found", 404
    
    batch_info = session['batch_result']
    return send_file(
        batch_info['zip_path'],
        as_attachment=True,
        download_name=f"resized_images_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
        mimetype='application/zip'
    )

@app.route('/presets')
def get_presets():
    """Get predefined resize presets"""
    presets = {
        'social_media': {
            'Instagram Square': {'width': 1080, 'height': 1080, 'unit': 'pixels'},
            'Instagram Portrait': {'width': 1080, 'height': 1350, 'unit': 'pixels'},
            'Facebook Cover': {'width': 820, 'height': 312, 'unit': 'pixels'},
            'Twitter Header': {'width': 1500, 'height': 500, 'unit': 'pixels'},
            'YouTube Thumbnail': {'width': 1280, 'height': 720, 'unit': 'pixels'},
        },
        'print': {
            '4x6 inch (300 DPI)': {'width': 4, 'height': 6, 'unit': 'inches', 'dpi': 300},
            '5x7 inch (300 DPI)': {'width': 5, 'height': 7, 'unit': 'inches', 'dpi': 300},
            '8x10 inch (300 DPI)': {'width': 8, 'height': 10, 'unit': 'inches', 'dpi': 300},
            'A4 (300 DPI)': {'width': 21, 'height': 29.7, 'unit': 'centimeters', 'dpi': 300},
        },
        'web': {
            'HD (1920x1080)': {'width': 1920, 'height': 1080, 'unit': 'pixels'},
            'Full HD (1920x1080)': {'width': 1920, 'height': 1080, 'unit': 'pixels'},
            '4K (3840x2160)': {'width': 3840, 'height': 2160, 'unit': 'pixels'},
            'Mobile (375x667)': {'width': 375, 'height': 667, 'unit': 'pixels'},
        }
    }
    return jsonify(presets)

if __name__ == '__main__':
    app.run(debug=True)