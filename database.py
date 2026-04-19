import mysql.connector

def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",  # put your MySQL password here if you have one
        database="car_rental",
        port = 3307
    )