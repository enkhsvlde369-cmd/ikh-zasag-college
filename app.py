
import os
import secrets
import sqlite3
import hmac
import uuid
from pathlib import Path
from functools import wraps
from urllib.parse import quote

from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, jsonify, redirect, render_template,
    request, session, send_from_directory, url_for
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "programs.db"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}

load_dotenv(BASE_DIR / ".env")

app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax"
)

PROGRAMS = [
    ('hevleliin-grafik', 'Хэвлэлийн график дизайнч'),
    ('hoolnii-uilchilgee', 'Хоолны үйлчилгээ'),
    ('huvtsas-design', 'Хувцас дизайнч'),
    ('huvtsas-zohion-butegch', 'Хувцасны загвар зохион бүтээгч'),
    ('suvilagchiin-tuslah', 'Сувилагчийн туслах'),
    ('barilgiin-santehnik', 'Барилгын сантехник, хоолой угсралт'),
    ('barilgiin-butets', 'Барилгын бүтэц угсралт'),
    ('nyagtlan-tuslah', 'Нягтлан бодох бүртгэлийн туслах ажилтан'),
    ('office-bichig-hereg', 'Оффис ба бичиг хэргийн ажил'),
    ('goo-saihan', 'Гоо сайхны үйлчилгээ'),
    ('ayalal-1plus1', 'Аялал жуулчлалын 1+1'),
    ('huni-noots', 'Хүний нөөцийн менежмент'),
    ('taiz-delgets', 'Тайз дэлгэцийн дизайн технологи'),
    ('web-design', 'Вэб дизайн'),
    ('oyomol-butegdehuun', 'Оёмол бүтээгдэхүүн үйлдвэрлэл'),
    ('us-chin-goo-saihan', 'Үсчин, гоо сайхан'),
    ('ayalal-uilchilgee', 'Аялал жуулчлалын үйлчилгээ'),
    ('zochid-buudal', 'Зочид буудал, зоогийн газрын үйлчилгээ'),
]


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS programs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                href TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                program_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                image_path TEXT,
                published INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Older databases need this column added once.
        news_columns = {
            row['name'] for row in conn.execute("PRAGMA table_info(news)").fetchall()
        }
        if 'image_path' not in news_columns:
            conn.execute("ALTER TABLE news ADD COLUMN image_path TEXT")

        count = conn.execute(
            'SELECT COUNT(*) FROM programs'
        ).fetchone()[0]

        if count == 0:
            conn.executemany(
                """
                INSERT INTO programs
                (slug, name, href, active, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        slug,
                        name,
                        f'program-details.html?program={quote(slug)}',
                        1,
                        i
                    )
                    for i, (slug, name) in enumerate(PROGRAMS)
                ]
            )


def csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return session['_csrf_token']


app.jinja_env.globals['csrf_token'] = csrf_token


def check_csrf():
    token = request.form.get('_csrf_token', '')
    expected = session.get('_csrf_token', '')

    if (
        not token
        or not expected
        or not secrets.compare_digest(token, expected)
    ):
        abort(
            400,
            description=(
                'Хүсэлтийн хамгаалалтын токен буруу байна. '
                'Хуудсаа дахин ачаалаад оролдоно уу.'
            )
        )


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(
                url_for('admin_login', next=request.path)
            )
        return fn(*args, **kwargs)
    return wrapped


def clean_slug(value):
    value = value.strip().lower()
    allowed = set('abcdefghijklmnopqrstuvwxyz0123456789-')

    if (
        not value
        or any(ch not in allowed for ch in value)
        or value.startswith('-')
        or value.endswith('-')
    ):
        return None

    return value


@app.get('/')
def home():
    return send_from_directory(BASE_DIR, 'index.html')


@app.get('/api/programs')
def list_programs():
    with db() as conn:
        rows = conn.execute("""
            SELECT slug, name, href
            FROM programs
            WHERE active = 1
            ORDER BY sort_order, id
        """).fetchall()

    return jsonify([dict(row) for row in rows])


@app.get('/api/news')
def list_news():
    with db() as conn:
        rows = conn.execute("""
            SELECT id, title, body, image_path, created_at
            FROM news
            WHERE published = 1
            ORDER BY id DESC
            LIMIT 20
        """).fetchall()

    return jsonify([dict(row) for row in rows])


@app.get('/program-details.html')
def details():
    return send_from_directory(BASE_DIR, 'program-details.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    with db() as conn:
        programs = conn.execute("""
            SELECT name
            FROM programs
            WHERE active = 1
            ORDER BY sort_order, id
        """).fetchall()

        if request.method == 'POST':
            check_csrf()

            full_name = request.form.get('full_name', '').strip()
            phone = request.form.get('phone', '').strip()
            program_name = request.form.get('program_name', '').strip()

            valid_programs = [p['name'] for p in programs]

            if (
                not full_name
                or not phone
                or program_name not in valid_programs
            ):
                flash(
                    'Нэр, утас, мэргэжлээ зөв бөглөнө үү.',
                    'error'
                )

            elif len(full_name) > 120 or len(phone) > 30:
                flash(
                    'Нэр эсвэл утасны мэдээлэл хэт урт байна.',
                    'error'
                )

            else:
                conn.execute("""
                    INSERT INTO registrations
                    (full_name, phone, program_name)
                    VALUES (?, ?, ?)
                """, (full_name, phone, program_name))

                flash(
                    'Урьдчилсан бүртгэл амжилттай илгээгдлээ!',
                    'success'
                )
                return redirect(url_for('register'))

    return render_template('register.html', programs=programs)


def get_admin_data(conn):
    programs = conn.execute("""
        SELECT *
        FROM programs
        ORDER BY sort_order, id
    """).fetchall()

    registrations = conn.execute("""
        SELECT *
        FROM registrations
        ORDER BY id DESC
    """).fetchall()

    news = conn.execute("""
        SELECT *
        FROM news
        ORDER BY id DESC
    """).fetchall()

    return programs, registrations, news


@app.get('/admin')
@admin_required
def admin_dashboard():
    with db() as conn:
        programs, registrations, news = get_admin_data(conn)

    return render_template(
        'admin.html',
        programs=programs,
        registrations=registrations,
        news=news,
        edit_program=None
    )


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        check_csrf()

        username = os.getenv('ADMIN_USERNAME', 'admin')
        password = os.getenv('ADMIN_PASSWORD', '')

        submitted_username = request.form.get('username', '')
        submitted_password = request.form.get('password', '')

        if not password:
            flash(
                'Нэвтрэх нууц үг тохируулаагүй байна. '
                '.env файлд ADMIN_PASSWORD тохируулна уу.',
                'error'
            )

        elif (
            hmac.compare_digest(submitted_username, username)
            and hmac.compare_digest(submitted_password, password)
        ):
            session.clear()
            session['admin_logged_in'] = True
            session['_csrf_token'] = secrets.token_urlsafe(32)

            flash('Амжилттай нэвтэрлээ.', 'success')
            return redirect(url_for('admin_dashboard'))

        else:
            flash(
                'Нэвтрэх нэр эсвэл нууц үг буруу байна.',
                'error'
            )

    return render_template('admin_login.html')


@app.post('/admin/logout')
@admin_required
def admin_logout():
    check_csrf()
    session.clear()
    flash('Системээс гарлаа.', 'success')
    return redirect(url_for('admin_login'))


@app.post('/admin/add')
@admin_required
def admin_add():
    check_csrf()

    name = request.form.get('name', '').strip()
    slug = clean_slug(request.form.get('slug', ''))

    try:
        sort_order = int(request.form.get('sort_order', '0'))
    except ValueError:
        sort_order = 0

    if not name or len(name) > 180 or not slug:
        flash(
            'Мэргэжлийн нэр болон латин үсэг, тоо, зураас '
            'ашигласан зөв slug оруулна уу.',
            'error'
        )

    else:
        try:
            with db() as conn:
                conn.execute("""
                    INSERT INTO programs
                    (slug, name, href, active, sort_order)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    slug,
                    name,
                    f'program-details.html?program={quote(slug)}',
                    1,
                    sort_order
                ))

            flash(
                'Шинэ мэргэжил нэмэгдлээ. '
                'Шаардлагатай бол program-details.html дотор '
                'дэлгэрэнгүй танилцуулгыг мөн нэмээрэй.',
                'success'
            )

        except sqlite3.IntegrityError:
            flash(
                'Энэ slug аль хэдийн ашиглагдаж байна. '
                'Өөр slug сонгоно уу.',
                'error'
            )

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/edit/<int:program_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit(program_id):
    with db() as conn:
        program = conn.execute(
            'SELECT * FROM programs WHERE id = ?',
            (program_id,)
        ).fetchone()

        if not program:
            abort(404)

        if request.method == 'POST':
            check_csrf()

            name = request.form.get('name', '').strip()
            slug = clean_slug(request.form.get('slug', ''))

            try:
                sort_order = int(
                    request.form.get('sort_order', '0')
                )
            except ValueError:
                sort_order = 0

            active = (
                1 if request.form.get('active') == '1' else 0
            )

            if not name or len(name) > 180 or not slug:
                flash(
                    'Мэргэжлийн нэр болон зөв slug оруулна уу.',
                    'error'
                )

            else:
                try:
                    conn.execute("""
                        UPDATE programs
                        SET name = ?, slug = ?, href = ?,
                            active = ?, sort_order = ?
                        WHERE id = ?
                    """, (
                        name,
                        slug,
                        f'program-details.html?program={quote(slug)}',
                        active,
                        sort_order,
                        program_id
                    ))

                    flash(
                        'Мэргэжлийн мэдээлэл хадгалагдлаа.',
                        'success'
                    )
                    return redirect(url_for('admin_dashboard'))

                except sqlite3.IntegrityError:
                    flash(
                        'Энэ slug өөр мэргэжилд ашиглагдаж байна.',
                        'error'
                    )

        # Засах дэлгэц дээр мэргэжил болон бүртгэлүүдийг хоёуланг нь харуулна.
        program = conn.execute(
            'SELECT * FROM programs WHERE id = ?',
            (program_id,)
        ).fetchone()

        programs, registrations, news = get_admin_data(conn)

    return render_template(
        'admin.html',
        programs=programs,
        registrations=registrations,
        news=news,
        edit_program=program
    )


@app.post('/admin/delete/<int:program_id>')
@admin_required
def admin_delete(program_id):
    check_csrf()

    with db() as conn:
        conn.execute(
            'DELETE FROM programs WHERE id = ?',
            (program_id,)
        )

    flash(
        'Мэргэжил өгөгдлийн сангаас устгагдлаа.',
        'success'
    )
    return redirect(url_for('admin_dashboard'))


@app.post('/admin/news/add')
@admin_required
def admin_news_add():
    check_csrf()

    title = request.form.get('title', '').strip()
    body = request.form.get('body', '').strip()
    published = 1 if request.form.get('published') == '1' else 0
    image = request.files.get('image')
    image_path = None

    if not title or not body or len(title) > 180 or len(body) > 4000:
        flash(
            'Мэдээний гарчиг болон агуулгыг зөв бөглөнө үү. '
            'Гарчиг 180, агуулга 4000 тэмдэгтээс хэтрэхгүй.',
            'error'
        )
    elif image and image.filename:
        ext = Path(image.filename).suffix.lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            flash('Зөвхөн PNG, JPG, JPEG, WEBP эсвэл GIF зураг оруулна уу.', 'error')
            return redirect(url_for('admin_dashboard'))
        if image.mimetype and not image.mimetype.startswith('image/'):
            flash('Оруулсан файл зураг биш байна.', 'error')
            return redirect(url_for('admin_dashboard'))
        filename = f"{uuid.uuid4().hex}{ext}"
        image.save(UPLOAD_DIR / filename)
        image_path = f"/static/uploads/{filename}"

    if title and body and len(title) <= 180 and len(body) <= 4000:
        with db() as conn:
            conn.execute(
                """
                INSERT INTO news (title, body, image_path, published)
                VALUES (?, ?, ?, ?)
                """,
                (title, body, image_path, published)
            )
        flash('Мэдээ зурагтайгаа нэмэгдлээ. Сайт дээр харагдана.', 'success')

    return redirect(url_for('admin_dashboard'))

@app.post('/admin/news/delete/<int:news_id>')
@admin_required
def admin_news_delete(news_id):
    check_csrf()

    with db() as conn:
        conn.execute('DELETE FROM news WHERE id = ?', (news_id,))

    flash('Мэдээ устгагдлаа.', 'success')
    return redirect(url_for('admin_dashboard'))


init_db()


if __name__ == '__main__':

    print('Site: http://127.0.0.1:5000')
    print('Admin: http://127.0.0.1:5000/admin')

    app.run(
        debug=False,
        host='127.0.0.1',
        port=5000
    )
