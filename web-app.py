from flask import Flask, render_template, send_from_directory, Response, request
import os, requests

# Memastikan Flask bisa membaca file di root directory sebagai static
static_folder = 'public'
app = Flask(__name__, static_folder=static_folder)

@app.route('/')
def index():
    # Mengirim file HTML utama kamu
    return send_from_directory(static_folder, 'manga_reader.v3.html')

@app.route('/<path:filename>')
def serve_static(filename):
    # Route ini penting agar Flask bisa melayani file .json dan gambar
    return send_from_directory(static_folder, filename)

@app.route('/get-pdf/<filename>')
def get_pdf(filename):
    # Mengirimkan file PDF ke browser dengan header yang benar
    # Flask secara otomatis mengatur Content-Type: application/pdf
    return send_from_directory(static_folder, filename)

@app.route('/proxy-pdf')
def proxy_pdf():
    # Ambil URL PDF dari parameter query
    target_url = request.args.get('url')
    if not target_url: return "URL tidak ditemukan", 400

    try:
        # Ambil file dari pihak ketiga
        response = requests.get(target_url, stream=True)
        
        # Teruskan file ke browser dengan header PDF
        return Response(
            response.iter_content(chunk_size=1024),
            content_type=response.headers.get('content-type', 'application/pdf')
        )
    except Exception as e: return str(e), 500

if __name__ == "__main__":
    # Mendapatkan port dari environment variable (Railway) atau default ke 5000
    port = int(os.environ.get("PORT", 5000))
    
    print(f"Server berjalan di: http://localhost:{port}/?slug=classmate")
    app.run(host='0.0.0.0', debug=True, port=port)