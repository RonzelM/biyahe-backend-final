from flask import Flask, jsonify, request, render_template
from database import get_db_connection
import os
from werkzeug.utils import secure_filename
import jwt
import datetime
from flask_bcrypt import Bcrypt

app = Flask(__name__)

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ================= HOME =================
@app.route('/')
def home():
    return render_template('book.html')


@app.route('/testdb')
def checkdb():
    return jsonify({"message": "Backend connected 🚗"})


# ================= VEHICLES =================
@app.route('/vehicle/<int:id>', methods=['GET'])
def get_vehicle(id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT name, status FROM vehicles
        WHERE id = %s AND is_deleted = FALSE
    """, (id,))

    vehicle = cursor.fetchone()

    conn.close()

    if not vehicle:
        return jsonify({"error": "Vehicle not available"}), 404

    return jsonify({
        "name": vehicle[0],
        "status": vehicle[1]
    })
    
    
#Get all vehicles
@app.route('/vehicles', methods=['GET'])
def get_vehicles():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, name, plate_number, status, image_url, transmission_type
    FROM vehicles
    WHERE is_deleted = FALSE
""")

    rows = cursor.fetchall()
    conn.close()

    return jsonify([
        {
            "id": r[0],
            "name": r[1],
            "plate_number": r[2],
            "status": r[3],
            "image_url": r[4],
            "transmission_type": r[5]
        }
        for r in rows
    ])


# ================= UPLOAD IMAGE =================
@app.route('/upload-image', methods=['POST'])
def upload_image():
    if 'image' not in request.files:
        return jsonify({"error": "No image provided"}), 400

    file = request.files['image']

    if file.filename == '':
        return jsonify({"error": "Empty filename"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    image_url = request.host_url.rstrip('/') + f"/static/uploads/{filename}"

    return jsonify({"image_url": image_url})


# ================= PLATE GENERATOR =================
def generate_plate(vehicle_type, cursor):
    prefix_map = {
        "Sedan": "SED",
        "SUV": "SUV",
        "Van": "VAN",
        "Minivan": "MIN",
        "Truck": "TRK",
        "Hybrid": "HYB",
        "Pickup": "PCK"
    }

    prefix = prefix_map.get(vehicle_type, "CAR")

    cursor.execute("""
        SELECT plate_number FROM vehicles
        WHERE plate_number LIKE %s
    """, (f"{prefix}-%",))

    rows = cursor.fetchall()

    numbers = []
    for row in rows:
        try:
            numbers.append(int(row[0].split("-")[1]))
        except:
            pass

    return f"{prefix}-{str(max(numbers, default=0) + 1).zfill(4)}"


# ================= ADD VEHICLE =================
@app.route('/vehicles', methods=['POST'])
def add_vehicle():
    data = request.json

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        plate_number = generate_plate(data['type'], cursor)

        # 1. INSERT VEHICLE
        cursor.execute("""
            INSERT INTO vehicles (name, plate_number, status, tracker_id, image_url,transmission_type)
            VALUES (%s, %s, %s, %s, %s,%s)
        """, (
            data['name'],
            plate_number,
            "available",
            data.get('tracker_id'),
            data.get('image_url'),
            data.get('transmission_type')
        ))

        # 2. LINK TRACKER (IMPORTANT FIX)
        if data.get('tracker_id'):
            cursor.execute("""
                UPDATE trackers
                SET gps_status = 'linked',
                    is_online = 1,
                    last_updated = NOW()
                WHERE tracker_id = %s
            """, (data['tracker_id'],))

        conn.commit()

        return jsonify({
            "message": "Vehicle added",
            "plate_number": plate_number
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()
        
        
        
# ================= SAFE DELETE (SOFT DELETE) =================
@app.route('/vehicles/<int:id>', methods=['DELETE'])
def delete_vehicle(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # ================= 1. CHECK ACTIVE BOOKING =================
        cursor.execute("""
            SELECT id FROM bookings
            WHERE vehicle_id = %s AND booking_status = 'accepted'
        """, (id,))
        active = cursor.fetchone()

        if active:
            return jsonify({
                "error": "Cannot delete vehicle with active booking"
            }), 400

        # ================= 2. GET TRACKER =================
        cursor.execute("""
            SELECT tracker_id FROM vehicles WHERE id = %s
        """, (id,))
        vehicle = cursor.fetchone()

        tracker_id = vehicle["tracker_id"] if vehicle else None

        # ================= 3. FREE TRACKER =================
        if tracker_id:
            cursor.execute("""
                UPDATE trackers
                SET is_online = 0,
                    gps_status = 'available',
                    last_updated = NOW()
                WHERE tracker_id = %s
            """, (tracker_id,))

        # ================= 4. SOFT DELETE VEHICLE =================
        cursor.execute("""
            UPDATE vehicles
            SET is_deleted = TRUE,
                tracker_id = NULL
            WHERE id = %s
        """, (id,))

        conn.commit()

        return jsonify({
            "message": "Vehicle archived and tracker released successfully"
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()
        
        
# ================= CREATE BOOKING =================
@app.route('/book', methods=['POST'])
def book():
    conn = None
    try:
        data = request.json

        # ================= VALIDATION =================
        required_fields = ['vehicle_id', 'name', 'phone', 'start_date', 'end_date']

        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({"error": f"{field} is required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # ================= CHECK VEHICLE =================
        cursor.execute("""
            SELECT id FROM vehicles
            WHERE id = %s AND is_deleted = FALSE
        """, (data['vehicle_id'],))

        vehicle = cursor.fetchone()

        if not vehicle:
            return jsonify({"error": "Vehicle not found"}), 404

        # ================= DATE CONFLICT =================
        cursor.execute("""
            SELECT id FROM bookings
            WHERE vehicle_id = %s
            AND booking_status IN ('pending', 'accepted', 'ongoing')
            AND (
                (%s BETWEEN start_date AND end_date)
                OR (%s BETWEEN start_date AND end_date)
                OR (start_date BETWEEN %s AND %s)
            )
        """, (
            data['vehicle_id'],
            data['start_date'],
            data['end_date'],
            data['start_date'],
            data['end_date']
        ))

        conflict = cursor.fetchone()

        if conflict:
            return jsonify({"error": "Vehicle already booked for selected dates"}), 400

        # ================= CUSTOMER =================
        phone = data['phone'].replace("+63", "0")

        cursor.execute("""
            SELECT customer_id FROM customers WHERE phone = %s
        """, (phone,))

        customer = cursor.fetchone()

        if customer:
            customer_id = customer[0]
        else:
            cursor.execute("""
                INSERT INTO customers (name, phone)
                VALUES (%s, %s)
            """, (data['name'], phone))

            conn.commit()
            customer_id = cursor.lastrowid

        # ================= CREATE BOOKING =================
        cursor.execute("""
            INSERT INTO bookings 
            (customer_id, vehicle_id, start_date, end_date, booking_status)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            customer_id,
            data['vehicle_id'],
            data['start_date'],
            data['end_date'],
            "pending"
        ))

        conn.commit()

        return jsonify({"message": "Booking created"}), 201

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        if conn:
            conn.close()

# ================= GET BOOKINGS =================
@app.route('/bookings', methods=['GET'])
def get_bookings():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            b.id,
            c.name,
            c.phone,
            v.name,
            v.plate_number,
            b.start_date,
            b.end_date,
            b.booking_status,
            b.decline_reason
        FROM bookings b
        JOIN customers c ON b.customer_id = c.customer_id
        JOIN vehicles v ON b.vehicle_id = v.id
    """)

    rows = cursor.fetchall()

    bookings = []
    for row in rows:
        bookings.append({
            "id": row[0],
            "customer_name": row[1],
            "phone": row[2],
            "vehicle_name": row[3],
            "plate_number": row[4],
            "start_date": str(row[5]),
            "end_date": str(row[6]),
            "status": row[7],
            "decline_reason": row[8]
        })

    conn.close()
    return jsonify(bookings)


# ================= APPROVE BOOKING =================
@app.route('/bookings/approve/<int:id>', methods=['POST'])
def approve_booking(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT vehicle_id, start_date, end_date
            FROM bookings
            WHERE id=%s
        """, (id,))

        booking = cursor.fetchone()

        if not booking:
            return jsonify({"error": "Booking not found"}), 404

        vehicle_id = booking['vehicle_id']

        cursor.execute("""
            SELECT id FROM bookings
            WHERE vehicle_id=%s
            AND booking_status='accepted'
            AND NOT (end_date < %s OR start_date > %s)
        """, (vehicle_id, booking['start_date'], booking['end_date']))

        conflict = cursor.fetchone()

        if conflict:
            cursor.execute("""
                UPDATE bookings
                SET booking_status='declined',
                    decline_reason=%s
                WHERE id=%s
            """, ("Vehicle already booked", id))

            conn.commit()

            return jsonify({
                "error": "Conflict detected",
                "reason": "Vehicle already booked"
            }), 400

        cursor.execute("""
            UPDATE bookings
            SET booking_status='accepted'
            WHERE id=%s
        """, (id,))

        cursor.execute("""
            UPDATE vehicles
            SET status='unavailable'
            WHERE id=%s
        """, (vehicle_id,))

        conn.commit()

        return jsonify({"message": "Approved"}), 200

    finally:
        conn.close()

# ================= DECLINE BOOKING =================
@app.route('/bookings/decline/<int:id>', methods=['POST'])
def decline_booking(id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT vehicle_id, booking_status
            FROM bookings
            WHERE id=%s
        """, (id,))

        booking = cursor.fetchone()

        if booking and booking['booking_status'] == 'accepted':
            cursor.execute("""
                UPDATE vehicles
                SET status='available'
                WHERE id=%s
            """, (booking['vehicle_id'],))

        cursor.execute("""
            UPDATE bookings
            SET booking_status='declined',
                decline_reason=%s
            WHERE id=%s
        """, ("Manually declined by admin", id))

        conn.commit()

        return jsonify({"message": "Declined"}), 200

    finally:
        conn.close()
        
        
# ================= TRACKER =================
@app.route('/gps/available', methods=['GET'])
def get_available_gps():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT tracker_id, is_online, gps_status
        FROM trackers
        WHERE gps_status = 'GOOD FIX'
    """)

    rows = cursor.fetchall()
    conn.close()

    return jsonify(rows)


# ================= REGISTER TRACKER =================
@app.route('/tracker/register', methods=['POST'])
def register_tracker():
    data = request.get_json()

    if not data or 'tracker_id' not in data:
        return jsonify({"error": "tracker_id is required"}), 400

    tracker_id = data['tracker_id']
    is_online = data.get('is_online', 1)
    gps_status = data.get('gps_status', 'unknown')
    last_updated = data.get('last_updated')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # ================= UPSERT (INSERT OR UPDATE) =================
        cursor.execute("""
            INSERT INTO trackers (tracker_id, is_online, gps_status, last_updated)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                is_online = VALUES(is_online),
                gps_status = VALUES(gps_status),
                last_updated = VALUES(last_updated)
        """, (
            tracker_id,
            is_online,
            gps_status,
            last_updated
        ))

        conn.commit()

        return jsonify({
            "message": "Tracker synced successfully",
            "tracker_id": tracker_id
        }), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()
        
        
        
        
        
#Scann
@app.route('/scan', methods=['POST'])
def scan_vehicle():
    conn = None
    try:
        data = request.json
        vehicle_id = data['vehicle_id']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # ================= GET ACTIVE BOOKING =================
        cursor.execute("""
            SELECT id, booking_status
            FROM bookings
            WHERE vehicle_id = %s
            AND booking_status IN ('accepted', 'ongoing')
            ORDER BY id DESC
            LIMIT 1
        """, (vehicle_id,))

        booking = cursor.fetchone()

        if not booking:
            return jsonify({"error": "No active booking found"}), 404

        booking_id = booking['id']
        status = booking['booking_status']

        # ================= CHECK-IN =================
        if status == 'accepted':
            cursor.execute("""
                UPDATE bookings
                SET booking_status = 'ongoing'
                WHERE id = %s
            """, (booking_id,))

            cursor.execute("""
                UPDATE vehicles
                SET status = 'unavailable'
                WHERE id = %s
            """, (vehicle_id,))

            conn.commit()

            return jsonify({
                "message": "CHECK-IN SUCCESS",
                "booking_id": booking_id,
                "status": "ongoing"
            }), 200

        # ================= CHECK-OUT =================
        if status == 'ongoing':
            cursor.execute("""
                UPDATE bookings
                SET booking_status = 'completed'
                WHERE id = %s
            """, (booking_id,))

            cursor.execute("""
                UPDATE vehicles
                SET status = 'available'
                WHERE id = %s
            """, (vehicle_id,))

            conn.commit()

            return jsonify({
                "message": "CHECK-OUT SUCCESS",
                "booking_id": booking_id,
                "status": "completed"
            }), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        if conn:
            conn.close()
    
    # Scan QR owner side (UPDATED: GPS OPTIONAL VERSION)
@app.route('/scan-action/<value>', methods=['POST'])
def scan_action(value):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        vehicle = None

        # ================= 1. TRY TRACKER MODE =================
        cursor.execute("""
            SELECT id FROM vehicles
            WHERE tracker_id = %s AND is_deleted = FALSE
        """, (value,))
        vehicle = cursor.fetchone()

        # ================= 2. FALLBACK: VEHICLE ID MODE =================
        if not vehicle:
            cursor.execute("""
                SELECT id FROM vehicles
                WHERE id = %s AND is_deleted = FALSE
            """, (value,))
            vehicle = cursor.fetchone()

        # ================= 3. STILL NOT FOUND =================
        if not vehicle:
            return jsonify({"error": "Vehicle not found"}), 404

        vehicle_id = vehicle['id']

        # ================= 4. GET ACTIVE BOOKING =================
        cursor.execute("""
            SELECT id, booking_status 
            FROM bookings
            WHERE vehicle_id = %s
            AND booking_status IN ('accepted', 'ongoing')
            ORDER BY id DESC
            LIMIT 1
        """, (vehicle_id,))

        booking = cursor.fetchone()

        # ================= 5. NO BOOKING =================
        if not booking:
            return jsonify({
                "message": "No active booking",
                "action": "track_only",
                "vehicle_id": vehicle_id
            }), 200

        booking_id = booking['id']
        status = booking['booking_status']

        # ================= CASE A: START TRIP =================
        if status == 'accepted':
            cursor.execute("""
                UPDATE bookings
                SET booking_status = 'ongoing'
                WHERE id = %s
            """, (booking_id,))

            cursor.execute("""
                UPDATE vehicles
                SET status = 'unavailable'
                WHERE id = %s
            """, (vehicle_id,))

            conn.commit()

            return jsonify({
                "message": "Trip started",
                "action": "start_trip",
                "vehicle_id": vehicle_id
            }), 200

        # ================= CASE B: END TRIP =================
        elif status == 'ongoing':
            cursor.execute("""
                UPDATE bookings
                SET booking_status = 'completed'
                WHERE id = %s
            """, (booking_id,))

            cursor.execute("""
                UPDATE vehicles
                SET status = 'available'
                WHERE id = %s
            """, (vehicle_id,))

            conn.commit()

            return jsonify({
                "message": "Trip completed",
                "action": "end_trip",
                "vehicle_id": vehicle_id
            }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()
        

bcrypt = Bcrypt(app)

SECRET_KEY = "byahe_secret"

#Login 
@app.route('/login', methods=['POST'])
def login():
    data = request.json

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM users WHERE email=%s", (data['email'],))
    user = cursor.fetchone()

    if not user:
        conn.close()
        return jsonify({"message": "Invalid credentials"}), 401

    if not bcrypt.check_password_hash(user['password'], data['password']):
        conn.close()
        return jsonify({"message": "Invalid credentials"}), 401

    token = jwt.encode({
        "user_id": user['id'],
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1)
    }, SECRET_KEY, algorithm="HS256")

    conn.close()

    return jsonify({"token": token})
        
# Temporary
@app.route('/create-owner')
def create_owner():
    conn = get_db_connection()
    cursor = conn.cursor()

    hashed = bcrypt.generate_password_hash("admin123").decode('utf-8')

    cursor.execute("SELECT * FROM users WHERE email=%s", ("owner@byahe.com",))
    exists = cursor.fetchone()

    if exists:
        conn.close()
        return jsonify({"message": "Owner already exists"})

    cursor.execute("""
        INSERT INTO users (email, password)
        VALUES (%s, %s)
    """, ("owner@byahe.com", hashed))

    conn.commit()
    conn.close()

    return jsonify({"message": "Owner created"})
        
# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)

# Sample edited
